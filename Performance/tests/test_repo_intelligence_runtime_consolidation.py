"""Repo Intelligent 02 / Execution 01 canonical-runtime qualification.

These tests target the gaps this Execution closes: one declared owner per
runtime concern, explicit Performance coverage, causal skip/failure reasons,
and replay that does not duplicate cost/exposure event state.
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from midnight_performance.contracts import (
    ClaimKind,
    EntityKind,
    Observation,
    deterministic_identity,
)
from midnight_performance.memory_bridge import MemoryReadResult
from midnight_performance.observation_model import (
    ObservationEnvelope,
    ObservationLayer,
    ObservationType,
)
from midnight_performance.query_api import QueryAuthorization, QueryPage
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.ports import RepoIntelligenceProviders
from midnight_performance.repo_intelligence.runtime_contract import (
    CANONICAL_STAGE_INVENTORY,
    RuntimeStage,
    StageExecutionStatus,
    StageOwnershipStatus,
    StageReasonCode,
)
from midnight_performance.repo_intelligence_adapters import AIAccountingBudgetMeter
from midnight_performance.repo_intelligence_bridge import run_pipeline as bridge_run_pipeline
from midnight_performance.repo_intelligence_pipeline import (
    PERFORMANCE_HARD_LIMIT,
    _read_performance_evidence,
    run_pipeline,
)
from midnight_performance.repo_intelligence_store import RepoIntelligenceStore

PROJECT = deterministic_identity(EntityKind.PROJECT, "runtime-consolidation")
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


class PagingReads:
    """A deterministic Performance-port fake with an explicit paging extension."""

    def __init__(self, total: int) -> None:
        self.items = tuple(range(total))

    def query(self, authorization, *, kinds=None, subject=None, claim_kinds=None, limit=50):
        return QueryPage(1, authorization.project, self.items[:limit], len(self.items), limit)

    def query_page(
        self, authorization, *, kinds=None, subject=None, claim_kinds=None,
        limit=50, offset=0,
    ):
        return QueryPage(
            1, authorization.project, self.items[offset:offset + limit],
            len(self.items), limit, offset,
        )

    def projection(self, authorization, name):
        raise KeyError(name)


class OnePageReads(PagingReads):
    query_page = None


class EnvelopeReads:
    def __init__(self, envelopes):
        self._envelopes = tuple(envelopes)

    def query(self, authorization, *, kinds=None, subject=None, claim_kinds=None, limit=50):
        return QueryPage(
            1, authorization.project, self._envelopes[:limit],
            len(self._envelopes), limit,
        )

    def projection(self, authorization, name):
        raise KeyError(name)


class EmptyMemory:
    def read_context(self, project_key, *, size=20, query=None):
        return MemoryReadResult(available=True, records=())

    def propose_lesson(self, envelope):
        raise NotImplementedError


class BrokenMemory:
    def read_context(self, project_key, *, size=20, query=None):
        raise RuntimeError("fixture failure whose body must not become telemetry")

    def propose_lesson(self, envelope):
        raise NotImplementedError


def _change(i: int, at: datetime, *, passed: bool) -> tuple[ObservationEnvelope, ObservationEnvelope]:
    change_id = deterministic_identity(EntityKind.CHANGE_SET, f"runtime|change|{i}")
    change = Observation(
        identity=change_id,
        claim_kind=ClaimKind.OBSERVED,
        subject=deterministic_identity(EntityKind.REPOSITORY_SNAPSHOT, f"runtime|snap|{i}"),
        payload={"files": ["src/foo.py"]},
        observed_at=at,
        episode=None,
        source="runtime-test",
    )
    verification = Observation(
        identity=deterministic_identity(EntityKind.VERIFICATION_RUN, f"runtime|verify|{i}"),
        claim_kind=ClaimKind.OBSERVED,
        subject=change_id,
        payload={"files": ["src/foo.py"], "passed": passed},
        observed_at=at + timedelta(minutes=5),
        episode=None,
        source="runtime-test",
    )
    return (
        ObservationEnvelope(
            observation=change,
            project=PROJECT,
            observation_type=ObservationType.REPOSITORY_CHANGE,
            layer=ObservationLayer.RAW,
            provider="runtime-test",
            provider_event_id=f"c{i}",
        ),
        ObservationEnvelope(
            observation=verification,
            project=PROJECT,
            observation_type=ObservationType.VERIFICATION,
            layer=ObservationLayer.NORMALIZED,
            provider="runtime-test",
            provider_event_id=f"v{i}",
        ),
    )


def _friction_evidence():
    rows = []
    for index in range(3):
        rows.extend(_change(index, NOW - timedelta(days=2) + timedelta(hours=index), passed=False))
    return tuple(rows)


class RuntimeContractTests(unittest.TestCase):
    def test_inventory_has_exactly_one_declared_entry_per_stage(self):
        self.assertEqual(
            {entry.stage for entry in CANONICAL_STAGE_INVENTORY},
            set(RuntimeStage),
        )
        self.assertEqual(len(CANONICAL_STAGE_INVENTORY), len(RuntimeStage))
        learn = next(
            entry for entry in CANONICAL_STAGE_INVENTORY
            if entry.stage is RuntimeStage.LEARN
        )
        self.assertIs(learn.status, StageOwnershipStatus.DEFERRED)
        attention = next(
            entry for entry in CANONICAL_STAGE_INVENTORY
            if entry.stage is RuntimeStage.ATTENTION_RANK
        )
        self.assertIn("terminal_learning", attention.owner)
        self.assertIn("library-only", attention.alternate_path)

    def test_desktop_bridge_imports_the_canonical_orchestrator(self):
        self.assertIs(bridge_run_pipeline, run_pipeline)

    def test_paginated_reader_reports_complete_coverage(self):
        providers = RepoIntelligenceProviders(performance_reads=PagingReads(250))
        auth = QueryAuthorization(project=PROJECT, allowed_kinds=frozenset(EntityKind))
        items, coverage, stage = _read_performance_evidence(providers, auth)
        self.assertEqual(len(items), 250)
        self.assertTrue(coverage.complete)
        self.assertFalse(coverage.truncated)
        self.assertIs(stage.status, StageExecutionStatus.COMPLETED)

    def test_hard_limit_keeps_latest_slice_and_reports_truncation(self):
        total = PERFORMANCE_HARD_LIMIT + 37
        providers = RepoIntelligenceProviders(performance_reads=PagingReads(total))
        auth = QueryAuthorization(project=PROJECT, allowed_kinds=frozenset(EntityKind))
        items, coverage, stage = _read_performance_evidence(providers, auth)
        self.assertEqual(len(items), PERFORMANCE_HARD_LIMIT)
        self.assertEqual(items[0], 37)
        self.assertTrue(coverage.truncated)
        self.assertEqual(coverage.start_offset, 37)
        self.assertIs(stage.status, StageExecutionStatus.DEGRADED)
        self.assertIs(stage.reason_code, StageReasonCode.HARD_LIMIT)

    def test_one_page_reader_cannot_silently_claim_full_coverage(self):
        providers = RepoIntelligenceProviders(performance_reads=OnePageReads(130))
        auth = QueryAuthorization(project=PROJECT, allowed_kinds=frozenset(EntityKind))
        items, coverage, stage = _read_performance_evidence(providers, auth)
        self.assertEqual(len(items), 100)
        self.assertFalse(coverage.complete)
        self.assertTrue(coverage.truncated)
        self.assertIs(stage.status, StageExecutionStatus.DEGRADED)


class RuntimePipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo_root = root / "repo"
        (self.repo_root / "src").mkdir(parents=True)
        (self.repo_root / "src" / "foo.py").write_text("print('hi')\n")
        self.store = RepoIntelligenceStore.open_for_project(root / "data", PROJECT)
        self.authorization = RepoIntelligenceAuthorization(
            project=PROJECT, external_access=False, model_access=False
        )

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def _providers(self, memory):
        providers = RepoIntelligenceProviders(
            performance_reads=EnvelopeReads(_friction_evidence()),
            memory_bridge=memory,
        )
        return RepoIntelligenceProviders(
            performance_reads=providers.performance_reads,
            memory_bridge=providers.memory_bridge,
            budget_meter=AIAccountingBudgetMeter(self.store),
        )

    def test_exact_replay_does_not_duplicate_exposure_or_local_cost(self):
        providers = self._providers(EmptyMemory())
        first = run_pipeline(
            PROJECT, "runtime", self.repo_root, providers,
            self.authorization, self.store, now=NOW, user_pull=True,
        )
        self.assertGreater(first.signals_detected, 0)
        first_exposures = len(self.store.list_exposures(PROJECT))
        first_costs = len(self.store.list_cost_records(PROJECT))
        self.assertGreater(first_exposures, 0)
        self.assertGreater(first_costs, 0)

        second = run_pipeline(
            PROJECT, "runtime", self.repo_root, providers,
            self.authorization, self.store, now=NOW, user_pull=True,
        )
        self.assertEqual(len(self.store.list_exposures(PROJECT)), first_exposures)
        self.assertEqual(len(self.store.list_cost_records(PROJECT)), first_costs)
        self.assertIn("idempotent replay", second.stopped_reason)
        stages = {stage.stage: stage for stage in second.stage_outcomes}
        self.assertIs(
            stages[RuntimeStage.EXPOSE].reason_code,
            StageReasonCode.IDEMPOTENT_REPLAY,
        )
        self.assertIs(
            stages[RuntimeStage.LEARN].reason_code,
            StageReasonCode.DEFERRED,
        )

    def test_optional_providers_disabled_still_returns_all_stage_outcomes(self):
        result = run_pipeline(
            PROJECT, "runtime", self.repo_root, self._providers(EmptyMemory()),
            self.authorization, self.store, now=NOW,
        )
        self.assertEqual(len(result.stage_outcomes), len(RuntimeStage))
        self.assertTrue(result.insights_synthesized)
        stages = {stage.stage: stage for stage in result.stage_outcomes}
        self.assertIs(
            stages[RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY].reason_code,
            StageReasonCode.AUTHORIZATION_DENIED,
        )

    def test_memory_failure_is_explicit_and_blocks_external_escalation(self):
        result = run_pipeline(
            PROJECT, "runtime", self.repo_root, self._providers(BrokenMemory()),
            self.authorization, self.store, now=NOW,
        )
        stages = {stage.stage: stage for stage in result.stage_outcomes}
        memory = stages[RuntimeStage.CHECK_INTERNAL_SUFFICIENCY]
        external = stages[RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY]
        self.assertIs(memory.status, StageExecutionStatus.FAILED)
        self.assertIs(memory.reason_code, StageReasonCode.INTERNAL_ERROR)
        self.assertNotIn("fixture failure", memory.detail)
        self.assertIs(external.status, StageExecutionStatus.SKIPPED)
        self.assertIs(external.reason_code, StageReasonCode.INTERNAL_ERROR)


if __name__ == "__main__":
    unittest.main()
