"""Execution RI-13: fusion helpers reuse Performance's anomaly + personal-learning modules directly."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.contracts import (
    BudgetCeiling,
    InternalAnswerStatus,
    InternalSignal,
    PressureDimension,
    QuestionStatus,
    ResearchQuestion,
    internal_signal_identity,
    research_question_identity,
)
from midnight_performance.repo_intelligence_fusion import classify_unusualness, match_prior_internal_answer

PROJECT = deterministic_identity(EntityKind.PROJECT, "fusion-alpha")
T0 = datetime(2026, 9, 5, tzinfo=timezone.utc)
_EVIDENCE_REF = deterministic_identity(EntityKind.VERIFICATION_RUN, "v1").canonical


def _signal(i, *, window_end, confidence, dims=(PressureDimension.ATTENTION, PressureDimension.RECURRENCE)):
    return InternalSignal(
        identity=internal_signal_identity(PROJECT, "churn", window_end - timedelta(days=1), f"widget-{i}"),
        project=PROJECT, signal_kind="churn", dimensions=tuple(dims),
        window_start=window_end - timedelta(days=1), window_end=window_end,
        claim_kind=ClaimKind.DERIVED, method="test", method_version="1",
        uncertainty="test fixture", summary="widget churn observed",
        confidence=confidence,
    )


class ClassifyUnusualnessTests(unittest.TestCase):
    def test_too_little_history_yields_unmeasured_baseline_never_a_fabricated_score(self):
        history = tuple(_signal(i, window_end=T0 - timedelta(days=i), confidence=0.3) for i in range(1, 4))
        current = _signal(0, window_end=T0, confidence=0.9)
        report = classify_unusualness(history, current, min_baseline=10)
        self.assertEqual(report.findings, ())
        self.assertIn("without a usable baseline", report.uncertainty)

    def test_a_confidence_spike_against_a_stable_baseline_is_flagged_unusual_not_bad(self):
        history = tuple(_signal(i, window_end=T0 - timedelta(days=i), confidence=0.3) for i in range(1, 12))
        current = _signal(0, window_end=T0, confidence=0.95)
        report = classify_unusualness(history, current, min_baseline=10)
        self.assertTrue(report.findings, "a large deviation from a stable baseline must be flagged as unusual")
        self.assertIn("not bad", report.findings[0].uncertainty)

    def test_a_typical_value_against_the_same_baseline_is_not_flagged(self):
        history = tuple(_signal(i, window_end=T0 - timedelta(days=i), confidence=0.3) for i in range(1, 12))
        current = _signal(0, window_end=T0, confidence=0.3)
        report = classify_unusualness(history, current, min_baseline=10)
        self.assertEqual(report.findings, ())


def _answered_question(concept, *, created_at):
    key = f"rework|{concept}"
    return ResearchQuestion(
        identity=research_question_identity(PROJECT, key), project=PROJECT,
        question_text=f"what are reliable patterns to prevent recurring failures in {concept}",
        privacy_minimized=True, why_now="rework signal observed", triggered_by=(_EVIDENCE_REF,),
        what_is_already_known="internal/Memory context already answers the need",
        what_is_unknown="n/a", what_external_evidence_would_change="n/a",
        stop_condition="n/a", budget=BudgetCeiling(max_network_requests=0),
        internal_answer_status=InternalAnswerStatus.SUFFICIENT, dedup_key=key,
        status=QuestionStatus.ANSWERED_INTERNAL, created_at=created_at,
    )


class MatchPriorInternalAnswerTests(unittest.TestCase):
    def test_no_answered_questions_yields_no_match(self):
        self.assertIsNone(match_prior_internal_answer("rework", "widget", PROJECT.canonical, ()))

    def test_same_component_and_kind_matches_the_canonical_history_matcher(self):
        prior = _answered_question("widget", created_at=T0 - timedelta(days=30))
        match = match_prior_internal_answer("rework", "widget", PROJECT.canonical, (prior,))
        self.assertIsNotNone(match)
        self.assertEqual(match.record_id, prior.identity.canonical)

    def test_different_component_does_not_match(self):
        prior = _answered_question("widget", created_at=T0 - timedelta(days=30))
        match = match_prior_internal_answer("rework", "gadget", PROJECT.canonical, (prior,))
        self.assertIsNone(match)

    def test_open_question_is_not_eligible_prior_answer_history(self):
        prior = _answered_question("widget", created_at=T0 - timedelta(days=30))
        open_question = ResearchQuestion(
            identity=research_question_identity(PROJECT, "rework|widget-open"), project=PROJECT,
            question_text="what are established approaches for widget",
            privacy_minimized=True, why_now="rework signal observed", triggered_by=(_EVIDENCE_REF,),
            what_is_already_known="no internal knowledge found; recorded as an honest gap, not reconstructed",
            what_is_unknown="n/a", what_external_evidence_would_change="n/a",
            stop_condition="n/a", budget=BudgetCeiling(max_network_requests=1),
            internal_answer_status=InternalAnswerStatus.ABSENT, dedup_key="rework|widget-open",
            status=QuestionStatus.OPEN, created_at=T0,
        )
        match = match_prior_internal_answer("rework", "widget-open", PROJECT.canonical, (prior, open_question))
        # "widget-open" only matches the still-open question, which is excluded from history.
        self.assertIsNone(match)


if __name__ == "__main__":
    unittest.main()
