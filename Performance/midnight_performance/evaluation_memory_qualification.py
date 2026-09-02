"""Qualification gates for evaluator ensembles and the Memory integration."""
from __future__ import annotations
from dataclasses import dataclass
from statistics import pvariance

from . import memory as _memory_module
from .ai_accounting import AIAnalysisAttempt, summarize_ai_attempts
from .evaluation import EvaluationResult, EvaluatorKind
from .memory_bridge import LessonDeliveryResult, propose_lesson_or_degrade
from .review import AgreementReport, ReviewLabel, analyze_agreement


@dataclass(frozen=True, slots=True)
class EvaluationQualification:
    agreement: AgreementReport; variance: float | None; reproducible: bool; false_positives: int; false_negatives: int
    total_cost: float | None; qualified: bool; failures: tuple[str, ...]
    uncertainty: str = "evaluators are evidence views; no LLM judge or ensemble result is product truth"


def qualify_evaluators(subject_id: str, evaluations: tuple[EvaluationResult, ...], labels: tuple[ReviewLabel, ...], watch_expected: bool | None, attempts: tuple[AIAnalysisAttempt, ...], *, reproducible: bool) -> EvaluationQualification:
    agreement = analyze_agreement(subject_id, evaluations, labels)
    scores = [item.score for item in evaluations if item.subject_id == subject_id and item.score is not None]
    llm_only = bool(evaluations) and all(item.kind is EvaluatorKind.MODEL_JUDGE for item in evaluations if item.subject_id == subject_id)
    predicted = sum(scores) / len(scores) >= .5 if scores else None
    fp = int(predicted is True and watch_expected is False); fn = int(predicted is False and watch_expected is True)
    summaries = summarize_ai_attempts(attempts); cost = round(sum(item.total_cost or 0 for item in summaries), 6) if summaries and any(item.total_cost is not None for item in summaries) else None
    failures = []
    if not scores: failures.append("no_evaluator_scores")
    if llm_only: failures.append("llm_judge_is_sole_evidence")
    if not reproducible: failures.append("non_reproducible_evaluation")
    if watch_expected is None: failures.append("missing_watch_outcome")
    return EvaluationQualification(agreement, round(pvariance(scores), 6) if len(scores) > 1 else None, reproducible, fp, fn, cost, not failures, tuple(failures))


@dataclass(frozen=True, slots=True)
class MemoryIntegrationQualification:
    """Qualifies the REAL Memory integration (Execution 04, Task 11) —
    replaces the removed MemoryQualification, which qualified a local
    promote()/KnowledgeRecord duplicate-authority path that no longer
    exists. `delivery` is None when no envelope was supplied (structural
    check only)."""

    no_local_duplicate_authority: bool
    delivery: LessonDeliveryResult | None
    degraded_mode_truthful: bool
    qualified: bool
    failures: tuple[str, ...]
    uncertainty: str = "a truthful degraded result is not a promotion; only Memory's own accepted candidate is durable knowledge"


def qualify_memory_integration(*, envelope: dict | None = None, **bridge_kwargs) -> MemoryIntegrationQualification:
    """Structural check (no second durable-memory authority survives in
    `memory.py`) always runs. If `envelope` is given, attempts a real
    delivery via `propose_lesson_or_degrade` and folds the result in.
    `degraded_mode_truthful` is True whenever no exception escaped the
    delivery attempt — i.e. failure was reported, never silently hidden or
    fabricated as success — which is true both when no envelope was given
    and when a real (accepted-or-degraded) result came back.
    """
    no_local_duplicate_authority = not any(
        hasattr(_memory_module, name) for name in ("KnowledgeRecord", "promote", "supersede")
    )
    delivery: LessonDeliveryResult | None = None
    degraded_mode_truthful = True
    if envelope is not None:
        delivery = propose_lesson_or_degrade(envelope, **bridge_kwargs)
        # propose_lesson_or_degrade already never raises for a reachable-
        # but-rejecting or unreachable Memory (verified by Performance/
        # tests/test_memory_bridge.py); truthfulness means the result
        # always states clearly whether delivery happened.
        degraded_mode_truthful = delivery.delivered or delivery.degraded_reason is not None
    failures = []
    if not no_local_duplicate_authority:
        failures.append("local_duplicate_memory_authority_present")
    if not degraded_mode_truthful:
        failures.append("degraded_mode_not_truthful")
    return MemoryIntegrationQualification(
        no_local_duplicate_authority, delivery, degraded_mode_truthful, not failures, tuple(failures)
    )
