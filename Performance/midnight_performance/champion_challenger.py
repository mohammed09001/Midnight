"""Frozen-and-recent champion/challenger evaluation; promotion remains an explicit later action."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from .contracts import ClaimKind
from .dataset import DatasetRow
from .learning_models import BinaryModel

_METHOD = "champion-challenger"
_VERSION = "1"

@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    snapshot_fingerprint: str; rows: tuple[DatasetRow, ...]; frozen: bool
    def __post_init__(self) -> None:
        if not self.snapshot_fingerprint.strip() or not self.rows or any(row.label is None for row in self.rows):
            raise ValueError("evaluation dataset requires fingerprint and labeled rows")

@dataclass(frozen=True, slots=True)
class ChallengePolicy:
    minimum_brier_improvement: float; maximum_cohort_brier_regression: float; minimum_cohort_size: int = 2
    def __post_init__(self) -> None:
        if self.minimum_brier_improvement < 0 or self.maximum_cohort_brier_regression < 0 or self.minimum_cohort_size < 1:
            raise ValueError("challenge thresholds must be non-negative and cohort size positive")

@dataclass(frozen=True, slots=True)
class DatasetComparison:
    snapshot_fingerprint: str; champion_brier: float; challenger_brier: float
    @property
    def improvement(self) -> float: return round(self.champion_brier - self.challenger_brier, 3)

@dataclass(frozen=True, slots=True)
class CohortComparison:
    cohort: str; count: int; champion_brier: float; challenger_brier: float
    @property
    def regression(self) -> float: return round(self.challenger_brier - self.champion_brier, 3)

@dataclass(frozen=True, slots=True)
class ChallengerReport:
    frozen: DatasetComparison; recent: DatasetComparison; cohorts: tuple[CohortComparison, ...]; promote: bool; reasons: tuple[str, ...]
    method: str = _METHOD; method_version: str = _VERSION; claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "comparisons apply only to supplied frozen and recent datasets; promotion is a recommendation, not deployment or causal proof"

def _brier(model: BinaryModel, rows: tuple[DatasetRow, ...]) -> float:
    return round(sum((model.probability(row) - int(row.label == model.positive_label)) ** 2 for row in rows) / len(rows), 3)

def _compare(champion: BinaryModel, challenger: BinaryModel, dataset: EvaluationDataset) -> DatasetComparison:
    if champion.positive_label != challenger.positive_label or champion.feature_names != challenger.feature_names:
        raise ValueError("champion and challenger must have the same label and feature schema")
    if any(tuple(sorted(row.features)) != champion.feature_names for row in dataset.rows):
        raise ValueError("evaluation rows must match model feature schema")
    return DatasetComparison(dataset.snapshot_fingerprint, _brier(champion, dataset.rows), _brier(challenger, dataset.rows))

def evaluate_challenger(champion: BinaryModel, challenger: BinaryModel, frozen: EvaluationDataset, recent: EvaluationDataset, *, policy: ChallengePolicy, cohort_key: str = "project") -> ChallengerReport:
    """Require measurable Brier improvement on frozen and recent snapshots without cohort harm."""
    if not frozen.frozen or recent.frozen: raise ValueError("evaluation requires one frozen holdout and one non-frozen recent dataset")
    frozen_result, recent_result = _compare(champion, challenger, frozen), _compare(champion, challenger, recent)
    groups: dict[str, list[DatasetRow]] = {}
    for row in recent.rows: groups.setdefault(row.agent_metadata.get(cohort_key, "unknown"), []).append(row)
    cohorts = tuple(CohortComparison(name, len(rows), _brier(champion, tuple(rows)), _brier(challenger, tuple(rows))) for name, rows in sorted(groups.items()) if len(rows) >= policy.minimum_cohort_size)
    reasons = []
    if frozen_result.improvement < policy.minimum_brier_improvement: reasons.append("frozen holdout improvement is insufficient")
    if recent_result.improvement < policy.minimum_brier_improvement: reasons.append("recent-data improvement is insufficient")
    harmed = [item.cohort for item in cohorts if item.regression > policy.maximum_cohort_brier_regression]
    if harmed: reasons.append(f"unacceptable cohort regression: {harmed}")
    return ChallengerReport(frozen_result, recent_result, cohorts, not reasons, tuple(reasons))
