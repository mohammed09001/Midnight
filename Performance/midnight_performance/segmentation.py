"""Cohort segmentation with minimum sizes enforced so small groups never mislead."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from .contracts import ClaimKind
from .dataset import DatasetRow

_METHOD = "segmentation"
_VERSION = "1"
DEFAULT_MIN_COHORT = 5

@dataclass(frozen=True, slots=True)
class CohortSlice:
    key: str; runs: int; labeled: int; sufficient: bool; mean_feature: float | None; accepted_rate: float | None; uncertainty: str

@dataclass(frozen=True, slots=True)
class Segmentation:
    dimension: str; feature: str; min_cohort: int; slices: tuple[CohortSlice, ...]; method: str; method_version: str; claim_kind: str; uncertainty: str

def segment(rows: tuple[DatasetRow, ...], dimension: str, feature: str, by: Callable[[DatasetRow], str | None], *, min_cohort: int = DEFAULT_MIN_COHORT) -> Segmentation:
    """Compare cohorts by task category, repository region, component, agent/model, prompt pattern, verification strategy, feedback class, release period, or project — named by the caller."""
    if not dimension.strip():
        raise ValueError("segmentation dimension name is required")
    if min_cohort < 1:
        raise ValueError("minimum cohort size must be positive")
    groups: dict[str, list[DatasetRow]] = {}
    for row in rows:
        key = by(row)
        if key is None:
            continue
        groups.setdefault(key, []).append(row)
    slices: list[CohortSlice] = []
    insufficient: list[str] = []
    for key in sorted(groups):
        population = groups[key]
        runs = len(population)
        if runs < min_cohort:
            insufficient.append(f"{key}:{runs}")
            slices.append(CohortSlice(key, runs, sum(1 for item in population if item.label is not None), False, None, None, f"cohort of {runs} is below the minimum of {min_cohort}; no statistic reported"))
            continue
        observed = [value for value in (row.features.get(feature) for row in population) if value is not None]
        mean_feature = round(sum(observed) / len(observed), 3) if observed else None
        labeled = [row for row in population if row.label is not None]
        accepted_rate = round(sum(1 for row in labeled if row.label == "achieved") / len(labeled), 3) if labeled else None
        slices.append(CohortSlice(key, runs, len(labeled), True, mean_feature, accepted_rate, f"cohort of {runs} meets the minimum; statistics are descriptive"))
    uncertainty = f"cohorts below {min_cohort} runs are suppressed, not reported" + (f"; suppressed: {insufficient}" if insufficient else "")
    return Segmentation(dimension, feature, min_cohort, tuple(slices), _METHOD, _VERSION, ClaimKind.STATISTICAL.value, uncertainty)
