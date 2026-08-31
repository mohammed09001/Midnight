"""Data and concept drift detection between a reference window and the present; shift signals, never performance verdicts."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from math import isfinite, log2, sqrt
from typing import Sequence
from .contracts import ClaimKind
from .correlation import spearman
from .dataset import DatasetRow
from .descriptive import percentile

_METHOD = "data-drift"
_VERSION = "1"
DEFAULT_NUMERIC_THRESHOLD = 0.1
DEFAULT_CATEGORICAL_THRESHOLD = 0.1
DEFAULT_RELATIONSHIP_THRESHOLD = 0.3
DEFAULT_MIN_REFERENCE = 10
DEFAULT_MIN_CURRENT = 5
_QUANTILE_GRID = 1000

@dataclass(frozen=True, slots=True)
class DriftResult:
    variable: str; kind: str; n_reference: int; n_current: int; statistic_name: str; statistic: float | None; threshold: float; drifted: bool; sufficient: bool; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if not self.variable.strip(): raise ValueError("drift variable must be named")
        if self.threshold <= 0: raise ValueError("drift thresholds must be positive")
        if self.statistic is not None and not isfinite(self.statistic): raise ValueError("drift statistics must be finite")
        if self.sufficient and self.statistic is None: raise ValueError("sufficient drift results carry a statistic")
        if not self.sufficient and self.statistic is not None: raise ValueError("insufficient drift results carry no statistic")
        if self.drifted and not self.sufficient: raise ValueError("drift is never declared without sufficient evidence")
        expected = self.sufficient and self.statistic is not None and self.statistic > self.threshold
        if self.drifted is not expected: raise ValueError("drifted must mirror the threshold comparison over a sufficient statistic")

@dataclass(frozen=True, slots=True)
class DriftReport:
    reference_rows: int; current_rows: int; numeric: tuple[str, ...]; categorical: tuple[str, ...]; relationships: tuple[tuple[str, str], ...]; results: tuple[DriftResult, ...]; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if self.reference_rows < 0 or self.current_rows < 0: raise ValueError("window sizes must not be negative")

    @property
    def drifted_variables(self) -> tuple[str, ...]:
        return tuple(result.variable for result in self.results if result.drifted)

def _numeric_wasserstein(reference: tuple[float, ...], current: tuple[float, ...]) -> float:
    """Mean absolute quantile gap (one-dimensional Wasserstein distance) over a fixed probability grid."""
    ordered_reference, ordered_current = sorted(reference), sorted(current)
    total = 0.0
    for step in range(1, _QUANTILE_GRID + 1):
        probability = step / _QUANTILE_GRID
        total += abs(percentile(ordered_reference, probability) - percentile(ordered_current, probability))
    return total / _QUANTILE_GRID

def _dispersion(values: tuple[float, ...]) -> float:
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / (len(values) - 1)) ** .5 if len(values) > 1 else 0.0

def _jensen_shannon_distance(first: dict[str, float], second: dict[str, float]) -> float:
    """Jensen-Shannon distance over level shares with base-2 logs; bounded zero to one; zero-share levels contribute nothing."""
    levels = set(first) | set(second)
    mixture = {level: (first.get(level, 0.0) + second.get(level, 0.0)) / 2 for level in levels}

    def margin(shares: dict[str, float]) -> float:
        total = 0.0
        for level, share in shares.items():
            if share > 0:
                total += share * log2(share / mixture[level])
        return total

    divergence = .5 * margin(first) + .5 * margin(second)
    return sqrt(max(0.0, min(1.0, divergence)))

def _shares(values: Sequence[str]) -> dict[str, float]:
    counts = Counter(values)
    total = sum(counts.values())
    return {level: count / total for level, count in counts.items()}

def _numeric_values(rows: tuple[DatasetRow, ...], feature: str) -> tuple[float, ...]:
    return tuple(float(row.features[feature]) for row in rows if row.features.get(feature) is not None)

def _categorical_values(rows: tuple[DatasetRow, ...], variable: str) -> tuple[str, ...]:
    if variable == "label":
        return tuple(row.label for row in rows if row.label is not None)
    return tuple(str(row.agent_metadata[variable]) for row in rows if row.agent_metadata.get(variable) is not None)

def _gated(variable: str, kind: str, statistic_name: str, threshold: float, n_reference: int, n_current: int, min_reference: int, min_current: int) -> DriftResult | None:
    if threshold <= 0: raise ValueError("drift thresholds must be positive")
    if min_reference < 1 or min_current < 1: raise ValueError("minimum window sizes must be positive")
    if n_reference < min_reference or n_current < min_current:
        return DriftResult(variable, kind, n_reference, n_current, statistic_name, None, threshold, False, False, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "windows below the minimum sizes are not compared; drift stays unknown rather than assumed absent")
    return None

def detect_numeric_drift(variable: str, reference: Sequence[float], current: Sequence[float], *, threshold: float = DEFAULT_NUMERIC_THRESHOLD, min_reference: int = DEFAULT_MIN_REFERENCE, min_current: int = DEFAULT_MIN_CURRENT) -> DriftResult:
    """Numeric distribution shift as Wasserstein distance normalized by reference dispersion."""
    first, second = tuple(float(value) for value in reference), tuple(float(value) for value in current)
    if any(not isfinite(value) for value in first + second): raise ValueError("drift values must be finite numbers")
    gated = _gated(variable, "numeric", "normalized_wasserstein", threshold, len(first), len(second), min_reference, min_current)
    if gated: return gated
    dispersion = _dispersion(first)
    statistic = round(_numeric_wasserstein(first, second) / dispersion if dispersion > 1e-12 else _numeric_wasserstein(first, second), 3)
    parts = ["wasserstein distance is normalized by reference dispersion" + (" (raw distance: zero-dispersion reference)" if dispersion <= 1e-12 else "") + "; drift is a distribution shift signal, not a performance judgment"]
    return DriftResult(variable, "numeric", len(first), len(second), "normalized_wasserstein", statistic, threshold, statistic > threshold, True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "; ".join(parts))

def detect_categorical_drift(variable: str, reference: Sequence[str], current: Sequence[str], *, threshold: float = DEFAULT_CATEGORICAL_THRESHOLD, min_reference: int = DEFAULT_MIN_REFERENCE, min_current: int = DEFAULT_MIN_CURRENT) -> DriftResult:
    """Categorical distribution shift as Jensen-Shannon distance over level shares."""
    first, second = tuple(str(value) for value in reference), tuple(str(value) for value in current)
    gated = _gated(variable, "categorical", "jensen_shannon_distance", threshold, len(first), len(second), min_reference, min_current)
    if gated: return gated
    statistic = round(_jensen_shannon_distance(_shares(first), _shares(second)), 3)
    return DriftResult(variable, "categorical", len(first), len(second), "jensen_shannon_distance", statistic, threshold, statistic > threshold, True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "jensen-shannon distance over level shares; drift is a distribution shift signal, not a performance judgment")

def detect_relationship_drift(x_name: str, y_name: str, reference_rows, current_rows, *, threshold: float = DEFAULT_RELATIONSHIP_THRESHOLD, min_reference: int = DEFAULT_MIN_REFERENCE, min_current: int = DEFAULT_MIN_CURRENT) -> DriftResult:
    """Concept drift over an outcome relationship: a material spearman shift between windows is reported, never causal."""
    variable = f"{x_name}~{y_name}"
    reference_population, current_population = tuple(reference_rows), tuple(current_rows)
    gated = _gated(variable, "relationship", "spearman_delta", threshold, len(reference_population), len(current_population), min_reference, min_current)
    if gated: return gated
    def pair(population: tuple[DatasetRow, ...]) -> tuple[list[float], list[float]]:
        left, right = [], []
        for row in population:
            x_value, y_value = row.features.get(x_name), row.features.get(y_name)
            if x_value is not None and y_value is not None:
                left.append(float(x_value))
                right.append(float(y_value))
        return left, right
    reference_x, reference_y = pair(reference_population)
    current_x, current_y = pair(current_population)
    reference = spearman(x_name, reference_x, y_name, reference_y)
    current = spearman(x_name, current_x, y_name, current_y)
    if not reference.sufficient or not current.sufficient:
        return DriftResult(variable, "relationship", len(reference_population), len(current_population), "spearman_delta", None, threshold, False, False, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, f"relationship drift needs sufficient correlations in both windows (reference {reference.n}, current {current.n} paired observations); unmeasured is not stable")
    statistic = round(abs(current.statistic - reference.statistic), 3)
    return DriftResult(variable, "relationship", len(reference_population), len(current_population), "spearman_delta", statistic, threshold, statistic > threshold, True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "a shift in association strength signals concept drift; correlation remains non-causal")

def detect_drift(reference_rows, current_rows, *, numeric: tuple[str, ...] = (), categorical: tuple[str, ...] = (), relationships: tuple[tuple[str, str], ...] = (), include_label: bool = False, numeric_threshold: float = DEFAULT_NUMERIC_THRESHOLD, categorical_threshold: float = DEFAULT_CATEGORICAL_THRESHOLD, relationship_threshold: float = DEFAULT_RELATIONSHIP_THRESHOLD, min_reference: int = DEFAULT_MIN_REFERENCE, min_current: int = DEFAULT_MIN_CURRENT) -> DriftReport:
    """Compare a reference window to the present across feature distributions, categorical context, and outcome relationships."""
    reference_population, current_population = tuple(reference_rows), tuple(current_rows)
    numeric_names = tuple(sorted(dict.fromkeys(numeric)))
    categorical_names = tuple(sorted(dict.fromkeys((*categorical, "label") if include_label else categorical)))
    results: list[DriftResult] = []
    for name in numeric_names:
        results.append(detect_numeric_drift(name, _numeric_values(reference_population, name), _numeric_values(current_population, name), threshold=numeric_threshold, min_reference=min_reference, min_current=min_current))
    for name in categorical_names:
        results.append(detect_categorical_drift(name, _categorical_values(reference_population, name), _categorical_values(current_population, name), threshold=categorical_threshold, min_reference=min_reference, min_current=min_current))
    for x_name, y_name in relationships:
        results.append(detect_relationship_drift(x_name, y_name, reference_population, current_population, threshold=relationship_threshold, min_reference=min_reference, min_current=min_current))
    drifted = [result.variable for result in results if result.drifted]
    parts = [f"{len(drifted)} of {len(results)} monitored variables drift between windows" + (f": {drifted}" if drifted else "")]
    parts.append("drift invalidates historical assumptions and models; it is never a performance verdict")
    return DriftReport(len(reference_population), len(current_population), numeric_names, categorical_names, tuple(relationships), tuple(results), _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "; ".join(parts))
