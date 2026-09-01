"""Qualification gates for evaluator ensembles and rebuildable Performance Memory."""
from __future__ import annotations
from dataclasses import dataclass
from statistics import pvariance

from .ai_accounting import AIAnalysisAttempt, summarize_ai_attempts
from .contracts import ClaimKind
from .evaluation import EvaluationResult, EvaluatorKind
from .memory import KnowledgeRecord, MemoryEvidence, promote
from .memory_retrieval import MemoryHit, retain, retrieve_memory
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
class MemoryQualification:
    promoted: KnowledgeRecord | None; hits: tuple[MemoryHit, ...]; retained: tuple[MemoryEvidence, ...]
    backup_restored: bool; contradictions_resolved: bool; supersession_checked: bool; historical_valid: bool; qualified: bool; failures: tuple[str, ...]
    uncertainty: str = "Memory is rebuildable from provenance; retrieval is not truth and noisy/AI-only interpretations are not promoted"


def qualify_memory(evidence: tuple[MemoryEvidence, ...], *, query: str, allowed_refs: frozenset[str], backup_restored: bool, contradictions_resolved: bool, supersession_checked: bool, historical_valid: bool) -> MemoryQualification:
    durable = tuple(item for item in evidence if item.claim_kind in {ClaimKind.OBSERVED, ClaimKind.DERIVED})
    promoted = promote(durable)
    retained = retain(durable, allowed_refs=allowed_refs)
    hits = retrieve_memory(query, retained)
    failures = []
    if promoted is None: failures.append("insufficient_grounded_provenance_for_promotion")
    if len(retained) != len(durable): failures.append("retention_removed_unapproved_provenance")
    if not backup_restored: failures.append("backup_restore_unverified")
    if not contradictions_resolved: failures.append("contradictions_unresolved")
    if not supersession_checked: failures.append("supersession_unchecked")
    if not historical_valid: failures.append("historical_validity_unverified")
    return MemoryQualification(promoted, hits, retained, backup_restored, contradictions_resolved, supersession_checked, historical_valid, not failures, tuple(failures))
