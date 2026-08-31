"""Anomaly baselines over prompt runs: transparent robust z-scores; an anomaly is unusual, never automatically bad."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Sequence
from .contracts import ClaimKind
from .dataset import DatasetRow
from .descriptive import percentile

_METHOD = "anomaly-baseline"
_VERSION = "1"
DEFAULT_Z_THRESHOLD = 3.5
DEFAULT_MIN_BASELINE = 10
_NORMAL_QUANTILE = .6745

@dataclass(frozen=True, slots=True)
class FeatureBaseline:
    feature: str; n: int; median: float | None; mad: float | None; uncertainty: str
    def __post_init__(self):
        if not self.feature.strip(): raise ValueError("baseline feature must be named")
        if self.n < 0: raise ValueError("baseline count must not be negative")
        if (self.median is None) is not (self.mad is None): raise ValueError("median and mad are reported together or not at all")

@dataclass(frozen=True, slots=True)
class BaselineProfile:
    rows: int; baselines: tuple[FeatureBaseline, ...]; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if self.rows < 0: raise ValueError("baseline row count must not be negative")
        names = [item.feature for item in self.baselines]
        if len(names) != len(set(names)): raise ValueError("baseline features must be unique")
    def baseline(self, feature: str) -> FeatureBaseline | None:
        return next((item for item in self.baselines if item.feature == feature), None)

@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    prompt_run_id: str; feature: str; value: float; direction: str; score: float | None; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if not self.prompt_run_id.strip(): raise ValueError("findings require a prompt run id")
        if not self.feature.strip(): raise ValueError("findings require a feature name")
        if not isfinite(self.value): raise ValueError("finding values must be finite")
        if self.direction not in {"high", "low", "deviation"}: raise ValueError("finding direction must be high, low, or deviation")
        if self.direction == "deviation" and self.score is not None: raise ValueError("deviation findings carry no score; constant-baseline deviations are unscored")
        if self.direction in {"high", "low"} and (self.score is None or not isfinite(self.score)): raise ValueError("high and low findings carry a finite robust z score")

@dataclass(frozen=True, slots=True)
class AnomalyReport:
    rows_scanned: int; findings: tuple[AnomalyFinding, ...]; skipped_missing: int; unmeasured_features: tuple[str, ...]; method: str; method_version: str; claim_kind: str; uncertainty: str

def _median_absolute_deviation(values: tuple[float, ...]) -> tuple[float, float]:
    ordered = sorted(values)
    median = percentile(ordered, .5)
    mad = percentile(sorted(abs(value - median) for value in values), .5)
    return median, mad

def build_baseline(rows, features: Sequence[str], *, min_baseline: int = DEFAULT_MIN_BASELINE) -> BaselineProfile:
    """Median and MAD per feature over historical rows; tiny baselines stay unknown instead of inventing normality."""
    if not features: raise ValueError("at least one baseline feature is required")
    if min_baseline < 1: raise ValueError("minimum baseline size must be positive")
    population = tuple(rows)
    baselines: list[FeatureBaseline] = []
    for feature in features:
        if not feature.strip(): raise ValueError("baseline features must be named")
        values = tuple(float(row.features[feature]) for row in population if row.features.get(feature) is not None)
        if len(values) < min_baseline:
            baselines.append(FeatureBaseline(feature, len(values), None, None, f"{len(values)} observations is below {min_baseline}; no baseline is claimed"))
            continue
        median, mad = _median_absolute_deviation(values)
        baselines.append(FeatureBaseline(feature, len(values), round(median, 3), round(mad, 6), "median and median-absolute-deviation baseline; no distribution assumed"))
    unmeasured = tuple(item.feature for item in baselines if item.median is None)
    parts = ["baselines are medians and median-absolute deviations over observed rows"]
    if unmeasured:
        parts.append(f"unmeasured features with too little history: {unmeasured}")
    return BaselineProfile(len(population), tuple(baselines), _METHOD, _VERSION, ClaimKind.DERIVED.value, "; ".join(parts))

def detect_anomalies(profile: BaselineProfile, rows, *, z_threshold: float = DEFAULT_Z_THRESHOLD) -> AnomalyReport:
    """Flag prompt runs whose features clear the robust-z threshold against the baseline; anomalies are unusual, not bad."""
    if z_threshold <= 0: raise ValueError("z threshold must be positive")
    population = tuple(rows)
    findings: list[AnomalyFinding] = []
    skipped_missing = 0
    for row in population:
        for baseline in profile.baselines:
            value = row.features.get(baseline.feature)
            if value is None:
                skipped_missing += 1
                continue
            value = float(value)
            if not isfinite(value): raise ValueError("feature values must be finite numbers")
            if baseline.median is None:
                continue
            if baseline.mad is not None and baseline.mad > 1e-12:
                score = round(_NORMAL_QUANTILE * (value - baseline.median) / baseline.mad, 3)
                if abs(score) > z_threshold:
                    findings.append(AnomalyFinding(row.prompt_run_id, baseline.feature, value, "high" if score > 0 else "low", score, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "robust z over median and MAD; anomaly means unusual relative to baseline, never bad performance"))
            elif value != baseline.median:
                findings.append(AnomalyFinding(row.prompt_run_id, baseline.feature, value, "deviation", None, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "zero-dispersion baseline; any deviation from the constant median is flagged as unusual, not bad"))
    unmeasured = tuple(item.feature for item in profile.baselines if item.median is None)
    parts = ["transparent robust z-scores over the features the caller baselines, e.g. change size, dispersion, verification, duration, failure patterns, and outcome signals"]
    if unmeasured:
        parts.append(f"features without a usable baseline are never flagged: {unmeasured}")
    parts.append(f"{skipped_missing} feature values were missing and skipped")
    parts.append("an anomaly is unusual, not bad; performance judgments require outcome evidence")
    return AnomalyReport(len(population), tuple(findings), skipped_missing, unmeasured, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "; ".join(parts))
