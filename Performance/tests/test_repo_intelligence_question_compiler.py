"""Repo Intelligent question compiler: abstraction, privacy, dedup, sufficiency."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import ClaimKind, deterministic_identity, EntityKind
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import (
    BudgetCeiling,
    InternalAnswerStatus,
    InternalSignal,
    LineageReceipt,
    PressureDimension,
    QuestionStatus,
    lineage_receipt_identity,
)
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence.question_compiler import (
    abstract_concept,
    compile_question,
    dedup_key_for,
)
from midnight_performance.repo_intelligence.signals import (
    LearningPressure,
    PressureFactor,
    PressureFactorName,
    ScoredSignal,
)

PROJECT = deterministic_identity(EntityKind.PROJECT, "alpha")
NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
T0 = NOW - timedelta(days=1)
T1 = NOW
BUDGET = BudgetCeiling(max_model_calls=1, max_network_requests=2, max_seconds=60.0)


def auth(**overrides) -> RepoIntelligenceAuthorization:
    fields = dict(project=PROJECT)
    fields.update(overrides)
    return RepoIntelligenceAuthorization(**fields)


def make_pressure(confidence=0.75) -> LearningPressure:
    return LearningPressure(
        factors=(
            PressureFactor(
                name=PressureFactorName.FRICTION,
                value=0.5,
                evidence_ids=(),
                basis="2 failed verifications in window",
            ),
        ),
        score=0.5,
        confidence=confidence,
        claim_kind=ClaimKind.DERIVED,
        uncertainty="score is a prioritization aid, never a quality judgment",
    )


def make_signal(
    signal_kind="verification_failure",
    path="src/payments/token_refresh.py",
    pressure=None,
) -> ScoredSignal:
    pressure = pressure or make_pressure()
    evidence = ("mp:v1:verification_run:00000000-0000-0000-0000-000000000001",)
    identity = deterministic_repo_identity(
        RepoIntelligenceKind.INTERNAL_SIGNAL, f"alpha|{signal_kind}|{path}|1"
    )
    signal = InternalSignal(
        identity=identity,
        project=PROJECT,
        signal_kind=signal_kind,
        dimensions=pressure.covered_dimensions() or (PressureDimension.FRICTION,),
        window_start=T0,
        window_end=T1,
        claim_kind=pressure.claim_kind,
        method="signal-detect",
        method_version="1",
        uncertainty=pressure.uncertainty,
        summary="repeated failed verifications on the token refresh helper",
        performance_refs=evidence,
        evidence_ids=evidence,
        confidence=pressure.confidence,
    )
    receipt_identity = lineage_receipt_identity(
        PROJECT,
        "signal-detect",
        "1",
        T0,
        T1,
        evidence,
        (),
        (),
    )
    receipt = LineageReceipt(
        identity=receipt_identity,
        project=PROJECT,
        derivation_method="signal-detect",
        derivation_version="1",
        window_start=T0,
        window_end=T1,
        claim_kind=ClaimKind.DERIVED,
        privacy_decision="local_only",
        created_at=NOW,
        performance_evidence_ids=evidence,
        confidence=pressure.confidence,
    )
    return ScoredSignal(signal=signal, receipt=receipt, pressure=pressure, paths=(path,))


def compile(scored, *, memory=InternalAnswerStatus.ABSENT, existing=None, **auth_overrides):
    return compile_question(
        scored,
        project=PROJECT,
        repository_key="midnight-repo",
        authorization=auth(**auth_overrides),
        internal_answer_status=memory,
        now=NOW,
        budget=BUDGET,
        existing=existing,
    )


class AbstractionTests(unittest.TestCase):
    def test_abstract_concept_drops_structural_tokens_and_repository_key(self):
        concept = abstract_concept(
            "src/payments/token_refresh.py", repository_key="midnight-repo"
        )
        self.assertEqual(concept, "payments token refresh")

    def test_abstract_concept_never_contains_the_repository_key(self):
        concept = abstract_concept("midnight-repo/auth/flow.py", repository_key="midnight-repo")
        self.assertNotIn("midnight", concept)
        self.assertNotIn("repo", concept.split())

    def test_unabstractable_paths_are_refused(self):
        with self.assertRaises(ValueError):
            abstract_concept("src/_/__init__.py")

    def test_dedup_keys_collapse_equivalent_questions(self):
        self.assertEqual(
            dedup_key_for("payments token refresh", "verification_failure"),
            dedup_key_for("payments token refresh", "verification_failure"),
        )
        self.assertNotEqual(
            dedup_key_for("payments token refresh", "verification_failure"),
            dedup_key_for("payments token refresh", "rework"),
        )


class CompilationTests(unittest.TestCase):
    def test_compiles_privacy_minimized_question_with_all_compiler_fields(self):
        scored = make_signal()
        result = compile(scored)
        self.assertIsNotNone(result.question)
        question = result.question
        self.assertTrue(question.privacy_minimized)
        self.assertNotIn("midnight-repo", question.question_text)
        self.assertNotIn("src/payments/token_refresh.py", question.question_text)
        self.assertIn("token refresh", question.question_text)
        self.assertTrue(question.why_now)
        self.assertTrue(question.triggered_by)
        self.assertIn(scored.signal.identity.canonical, question.triggered_by)
        self.assertTrue(question.what_is_already_known)
        self.assertTrue(question.what_is_unknown)
        self.assertTrue(question.what_external_evidence_would_change)
        self.assertTrue(question.stop_condition)
        self.assertIsNotNone(question.budget.max_model_calls)
        self.assertEqual(question.status, QuestionStatus.OPEN)
        self.assertEqual(
            question.identity,
            deterministic_repo_identity(
                RepoIntelligenceKind.RESEARCH_QUESTION,
                f"{PROJECT.canonical}|{result.dedup_key}",
            ),
        )

    def test_churn_alone_is_never_a_research_question(self):
        scored = make_signal(signal_kind="churn")
        result = compile(scored)
        self.assertIsNone(result.question)
        self.assertIn("not a learning need", result.reason)

    def test_unknown_claim_strength_is_refused(self):
        weak_pressure = LearningPressure(
            factors=(),
            score=None,
            confidence=None,
            claim_kind=ClaimKind.UNKNOWN,
            uncertainty="no evidence",
        )
        scored = make_signal(pressure=weak_pressure)
        result = compile(scored)
        self.assertIsNone(result.question)

    def test_dedup_prevents_repeat_candidates(self):
        scored = make_signal()
        first = compile(scored)
        second = compile(scored, existing={first.dedup_key: QuestionStatus.OPEN})
        self.assertIsNone(second.question)
        self.assertEqual(second.duplicate_of, first.question.identity.canonical)
        self.assertIn("no external call", second.reason)

    def test_superseded_or_cancelled_questions_may_be_recompiled(self):
        scored = make_signal()
        first = compile(scored)
        again = compile(scored, existing={first.dedup_key: QuestionStatus.SUPERSEDED})
        self.assertIsNotNone(again.question)

    def test_memory_sufficient_answer_closes_the_question_without_external_call(self):
        scored = make_signal()
        result = compile(scored, memory=InternalAnswerStatus.SUFFICIENT)
        self.assertIsNotNone(result.question)
        self.assertEqual(result.question.status, QuestionStatus.ANSWERED_INTERNAL)
        self.assertIn("already answers", result.question.what_is_already_known)
        self.assertEqual(result.question.internal_answer_status, InternalAnswerStatus.SUFFICIENT)

    def test_partial_internal_knowledge_stays_open_with_honest_known_text(self):
        scored = make_signal()
        result = compile(scored, memory=InternalAnswerStatus.PARTIAL)
        self.assertEqual(result.question.status, QuestionStatus.OPEN)
        self.assertIn("partial", result.question.what_is_already_known)

    def test_absent_internal_knowledge_is_recorded_as_honest_gap(self):
        scored = make_signal()
        result = compile(scored, memory=InternalAnswerStatus.ABSENT)
        self.assertIn("honest gap", result.question.what_is_already_known)

    def test_private_identifiers_require_explicit_policy(self):
        scored = make_signal()
        denied = compile(scored)
        self.assertIsNotNone(denied.question)
        allowed = compile(scored, allow_private_identifiers=True)
        self.assertIsNotNone(allowed.question)
        self.assertIn("src/payments/token_refresh.py", allowed.question.question_text)

    def test_coupling_questions_name_both_concepts(self):
        pressure = make_pressure()
        scored = make_signal(signal_kind="coupling", path="src/auth/session.py", pressure=pressure)
        two_paths = ScoredSignal(
            signal=scored.signal,
            receipt=scored.receipt,
            pressure=pressure,
            paths=("src/auth/session.py", "src/auth/token_store.py"),
        )
        result = compile(two_paths)
        self.assertIsNotNone(result.question)
        self.assertIn("session", result.question.question_text)
        self.assertIn("token store", result.question.question_text)
        self.assertNotIn("src/", result.question.question_text)

    def test_compilation_never_calls_models_or_network(self):
        scored = make_signal()
        result = compile(scored)
        self.assertIsNotNone(result.question)
        self.assertEqual(result.question.budget.max_network_requests, 2)
        self.assertGreaterEqual(result.question.budget.max_model_calls, 0)


if __name__ == "__main__":
    unittest.main()
