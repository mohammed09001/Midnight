"""Descriptive analytics over dataset rows; useful before any ML model exists."""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from typing import Callable, Iterable, Mapping
from .contracts import ClaimKind
from .dataset import DatasetRow

_METHOD = "descriptive"
_VERSION = "1"

@dataclass(frozen=True, slots=True)
class Distribution:
    feature: str; count: int; missing: int; mean: float | None; median: float | None; p25: float | None; p75: float | None; p90: float | None; minimum: float | None; maximum: float | None; std: float | None; ci95: tuple[float, float] | None; method: str; method_version: str; claim_kind: str; uncertainty: str

@dataclass(frozen=True, slots=True)
class Trend:
    feature: str; n: int; slope: float | None; direction: str; method: str; method_version: str; uncertainty: str

def percentile(sorted_values: list[float], quantile: float) -> float:
    """Interpolated quantile of an ascending-sorted sample; shared descriptive primitive."""
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction

def describe(feature: str, values: Iterable[float | None]) -> Distribution:
    """Distribution, percentiles, and a normal-approximation 95% interval of the mean."""
    all_values = tuple(values)
    observed = sorted(value for value in all_values if value is not None)
    missing = len(all_values) - len(observed)
    count = len(observed)
    if not count:
        return Distribution(feature, 0, 0, None, None, None, None, None, None, None, None, None, _METHOD, _VERSION, "derived", "no observed values")
    mean = sum(observed) / count
    std = sqrt(sum((value - mean) ** 2 for value in observed) / (count - 1)) if count > 1 else None
    ci95 = (round(mean - 1.96 * std / sqrt(count), 3), round(mean + 1.96 * std / sqrt(count), 3)) if std is not None else None
    return Distribution(
        feature, count, missing, round(mean, 3), round(percentile(observed, .5), 3), round(percentile(observed, .25), 3),
        round(percentile(observed, .75), 3), round(percentile(observed, .90), 3), observed[0], observed[-1],
        round(std, 3) if std is not None else None, ci95, _METHOD, _VERSION, "derived",
        "95% interval is a normal approximation of the mean, not a distribution-free guarantee",
    )

def trend(feature: str, points: tuple[float | None, ...]) -> Trend:
    """Least-squares slope over chronologically ordered bucket values; gaps are skipped."""
    series = [(index, value) for index, value in enumerate(points) if value is not None]
    if len(series) < 2:
        return Trend(feature, len(series), None, "insufficient_points", _METHOD, _VERSION, "at least two non-missing points are required")
    n = len(series)
    mean_x = sum(x for x, _ in series) / n
    mean_y = sum(y for _, y in series) / n
    slope = sum((x - mean_x) * (y - mean_y) for x, y in series) / sum((x - mean_x) ** 2 for x, _ in series)
    direction = "rising" if slope > 0 else "falling" if slope < 0 else "flat"
    return Trend(feature, n, round(slope, 6), direction, _METHOD, _VERSION, "slope over bucket means is descriptive, not causal")

def breakdown(rows: tuple[DatasetRow, ...], feature: str, by: Callable[[DatasetRow], str | None]) -> Mapping[str, Distribution]:
    """Per-group distributions keyed by task, agent, project, label class, or any caller key."""
    groups: dict[str, list[float | None]] = {}
    for row in rows:
        key = by(row)
        if key is None:
            continue
        groups.setdefault(key, []).append(row.features.get(feature))
    return {key: describe(feature, tuple(values)) for key, values in sorted(groups.items())}
