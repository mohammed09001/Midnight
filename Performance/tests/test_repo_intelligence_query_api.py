"""Execution RI-13: the fusion read facade over an already-populated store."""

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import CrossProjectAccessError, RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import (
    AssociationKind,
    BudgetCeiling,
    Exposure,
    ExposureChannel,
    ExposureOutcome,
    InternalAnswerStatus,
    InternalSignal,
    JobStatus,
    JobTrigger,
    LearningOutcome,
    LineageReceipt,
    PressureDimension,
    ProjectIntelligenceJob,
    QuestionStatus,
    ResearchQuestion,
    internal_signal_identity,
    lineage_receipt_identity,
    new_event_identity,
    project_intelligence_job_identity,
    research_question_identity,
)
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence_query_api import RepoIntelligenceQueryAPI
from midnight_performance.repo_intelligence_store import RepoIntelligenceStore

PROJECT = deterministic_identity(EntityKind.PROJECT, "query-alpha")
OTHER_PROJECT = deterministic_identity(EntityKind.PROJECT, "query-beta")
T0 = datetime(2026, 9, 5, tzinfo=timezone.utc)
EVIDENCE_REF = deterministic_identity(EntityKind.VERIFICATION_RUN, "v1").canonical
WIDGET_ENTITY_REF = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_ENTITY_REF, "widget").canonical


def _signal(confidence=0.8):
    return InternalSignal(
        identity=internal_signal_identity(PROJECT, "rework", T0 - timedelta(days=1), "widget"),
        project=PROJECT, signal_kind="rework", dimensions=(PressureDimension.FRICTION,),
        window_start=T0 - timedelta(days=1), window_end=T0, claim_kind=ClaimKind.DERIVED,
        method="test", method_version="1", uncertainty="test fixture", summary="widget rework observed",
        performance_refs=(EVIDENCE_REF,), evidence_ids=(EVIDENCE_REF,), entity_refs=(WIDGET_ENTITY_REF,),
        confidence=confidence,
    )


def _receipt():
    return LineageReceipt(
        identity=lineage_receipt_identity(PROJECT, "test", "1", T0 - timedelta(days=1), T0, (EVIDENCE_REF,), (), ()),
        project=PROJECT, derivation_method="test", derivation_version="1",
        window_start=T0 - timedelta(days=1), window_end=T0, claim_kind=ClaimKind.DERIVED,
        privacy_decision="local_only", created_at=T0, performance_evidence_ids=(EVIDENCE_REF,),
    )


def _question(status=QuestionStatus.OPEN):
    key = "rework|widget"
    return ResearchQuestion(
        identity=research_question_identity(PROJECT, key), project=PROJECT,
        question_text="what are reliable patterns to prevent recurring failures in widget",
        privacy_minimized=True, why_now="rework signal observed in the window ending " + T0.isoformat(),
        triggered_by=(_signal().identity.canonical, EVIDENCE_REF),
        what_is_already_known="no internal knowledge found; recorded as an honest gap, not reconstructed",
        what_is_unknown="n/a", what_external_evidence_would_change="n/a", stop_condition="n/a",
        budget=BudgetCeiling(max_network_requests=1), internal_answer_status=InternalAnswerStatus.ABSENT,
        dedup_key=key, status=status, created_at=T0,
    )


def _job():
    return ProjectIntelligenceJob(
        identity=project_intelligence_job_identity(PROJECT, "continuous_learning", "k1"), project=PROJECT,
        job_kind="continuous_learning", idempotency_key="k1", trigger=JobTrigger.MAINTENANCE,
        status=JobStatus.COMPLETED, stop_condition="stop", budget=BudgetCeiling(max_network_requests=1),
        derivation_method="test", derivation_version="1", requested_at=T0, started_at=T0, completed_at=T0,
    )


class RepoIntelligenceQueryAPITests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RepoIntelligenceStore(Path(self._tmp.name) / "state.sqlite3")
        self.api = RepoIntelligenceQueryAPI(self.store, PROJECT)
        self.authorization = RepoIntelligenceAuthorization(project=PROJECT)

        self.signal = _signal()
        self.receipt = _receipt()
        self.question = _question()
        self.job = _job()
        self.store.upsert_signal(self.signal)
        self.store.upsert_lineage_receipt(self.receipt)
        self.store.link_signal_receipt(PROJECT, self.signal.identity, self.receipt.identity)
        self.store.upsert_research_question(self.question)
        self.store.upsert_job(self.job)
        self.store.record_question_job(PROJECT, self.question.dedup_key, self.job.identity)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_cross_project_read_fails_closed(self):
        wrong = RepoIntelligenceAuthorization(project=OTHER_PROJECT)
        with self.assertRaises(CrossProjectAccessError):
            self.api.active_learning_pressures(wrong)

    def test_active_learning_pressures_filters_by_confidence(self):
        self.assertEqual(len(self.api.active_learning_pressures(self.authorization)), 1)
        self.assertEqual(self.api.active_learning_pressures(self.authorization, min_confidence=0.9), ())

    def test_why_this_topic_now_composes_signal_and_question(self):
        topic = self.api.why_this_topic_now(self.authorization, self.signal.identity.canonical)
        self.assertIsNotNone(topic)
        self.assertEqual(topic.signal_summary, self.signal.summary)
        self.assertEqual(topic.question_why_now, self.question.why_now)
        self.assertEqual(topic.question_status, QuestionStatus.OPEN.value)
        self.assertIsNone(topic.unusual, "no same-kind history yet; unusual must not be fabricated")
        self.assertIsNone(topic.prior_internal_answer_reference)

    def test_why_this_topic_now_flags_unusual_signal_against_stable_history(self):
        for i in range(1, 12):
            historical = InternalSignal(
                identity=internal_signal_identity(PROJECT, "rework", T0 - timedelta(days=i + 1), f"widget-{i}"),
                project=PROJECT, signal_kind="rework", dimensions=(PressureDimension.FRICTION,),
                window_start=T0 - timedelta(days=i + 1), window_end=T0 - timedelta(days=i),
                claim_kind=ClaimKind.DERIVED, method="test", method_version="1",
                uncertainty="test fixture", summary="widget rework observed", confidence=0.2,
                entity_refs=(WIDGET_ENTITY_REF,),
            )
            self.store.upsert_signal(historical)

        topic = self.api.why_this_topic_now(self.authorization, self.signal.identity.canonical)
        self.assertTrue(topic.unusual, "a confidence spike against a stable rework baseline must be flagged unusual")

    def test_why_this_topic_now_does_not_mix_unrelated_entities_into_the_baseline(self):
        """Same signal_kind, a different component: must never be treated as this signal's own history."""
        other_entity_ref = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_ENTITY_REF, "gadget").canonical
        for i in range(1, 12):
            unrelated = InternalSignal(
                identity=internal_signal_identity(PROJECT, "rework", T0 - timedelta(days=i + 1), f"gadget-{i}"),
                project=PROJECT, signal_kind="rework", dimensions=(PressureDimension.FRICTION,),
                window_start=T0 - timedelta(days=i + 1), window_end=T0 - timedelta(days=i),
                claim_kind=ClaimKind.DERIVED, method="test", method_version="1",
                uncertainty="test fixture", summary="gadget rework observed", confidence=0.2,
                entity_refs=(other_entity_ref,),
            )
            self.store.upsert_signal(unrelated)

        topic = self.api.why_this_topic_now(self.authorization, self.signal.identity.canonical)
        self.assertIsNone(
            topic.unusual,
            "an unrelated component's history must never be borrowed as this signal's own baseline",
        )

    def test_why_this_topic_now_surfaces_a_matching_prior_internal_answer(self):
        # The recurring-component-with-an-old-Memory-answer scenario: this exact
        # need (same dedup_key/identity) was already closed internally by an
        # earlier pass. Re-upserting with status flipped simulates that -- a
        # dedup_key always maps to the one recurring question, never a second
        # coexisting record for the same concept+kind (see ``dedup_key_for``).
        answered = replace(
            self.question,
            status=QuestionStatus.ANSWERED_INTERNAL,
            internal_answer_status=InternalAnswerStatus.SUFFICIENT,
            what_is_already_known="internal/Memory context already answers the need",
            created_at=T0 - timedelta(days=60),
        )
        self.store.upsert_research_question(answered)

        topic = self.api.why_this_topic_now(self.authorization, self.signal.identity.canonical)
        self.assertEqual(topic.prior_internal_answer_reference, answered.identity.canonical)
        self.assertEqual(topic.question_status, QuestionStatus.ANSWERED_INTERNAL.value)

    def test_why_this_topic_now_unknown_signal_is_none(self):
        self.assertIsNone(self.api.why_this_topic_now(self.authorization, "ri:v1:internal_signal:00000000-0000-0000-0000-000000000000"))

    def test_evidence_behind_pressure_returns_the_linked_receipt(self):
        self.assertEqual(
            self.api.evidence_behind_pressure(self.authorization, self.signal.identity.canonical),
            self.receipt,
        )

    def test_evidence_behind_pressure_unlinked_signal_is_none(self):
        self.assertIsNone(self.api.evidence_behind_pressure(self.authorization, "ri:v1:internal_signal:00000000-0000-0000-0000-000000000000"))

    def test_internal_knowledge_sufficiency_reads_last_recorded_status(self):
        self.assertIsNone(self.api.internal_knowledge_sufficiency(self.authorization))
        self.store.record_pipeline_run(PROJECT, now=T0, window_end=T0, memory_status=InternalAnswerStatus.PARTIAL)
        self.assertEqual(self.api.internal_knowledge_sufficiency(self.authorization), InternalAnswerStatus.PARTIAL)

    def test_research_jobs_for_pressure_resolves_through_the_question(self):
        jobs = self.api.research_jobs_for_pressure(self.authorization, self.signal.identity.canonical)
        self.assertEqual(jobs, (self.job,))

    def test_research_jobs_for_pressure_unrelated_signal_is_empty(self):
        self.assertEqual(
            self.api.research_jobs_for_pressure(self.authorization, "ri:v1:internal_signal:00000000-0000-0000-0000-000000000000"),
            (),
        )

    def test_exposure_outcomes_pairs_exposures_with_later_associations(self):
        exposure = Exposure(
            identity=new_event_identity(RepoIntelligenceKind.EXPOSURE), project=PROJECT,
            insight=deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "insight-stand-in"),
            channel=ExposureChannel.USER_PULL,
            outcome=ExposureOutcome.OPENED, surface="terminal", occurred_at=T0,
        )
        self.store.append_exposure(exposure)
        outcome = LearningOutcome(
            identity=new_event_identity(RepoIntelligenceKind.LEARNING_OUTCOME), project=PROJECT,
            exposure=exposure.identity, insight=exposure.insight, association=AssociationKind.INCONCLUSIVE,
            claim_kind=ClaimKind.UNKNOWN, method="test", method_version="1",
            uncertainty="association observed after exposure; not evidence of causality",
            window_start=T0, window_end=T0 + timedelta(days=7), created_at=T0,
        )
        self.store.append_learning_outcome(outcome)

        pairs = self.api.exposure_outcomes(self.authorization)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].exposure, exposure)
        self.assertEqual(pairs[0].outcomes, (outcome,))


def _analogy(suffix="a1", *, confidence_similar=True):
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
    external_role = "worker" if confidence_similar else "static-site-generator"
    external_profile = RepositoryProfile(architectural_role=external_role, language="go", evidence_ids=(external.identity.canonical,))
    return build_analogy_record(
        PROJECT, external, internal_ref, internal_profile, external_profile,
        why_it_matters_now="test", meaningful_differences=("language",), freshness=Freshness(captured_at=T0), now=T0,
    )


class AttentionAndAnalogyQueryAPITests(unittest.TestCase):
    """Execution RI-14: active analogies, the independent attention ledger, and the release metric."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RepoIntelligenceStore(Path(self._tmp.name) / "state.sqlite3")
        self.api = RepoIntelligenceQueryAPI(self.store, PROJECT)
        self.authorization = RepoIntelligenceAuthorization(project=PROJECT)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_active_analogies_filters_by_confidence_and_staleness(self):
        from midnight_performance.repo_intelligence.sources import Freshness

        high = _analogy("high", confidence_similar=True)
        low = _analogy("low", confidence_similar=False)
        self.store.upsert_analogy_record(high)
        self.store.upsert_analogy_record(low)
        self.assertEqual(self.api.active_analogies(self.authorization, now=T0), (high, low))
        self.assertEqual(self.api.active_analogies(self.authorization, now=T0, min_confidence=0.5), (high,))

    def test_attention_budget_status_reads_only_durable_exposure_history(self):
        from midnight_performance.repo_intelligence.attention import AttentionBudgetLimits

        limits = AttentionBudgetLimits(window=timedelta(hours=1), max_interruptions=1, max_digests=1)
        spend, allowed = self.api.attention_budget_status(self.authorization, now=T0, limits=limits)
        self.assertEqual((spend.interruptions, spend.digests), (0, 0))
        self.assertTrue(allowed)

        insight = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "attn-insight")
        push = Exposure(
            identity=new_event_identity(RepoIntelligenceKind.EXPOSURE), project=PROJECT, insight=insight,
            channel=ExposureChannel.PROACTIVE_PUSH, outcome=ExposureOutcome.OFFERED, surface="terminal",
            occurred_at=T0, relevance_justification="hiding this would leave a pattern unexplained",
        )
        self.store.append_exposure(push)
        spend, allowed = self.api.attention_budget_status(self.authorization, now=T0, limits=limits)
        self.assertEqual(spend.interruptions, 1)
        self.assertFalse(allowed)

    def test_release_metric_composes_outcomes_exposures_and_costs(self):
        metric = self.api.release_metric(self.authorization)
        self.assertIsNone(metric.value)  # nothing spent yet; never a fabricated ratio

        insight = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "metric-insight")
        push = Exposure(
            identity=new_event_identity(RepoIntelligenceKind.EXPOSURE), project=PROJECT, insight=insight,
            channel=ExposureChannel.PROACTIVE_PUSH, outcome=ExposureOutcome.OFFERED, surface="terminal",
            occurred_at=T0, relevance_justification="hiding this would leave a pattern unexplained",
        )
        self.store.append_exposure(push)
        outcome = LearningOutcome(
            identity=new_event_identity(RepoIntelligenceKind.LEARNING_OUTCOME), project=PROJECT,
            exposure=push.identity, insight=insight, association=AssociationKind.POSITIVE_ASSOCIATION,
            claim_kind=ClaimKind.STATISTICAL, method="test", method_version="1",
            uncertainty="associative only", window_start=T0, window_end=T0 + timedelta(days=1), created_at=T0,
        )
        self.store.append_learning_outcome(outcome)
        metric = self.api.release_metric(self.authorization)
        self.assertEqual(metric.value, 1.0)


if __name__ == "__main__":
    unittest.main()
