"""Execution RI-13: job persistence and the signal<->receipt / question<->job link tables.

These are pure store-layer additions -- no ``repo_intelligence/contracts.py``
schema changed, so this file only exercises the new
``RepoIntelligenceStore`` methods directly.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.contracts import (
    BudgetCeiling,
    InternalAnswerStatus,
    JobStatus,
    JobTrigger,
    ProjectIntelligenceJob,
    project_intelligence_job_identity,
)
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence_store import RepoIntelligenceStore

PROJECT = deterministic_identity(EntityKind.PROJECT, "store-ri13")
T0 = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _job(idempotency_key="k1"):
    return ProjectIntelligenceJob(
        identity=project_intelligence_job_identity(PROJECT, "continuous_learning", idempotency_key),
        project=PROJECT, job_kind="continuous_learning", idempotency_key=idempotency_key,
        trigger=JobTrigger.MAINTENANCE, status=JobStatus.COMPLETED, stop_condition="stop",
        budget=BudgetCeiling(max_network_requests=1), derivation_method="test", derivation_version="1",
        requested_at=T0, started_at=T0, completed_at=T0,
    )


class RepoIntelligenceStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RepoIntelligenceStore(Path(self._tmp.name) / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_job_round_trips_and_lists(self):
        job = _job()
        self.store.upsert_job(job)
        self.assertEqual(self.store.get_job(PROJECT, job.identity.canonical), job)
        self.assertEqual(self.store.list_jobs(PROJECT), (job,))

    def test_unknown_job_returns_none(self):
        self.assertIsNone(self.store.get_job(PROJECT, "ri:v1:project_intelligence_job:missing"))

    def test_signal_receipt_link_round_trips(self):
        signal_id = deterministic_repo_identity(RepoIntelligenceKind.INTERNAL_SIGNAL, "s1")
        receipt_id = deterministic_repo_identity(RepoIntelligenceKind.LINEAGE_RECEIPT, "r1")
        self.assertIsNone(self.store.receipt_identity_for_signal(PROJECT, signal_id.canonical))
        self.store.link_signal_receipt(PROJECT, signal_id, receipt_id)
        self.assertEqual(self.store.receipt_identity_for_signal(PROJECT, signal_id.canonical), receipt_id.canonical)

    def test_question_job_link_accumulates_across_reopened_questions(self):
        job_a = _job("a")
        job_b = _job("b")
        self.store.upsert_job(job_a)
        self.store.upsert_job(job_b)
        self.store.record_question_job(PROJECT, "rework|widget", job_a.identity)
        self.store.record_question_job(PROJECT, "rework|widget", job_b.identity)
        self.assertEqual(
            set(self.store.job_identities_for_question(PROJECT, "rework|widget")),
            {job_a.identity.canonical, job_b.identity.canonical},
        )

    def test_memory_status_recorded_with_pipeline_run_and_survives_no_run(self):
        other = deterministic_identity(EntityKind.PROJECT, "store-ri13-other")
        self.assertIsNone(self.store.last_memory_status(other))
        self.store.record_pipeline_run(PROJECT, now=T0, window_end=T0, memory_status=InternalAnswerStatus.PARTIAL)
        self.assertEqual(self.store.last_memory_status(PROJECT), InternalAnswerStatus.PARTIAL)

    def test_discard_rebuildable_state_clears_links_but_keeps_jobs(self):
        job = _job()
        self.store.upsert_job(job)
        signal_id = deterministic_repo_identity(RepoIntelligenceKind.INTERNAL_SIGNAL, "s1")
        receipt_id = deterministic_repo_identity(RepoIntelligenceKind.LINEAGE_RECEIPT, "r1")
        self.store.link_signal_receipt(PROJECT, signal_id, receipt_id)
        self.store.record_question_job(PROJECT, "rework|widget", job.identity)

        self.store.discard_rebuildable_state(PROJECT)

        self.assertIsNone(self.store.receipt_identity_for_signal(PROJECT, signal_id.canonical))
        self.assertEqual(self.store.job_identities_for_question(PROJECT, "rework|widget"), ())
        # Jobs record real authorized spend history -- like cost_records, they are not purged.
        self.assertEqual(self.store.list_jobs(PROJECT), (job,))


def _analogy_record(suffix="a1"):
    from midnight_performance.repo_intelligence.analogy import RepositoryProfile, build_analogy_record
    from midnight_performance.repo_intelligence.contracts import (
        ExternalSourceRef,
        ProjectEntityRef,
        ProjectEntityRefKind,
        external_source_ref_identity,
        project_entity_ref_identity,
    )
    from midnight_performance.repo_intelligence.sources import Freshness, SourceClass

    internal_ref = ProjectEntityRef(
        identity=project_entity_ref_identity("repo", ProjectEntityRefKind.MODULE, f"src/{suffix}.py", None, "resolver", "1"),
        project=PROJECT, ref_kind=ProjectEntityRefKind.MODULE, repository_key="repo",
        resolver_tool="resolver", resolver_version="1", first_seen_at=T0, last_seen_at=T0, path=f"src/{suffix}.py",
    )
    external = ExternalSourceRef(
        identity=external_source_ref_identity("github", f"org/{suffix}", "a" * 64),
        project=PROJECT, source_class=SourceClass.GITHUB_REPOSITORY, provider="github",
        locator=f"org/{suffix}", title=suffix, content_digest="a" * 64, captured_at=T0,
        retrieval_method="fetch", retrieval_version="1",
    )
    internal_profile = RepositoryProfile(architectural_role="worker", language="python", evidence_ids=(internal_ref.identity.canonical,))
    external_profile = RepositoryProfile(architectural_role="worker", language="go", evidence_ids=(external.identity.canonical,))
    return build_analogy_record(
        PROJECT, external, internal_ref, internal_profile, external_profile,
        why_it_matters_now="test", meaningful_differences=("language",), freshness=Freshness(captured_at=T0), now=T0,
    )


class AnalogyRecordStoreTests(unittest.TestCase):
    """Execution RI-14: analogy record persistence, entity-scoped lookup, and rebuildable-cache discard."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RepoIntelligenceStore(Path(self._tmp.name) / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_round_trips_and_lists(self):
        record = _analogy_record()
        self.store.upsert_analogy_record(record)
        self.assertEqual(self.store.list_analogy_records(PROJECT), (record,))

    def test_scoped_lookup_by_internal_entity(self):
        record = _analogy_record("scoped")
        self.store.upsert_analogy_record(record)
        self.assertEqual(
            self.store.analogies_for_entity(PROJECT, record.internal_entity_ref.canonical), (record,)
        )
        self.assertEqual(self.store.analogies_for_entity(PROJECT, "ri:v1:project_entity_ref:missing"), ())

    def test_discard_rebuildable_state_clears_analogies(self):
        record = _analogy_record("discard")
        self.store.upsert_analogy_record(record)
        self.store.discard_rebuildable_state(PROJECT)
        self.assertEqual(self.store.list_analogy_records(PROJECT), ())


if __name__ == "__main__":
    unittest.main()
