"""Time-series and trend analysis over bucketed prompt-experience rows; candidates, never confirmed causes."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from .contracts import ClaimKind
from .dataset import DatasetRow
from .descriptive import Trend, trend

_METHOD = "time-series"
_VERSION = "1"
DEFAULT_MIN_SEGMENT = 3
DEFAULT_THRESHOLD = 1.0

@dataclass(frozen=True, slots=True)
class SeriesPoint:
    bucket: str; count: int; missing: int; value: float | None
    def __post_init__(self):
        if not self.bucket.strip(): raise ValueError("bucket key is required")
        if self.count < 0 or self.missing < 0: raise ValueError("bucket counts must not be negative")
        if self.count == 0 and self.value is not None: raise ValueError("empty buckets carry no value")

@dataclass(frozen=True, slots=True)
class RollingPoint:
    bucket: str; values_used: int; value: float | None
    def __post_init__(self):
        if not self.bucket.strip(): raise ValueError("bucket key is required")
        if self.values_used < 0: raise ValueError("values used must not be negative")
        if self.values_used == 0 and self.value is not None: raise ValueError("empty windows carry no value")

@dataclass(frozen=True, slots=True)
class SeasonalComparison:
    period: int; comparisons: int; mean_difference: float | None; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if self.period < 1: raise ValueError("seasonal period must be positive")
        if self.comparisons < 0: raise ValueError("comparison count must not be negative")
        if self.comparisons == 0 and self.mean_difference is not None: raise ValueError("no comparisons carry no difference")

@dataclass(frozen=True, slots=True)
class ChangePointCandidate:
    """Level-shift candidate; index counts buckets carrying observations, and left_bucket/right_bucket name the boundary unambiguously when buckets are missing."""
    index: int; left_bucket: str; right_bucket: str; left_n: int; right_n: int; left_mean: float; right_mean: float; difference: float; score: float | None
    def __post_init__(self):
        if self.index < 0: raise ValueError("candidate index must not be negative")
        if self.left_n < 1 or self.right_n < 1: raise ValueError("candidates need observations on both sides")

@dataclass(frozen=True, slots=True)
class TimeSeriesReport:
    feature: str; points: tuple[SeriesPoint, ...]; rolling: tuple[RollingPoint, ...] | None; seasonal: SeasonalComparison | None; change_points: tuple[ChangePointCandidate, ...]; overall_trend: Trend; method: str; method_version: str; claim_kind: str; uncertainty: str

def by_day(row: DatasetRow) -> str:
    """Calendar-day bucket key; ISO date strings sort chronologically."""
    return row.observed_at.date().isoformat()

def by_week(row: DatasetRow) -> str:
    """ISO week bucket key; ISO week strings sort chronologically."""
    iso = row.observed_at.date().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"

def by_month(row: DatasetRow) -> str:
    """Calendar-month bucket key; ISO month strings sort chronologically."""
    moment = row.observed_at
    return f"{moment.year:04d}-{moment.month:02d}"

def bucket_mean(rows, bucket: Callable[[DatasetRow], str | None], feature: str) -> tuple[SeriesPoint, ...]:
    """Chronologically ordered bucket means; bucket keys must sort chronologically."""
    if not feature.strip(): raise ValueError("feature name is required")
    groups: dict[str, list[float | None]] = {}
    for row in rows:
        key = bucket(row)
        if key is None:
            continue
        groups.setdefault(key, []).append(row.features.get(feature))
    points = []
    for key in sorted(groups):
        values = groups[key]
        observed = [value for value in values if value is not None]
        points.append(SeriesPoint(key, len(observed), len(values) - len(observed), round(sum(observed) / len(observed), 3) if observed else None))
    return tuple(points)

def rolling(points: tuple[SeriesPoint, ...], window: int) -> tuple[RollingPoint, ...]:
    """Trailing-window means over bucket values; empty windows stay unknown."""
    if window < 1: raise ValueError("rolling window must be positive")
    rolled = []
    for index in range(len(points)):
        trailing = [point.value for point in points[max(0, index - window + 1):index + 1] if point.value is not None]
        rolled.append(RollingPoint(points[index].bucket, len(trailing), round(sum(trailing) / len(trailing), 3) if trailing else None))
    return tuple(rolled)

def seasonal(points: tuple[SeriesPoint, ...], period: int) -> SeasonalComparison:
    """Same-phase bucket differences, e.g. period 7 over daily buckets compares weekday to weekday."""
    if period < 1: raise ValueError("seasonal period must be positive")
    differences = [points[index].value - points[index - period].value for index in range(period, len(points)) if points[index].value is not None and points[index - period].value is not None]
    parts = ["same-phase bucket differences are descriptive comparisons, not causal seasonality"]
    if len(points) <= period:
        parts.append(f"needs more than {period} buckets for one same-phase comparison")
    return SeasonalComparison(period, len(differences), round(sum(differences) / len(differences), 3) if differences else None, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "; ".join(parts))

def change_points(points: tuple[SeriesPoint, ...], *, min_segment: int = DEFAULT_MIN_SEGMENT, threshold: float = DEFAULT_THRESHOLD) -> tuple[ChangePointCandidate, ...]:
    """Transparent mean-shift candidates: every split whose pooled-standardized level gap clears the threshold."""
    if min_segment < 1: raise ValueError("minimum segment size must be positive")
    if threshold <= 0: raise ValueError("threshold must be positive")
    valued = [point for point in points if point.value is not None]
    candidates: list[ChangePointCandidate] = []
    for split in range(1, len(valued)):
        left, right = valued[:split], valued[split:]
        if len(left) < min_segment or len(right) < min_segment:
            continue
        left_mean = sum(point.value for point in left) / len(left)
        right_mean = sum(point.value for point in right) / len(right)
        difference = right_mean - left_mean
        left_var = sum((point.value - left_mean) ** 2 for point in left) / (len(left) - 1) if len(left) > 1 else 0.0
        right_var = sum((point.value - right_mean) ** 2 for point in right) / (len(right) - 1) if len(right) > 1 else 0.0
        pooled = ((left_var * (len(left) - 1) + right_var * (len(right) - 1)) / (len(left) + len(right) - 2)) ** .5 if len(left) + len(right) > 2 else 0.0
        score = round(abs(difference) / pooled, 3) if pooled > 1e-12 else None
        if (score is not None and score >= threshold) or (score is None and difference != 0):
            candidates.append(ChangePointCandidate(split, valued[split - 1].bucket, valued[split].bucket, len(left), len(right), round(left_mean, 3), round(right_mean, 3), round(difference, 3), score))
    return tuple(candidates)

def analyze_time_series(rows, feature: str, bucket: Callable[[DatasetRow], str | None], *, window: int | None = None, period: int | None = None, min_segment: int = DEFAULT_MIN_SEGMENT, threshold: float = DEFAULT_THRESHOLD) -> TimeSeriesReport:
    """Bucketed series with optional rolling means, seasonal comparisons, change-point candidates, and overall slope."""
    points = bucket_mean(rows, bucket, feature)
    rolled = rolling(points, window) if window is not None else None
    season = seasonal(points, period) if period is not None else None
    candidates = change_points(points, min_segment=min_segment, threshold=threshold)
    overall = trend(feature, tuple(point.value for point in points))
    parts = ["bucket means are descriptive derived values; trend and change-point candidates are statistical signals, never causal explanations"]
    if rolled is not None:
        parts.append("rolling means smooth bucket noise and lag behind level shifts")
    if season is not None:
        parts.append(f"seasonal comparison uses period {season.period}")
    return TimeSeriesReport(feature, points, rolled, season, candidates, overall, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "; ".join(parts))
