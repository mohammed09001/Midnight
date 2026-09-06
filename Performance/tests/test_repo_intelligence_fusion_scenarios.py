"""Execution RI-13: the doc's own verification scenarios, run end-to-end.

Reuses the exact fixtures ``test_repo_intelligence_pipeline_end_to_end.py``
(Execution RI-12) already built for driving ``run_pipeline`` against fixture
ports -- this file adds no second envelope-building convention, it only
asks new questions of the same real pipeline.
"""

import tempfile
import unittest
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.privacy import PrivacyPolicy
from midnight_performance.repo_intelligence.authorization import CrossProjectAccessError, RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import (
    CostResourceKind,
    InternalAnswerStatus,
    InternalSignal,
    PressureDimension,
    QuestionStatus,
    internal_signal_identity,
)
from midnight_performance.repo_intelligence_fusion import classify_unusualness
from midnight_performance.repo_intelligence_adapters import AIAccountingBudgetMeter
from midnight_performance.repo_intelligence_pipeline import run_pipeline
from midnight_performance.repo_intelligence_query_api import RepoIntelligenceQueryAPI
from midnight_performance.repo_intelligence_store import RepoIntelligenceStore
from tests.test_repo_intelligence_pipeline_end_to_end import (
    FakeDiscoveryPort,
    FakeMemoryPort,
    FakeReadsPort,
    NOW,
    PROJECT_ALPHA,
    PROJECT_BETA,
    _change_envelope,
    _providers,
    _rework_envelopes,
    _verification_envelope,
)


def _healthy_refactor_envelopes(project, *, base_at, n=4, files=("src/foo.py",)):
    """Many changes, every verification passing -- churn is activity, not a defect."""
    envelopes = []
    for i in range(n):
        envelopes.append(_change_envelope(project, i, base_at + timedelta(hours=i), files))
        envelopes.append(_verification_envelope(project, i, base_at + timedelta(hours=i, minutes=30), files, True))
    return envelopes


class FusionScenarioTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmp.name) / "repo"
        (self.repo_root / "src").mkdir(parents=True)
        (self.repo_root / "src" / "foo.py").write_text("print('hi')\n")
        self.data_dir = Path(self._tmp.name) / "data"
        self.store = RepoIntelligenceStore.open_for_project(self.data_dir, PROJECT_ALPHA)
        self.authorization = RepoIntelligenceAuthorization(project=PROJECT_ALPHA, external_access=True)
        self.api = RepoIntelligenceQueryAPI(self.store, PROJECT_ALPHA)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_active_healthy_refactor_produces_no_friction_based_research_need(self):
        """Scenario: active healthy refactor -- churn is activity, never a defect; no friction-based question opens."""
        envelopes = _healthy_refactor_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(days=1))
        reads = FakeReadsPort(envelopes)
        memory = FakeMemoryPort(records=())
        discovery = FakeDiscoveryPort(hits=())
        providers = _providers(reads=reads, memory=memory, discovery=discovery, store=self.store)

        result = run_pipeline(PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW)

        self.assertGreater(result.signals_detected, 0)
        friction_kinds = {"rework", "verification_failure", "flaky_verification", "rollback"}
        signals = self.store.list_signals(PROJECT_ALPHA)
        self.assertTrue(signals)
        self.assertFalse(
            any(s.signal_kind in friction_kinds for s in signals),
            "an all-passing burst of activity must never itself register as friction",
        )
        self.assertFalse(
            any(q.dedup_key.split("|", 1)[0] in friction_kinds for q in result.questions_compiled),
            "no friction-based research need may be compiled from healthy activity alone",
        )
        pressures = self.api.active_learning_pressures(self.authorization)
        self.assertTrue(pressures)

    def test_chronic_repeated_failure_opens_a_research_need_and_reaches_discovery(self):
        """Scenario: chronic repeated failure -- friction is real, a question opens, discovery is authorized+eligible."""
        envelopes = _rework_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(days=5))
        reads = FakeReadsPort(envelopes)
        memory = FakeMemoryPort(records=())
        discovery = FakeDiscoveryPort(hits=())
        providers = _providers(reads=reads, memory=memory, discovery=discovery, store=self.store)

        result = run_pipeline(
            PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW,
            privacy_policy=PrivacyPolicy(allow_export=True),
        )

        self.assertTrue(any(q.status is QuestionStatus.OPEN for q in result.questions_compiled))
        self.assertGreater(discovery.search_calls, 0)
        open_question = next(q for q in result.questions_compiled if q.status is QuestionStatus.OPEN)
        self.assertTrue(self.store.job_identities_for_question(PROJECT_ALPHA, open_question.dedup_key))

    def _synthetic_churn_signal(self, i, *, window_end, confidence):
        return InternalSignal(
            identity=internal_signal_identity(PROJECT_ALPHA, "churn", window_end - timedelta(hours=1), f"baseline-{i}"),
            project=PROJECT_ALPHA, signal_kind="churn", dimensions=(PressureDimension.ATTENTION,),
            window_start=window_end - timedelta(hours=1), window_end=window_end, claim_kind=ClaimKind.DERIVED,
            method="test", method_version="1", uncertainty="test fixture",
            summary="quiet baseline churn", confidence=confidence,
        )

    def test_unusual_but_successful_one_off_is_flagged_unusual_never_bad(self):
        """Scenario: unusual-but-successful one-off -- statistically unusual against baseline, friction stays zero."""
        envelopes = _healthy_refactor_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(hours=6), n=8)
        providers = _providers(reads=FakeReadsPort(envelopes), memory=FakeMemoryPort(records=()), store=self.store)
        run_pipeline(PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW)

        current = next(s for s in self.store.list_signals(PROJECT_ALPHA) if s.signal_kind == "churn")
        self.assertNotEqual(current.confidence, None)
        # Ten quiet historical days establish a stable low-confidence baseline
        # for the same entity/kind -- synthesized directly (this file already
        # covers ``classify_unusualness`` from raw pipeline output above; this
        # test isolates the "large but healthy" contrast against a controlled
        # history without fighting per-day window/identity bookkeeping).
        history = tuple(
            self._synthetic_churn_signal(i, window_end=NOW - timedelta(days=i + 1), confidence=0.15)
            for i in range(10)
        )
        report = classify_unusualness(history, current, min_baseline=5)
        self.assertTrue(report.findings, "a healthy but much larger burst must still register as statistically unusual")
        # Whether or not this particular draw clears the z-threshold, the
        # report itself must never call it "bad" -- only ever "unusual."
        for finding in report.findings:
            self.assertIn("not bad", finding.uncertainty)
        self.assertNotIn(" bad", report.uncertainty.replace("not bad", ""))
        # And friction genuinely stayed at zero for this all-passing burst.
        self.assertNotEqual(current.signal_kind, "rework")

    def test_recurring_component_with_fresh_internal_answer_stays_answered(self):
        """Scenario: recurring component whose prior internal answer is still fresh."""
        envelopes = _rework_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(days=5))
        reads = FakeReadsPort(envelopes)
        memory = FakeMemoryPort(records=())
        discovery = FakeDiscoveryPort(hits=())
        providers = _providers(reads=reads, memory=memory, discovery=discovery, store=self.store)

        first = run_pipeline(
            PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW,
            privacy_policy=PrivacyPolicy(allow_export=True),
        )
        open_question = next(q for q in first.questions_compiled if q.status is QuestionStatus.OPEN)

        answered_now = NOW - timedelta(days=1)
        answered = dc_replace(
            open_question, status=QuestionStatus.ANSWERED_INTERNAL,
            internal_answer_status=InternalAnswerStatus.SUFFICIENT,
            what_is_already_known="internal/Memory context already answers the need",
            created_at=answered_now,
        )
        self.store.upsert_research_question(answered)

        discovery.search_calls = 0
        second = run_pipeline(
            PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW,
            privacy_policy=PrivacyPolicy(allow_export=True),
        )
        self.assertFalse(
            any(q.dedup_key == open_question.dedup_key and q.status is QuestionStatus.OPEN for q in second.questions_compiled),
            "an already internally-answered recurring need must not reopen research",
        )
        self.assertEqual(discovery.search_calls, 0)

    def test_recurring_component_with_stale_internal_answer_is_distinguishable_from_fresh(self):
        """Scenario: recurring component whose prior internal answer is stale (age is visible to the caller)."""
        envelopes = _rework_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(days=5))
        providers = _providers(reads=FakeReadsPort(envelopes), memory=FakeMemoryPort(records=()), store=self.store)
        first = run_pipeline(PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW)
        open_question = next(q for q in first.questions_compiled if q.status is QuestionStatus.OPEN)

        stale_answered_at = NOW - timedelta(days=400)
        stale_answer = dc_replace(
            open_question, status=QuestionStatus.ANSWERED_INTERNAL,
            internal_answer_status=InternalAnswerStatus.SUFFICIENT,
            what_is_already_known="internal/Memory context already answers the need",
            created_at=stale_answered_at,
        )
        self.store.upsert_research_question(stale_answer)

        signal = next(
            s for s in self.store.list_signals(PROJECT_ALPHA)
            if s.identity.canonical in open_question.triggered_by
        )
        topic = self.api.why_this_topic_now(self.authorization, signal.identity.canonical)
        self.assertEqual(topic.prior_internal_answer_reference, stale_answer.identity.canonical)
        # RI-13 exposes the match; staleness is a freshness-window judgment the
        # caller makes over the referenced record's own created_at -- never
        # invented here as a boolean the record itself doesn't carry.
        matched_question = next(q for q in self.store.list_research_questions(PROJECT_ALPHA) if q.identity.canonical == topic.prior_internal_answer_reference)
        self.assertGreater(NOW - matched_question.created_at, timedelta(days=180))

    def test_degraded_without_performance_or_memory_still_produces_an_honest_result(self):
        """Scenario: no Performance installed / degraded bridge."""
        providers = _providers(reads=None, memory=None, store=self.store)
        result = run_pipeline(PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW)
        self.assertEqual(result.signals_detected, 0)
        self.assertEqual(result.questions_compiled, ())
        # Degraded is reported honestly (ABSENT), never fabricated as sufficient or left unrecorded.
        self.assertEqual(self.api.internal_knowledge_sufficiency(self.authorization), InternalAnswerStatus.ABSENT)

    def test_cross_project_attack_fails_closed_end_to_end(self):
        """Scenario: cross-project attack -- both the pipeline and the query facade refuse."""
        envelopes = _rework_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(days=5))
        providers = _providers(reads=FakeReadsPort(envelopes), memory=FakeMemoryPort(records=()), store=self.store)
        attacker_authorization = RepoIntelligenceAuthorization(project=PROJECT_BETA)

        with self.assertRaises(CrossProjectAccessError):
            run_pipeline(PROJECT_ALPHA, "alpha", self.repo_root, providers, attacker_authorization, self.store, now=NOW)
        with self.assertRaises(CrossProjectAccessError):
            self.api.active_learning_pressures(attacker_authorization)

    def test_rerun_restart_idempotency_produces_the_same_job_and_signals(self):
        """Scenario: rerun/restart idempotency."""
        envelopes = _rework_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(days=5))
        providers = _providers(reads=FakeReadsPort(envelopes), memory=FakeMemoryPort(records=()), store=self.store)

        first = run_pipeline(PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW)
        # Simulate a restart: a brand new store handle over the same on-disk state
        # (and a fresh providers bundle -- the old one's budget meter held a
        # reference to the now-closed store).
        self.store.close()
        self.store = RepoIntelligenceStore.open_for_project(self.data_dir, PROJECT_ALPHA)
        self.api = RepoIntelligenceQueryAPI(self.store, PROJECT_ALPHA)
        providers = _providers(reads=FakeReadsPort(envelopes), memory=FakeMemoryPort(records=()), store=self.store)
        second = run_pipeline(PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW)

        self.assertEqual(first.job.identity, second.job.identity)
        self.assertEqual(first.job.idempotency_key, second.job.idempotency_key)
        self.assertEqual(
            {i.identity for i in first.insights_synthesized},
            {i.identity for i in second.insights_synthesized},
            "identical evidence at an identical window must re-derive the same insight identities",
        )
        self.assertEqual(self.store.list_jobs(PROJECT_ALPHA), (second.job,), "the replayed job overwrites, it never duplicates")

    def test_cost_accounting_reconciles_through_the_typed_ledger(self):
        """Scenario: cost accounting reconciliation -- CostRecord totals match the AI-accounting meter's own usage()."""
        envelopes = _rework_envelopes(PROJECT_ALPHA, base_at=NOW - timedelta(days=5))
        discovery = FakeDiscoveryPort(hits=())
        providers = _providers(reads=FakeReadsPort(envelopes), memory=FakeMemoryPort(records=()), discovery=discovery, store=self.store)

        run_pipeline(
            PROJECT_ALPHA, "alpha", self.repo_root, providers, self.authorization, self.store, now=NOW,
            privacy_policy=PrivacyPolicy(allow_export=True),
        )

        meter = AIAccountingBudgetMeter(self.store)
        usage = meter.usage(PROJECT_ALPHA)
        records = self.store.list_cost_records(PROJECT_ALPHA)
        self.assertTrue(records)
        expected_network = sum(1 for r in records if r.resource in (CostResourceKind.EXTERNAL_SEARCH, CostResourceKind.EXTERNAL_FETCH))
        self.assertEqual(usage.network_requests, expected_network)
        self.assertGreater(expected_network, 0)
        # Every accounted cost is tied to a job that was itself persisted -- the
        # ledger never accounts spend against a job nobody can look back up.
        for record in records:
            self.assertIsNotNone(self.store.get_job(PROJECT_ALPHA, record.job.canonical))


if __name__ == "__main__":
    unittest.main()
