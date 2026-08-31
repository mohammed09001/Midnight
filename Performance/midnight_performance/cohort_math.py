"""Transparent historical cohort rates; correlations stay statistical, never causal."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .associations import AssociationKind, OutcomeAssociation
from .contracts import ClaimKind
from .feedback import FeedbackRecord, FeedbackReason, Judgment
from .vector import Dimension

_METHOD = "cohort-measures"
_VERSION = "1"

@dataclass(frozen=True, slots=True)
class CohortRun:
    """One prompt run's canonical evidence as assembled by the caller."""
    prompt_run_id: str; feedback: tuple[FeedbackRecord, ...] = (); associations: tuple[OutcomeAssociation, ...] = (); rework: bool = False; verification_gaps: bool = False

@dataclass(frozen=True, slots=True)
class CohortMeasures:
    cohort: str; runs: int; labeled: int; accepted_rate: float | None; partial_failure_rate: float | None; issue_rate: float | None; regression_rate: float | None; rework_rate: float | None; verification_gap_rate: float | None; method: str; method_version: str; claim_kind: ClaimKind; confidence: float | None; uncertainty: str

    def __post_init__(self):
        if not self.cohort.strip(): raise ValueError("cohort id is required")
        if self.runs < 1: raise ValueError("cohort measures require at least one run")

    def dimension(self) -> Dimension:
        valued = [x for x in (self.accepted_rate, self.issue_rate, self.regression_rate, self.rework_rate, self.verification_gap_rate) if x is not None]
        value = round(sum(valued) / len(valued), 3) if valued else None
        return Dimension("outcome_quality", value, ClaimKind.STATISTICAL, _METHOD, _VERSION, self.confidence, self.uncertainty)

def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None

def measure_cohort(cohort: str, runs: Iterable[CohortRun]) -> CohortMeasures:
    """Rates over comparable cohorts; empty denominators stay None instead of pretending success."""
    population = tuple(runs)
    if not population:
        raise ValueError("cohort measures require at least one run")
    labeled = [item for item in population if item.feedback]
    judged = [item.feedback[0].judgment for item in labeled]
    issue_runs = sum(any(a.kind is AssociationKind.RUNTIME_ISSUE for a in item.associations) for item in population)
    regression_runs = sum(any(reason is FeedbackReason.REGRESSION for record in item.feedback for reason in record.reasons) for item in population)
    rework_runs = sum(item.rework for item in population)
    gap_runs = sum(item.verification_gaps for item in population)
    uncertain = sum(judgment is Judgment.UNCERTAIN for judgment in judged)
    coverage = round(len(labeled) / len(population), 3)
    rates = {
        "accepted_rate": _rate(sum(j is Judgment.ACHIEVED for j in judged), len(labeled)),
        "partial_failure_rate": _rate(sum(j in (Judgment.PARTIAL, Judgment.NOT_ACHIEVED) for j in judged), len(labeled)),
        "issue_rate": _rate(issue_runs, len(population)),
        "regression_rate": _rate(regression_runs, len(labeled)),
        "rework_rate": _rate(rework_runs, len(population)),
        "verification_gap_rate": _rate(gap_runs, len(population)),
    }
    parts = [f"{len(labeled)}/{len(population)} runs carry user labels"]
    if uncertain:
        parts.append(f"{uncertain} UNCERTAIN labels count toward denominators but never as success")
    parts.append("issue and regression measures are correlations over sibling references, never causal claims")
    return CohortMeasures(
        cohort, len(population), len(labeled), rates["accepted_rate"], rates["partial_failure_rate"], rates["issue_rate"],
        rates["regression_rate"], rates["rework_rate"], rates["verification_gap_rate"], _METHOD, _VERSION,
        ClaimKind.STATISTICAL, coverage, "; ".join(parts),
    )
