"""Append-only human review labels and evaluation-agreement projections."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from collections import Counter
from .contracts import ClaimKind
from .evaluation import EvaluationResult

@dataclass(frozen=True, slots=True)
class ReviewLabel:
    subject_id: str; reviewer_id: str; label: str; confidence: float; evidence: tuple[str, ...]; evaluator_refs: tuple[str, ...]; submitted_at: datetime
    def __post_init__(self):
        if not all((self.subject_id.strip(), self.reviewer_id.strip(), self.label.strip())) or not 0 <= self.confidence <= 1 or self.submitted_at.tzinfo is None: raise ValueError("review label requires identity, bounded confidence, and timezone-aware time")
@dataclass(frozen=True, slots=True)
class ReviewStore:
    labels: tuple[ReviewLabel, ...] = ()
    def add(self, label: ReviewLabel) -> "ReviewStore":
        if any((x.subject_id, x.reviewer_id, x.submitted_at) == (label.subject_id, label.reviewer_id, label.submitted_at) for x in self.labels): raise ValueError("duplicate review submission")
        return ReviewStore(self.labels + (label,))
@dataclass(frozen=True, slots=True)
class AgreementReport:
    subject_id: str; observed: int; agreement: float | None; labels: tuple[str, ...]; active_learning_question: bool; claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "agreement measures supplied evaluators and labels only; disagreement is an uncertainty signal, not truth"
def analyze_agreement(subject_id: str, evaluations: tuple[EvaluationResult, ...], labels: tuple[ReviewLabel, ...], *, threshold: float = .5) -> AgreementReport:
    if not 0 <= threshold <= 1: raise ValueError("threshold must be zero-one")
    votes = ["pass" if x.score >= threshold else "fail" for x in evaluations if x.subject_id == subject_id and x.score is not None]
    votes += [x.label for x in labels if x.subject_id == subject_id]
    if not votes: return AgreementReport(subject_id, 0, None, (), True, ClaimKind.UNKNOWN)
    majority = max(Counter(votes).values()); agreement = round(majority / len(votes), 3)
    return AgreementReport(subject_id, len(votes), agreement, tuple(sorted(votes)), agreement < 1)
