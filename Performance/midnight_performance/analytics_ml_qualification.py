"""Qualification gates that compose canonical analytics and ML projections."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .bootstrap import bootstrap_metric
from .correlation import analyze_correlations
from .data_drift import DriftReport, detect_drift
from .dataset import DatasetRow
from .descriptive import Distribution, Trend, describe, trend
from .ml import MLReadinessReport, PartitionSplit
from .model_assurance import ModelQuality
from .model_registry import CohortPerformance, ModelMonitoringReport
from .segmentation import Segmentation, segment
from .stats_tests import ComparisonResult, compare_samples
from .confounders import compare_stratified


class QualificationState(str, Enum):
    QUALIFIED = "qualified"; DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class AnalyticsQualification:
    frozen_dataset_fingerprint: str; distribution: Distribution; cohorts: Segmentation
    comparison: ComparisonResult; interval_sufficient: bool; correlations_sufficient: bool; confounder_sufficient: bool
    trend: Trend; drift: DriftReport; state: QualificationState; failures: tuple[str, ...]
    uncertainty: str = "analytics are derived/statistical summaries of the supplied frozen data, never causal or outcome truth"


def qualify_analytics(fingerprint: str, rows: tuple[DatasetRow, ...], reference: tuple[DatasetRow, ...], current: tuple[DatasetRow, ...], *, feature: str, cohort: Callable[[DatasetRow], str | None]) -> AnalyticsQualification:
    """Run the canonical descriptive, cohort, statistical, trend, correlation, and drift paths."""
    if not fingerprint.strip(): raise ValueError("a frozen dataset fingerprint is required")
    values = tuple(float(row.features[feature]) for row in rows if row.features.get(feature) is not None)
    distribution = describe(feature, values)
    cohorts = segment(rows, "qualification_cohort", feature, cohort, min_cohort=1)
    groups = sorted({cohort(row) for row in rows if cohort(row) is not None})
    samples = [tuple(float(row.features[feature]) for row in rows if cohort(row) == group and row.features.get(feature) is not None) for group in groups[:2]]
    comparison = compare_samples(*(samples if len(samples) == 2 else ((), ())), feature=feature, min_size=2)
    interval = bootstrap_metric(values, resamples=20, min_size=2)
    series = trend(feature, values)
    correlations = analyze_correlations(rows, numeric=(feature,), categorical=("project",), min_observations=2)
    stratified = compare_stratified(rows, cohort, feature, {"project": lambda row: row.agent_metadata.get("project")}, min_stratum=1, resamples=20) if len(groups) == 2 else None
    drift = detect_drift(reference, current, numeric=(feature,), categorical=("project",), min_reference=1, min_current=1)
    failures = []
    if not values: failures.append("missing_feature_values")
    if not comparison.sufficient: failures.append("insufficient_statistical_cohorts")
    if not interval.sufficient: failures.append("insufficient_confidence_interval")
    if not correlations.pairs or any(not item.sufficient for item in correlations.pairs): failures.append("insufficient_correlation_evidence")
    if stratified is None or stratified.adjusted_effect is None: failures.append("insufficient_confounder_control")
    if series.slope is None: failures.append("insufficient_trend_evidence")
    if any(not item.sufficient for item in drift.results): failures.append("insufficient_drift_evidence")
    return AnalyticsQualification(fingerprint, distribution, cohorts, comparison, interval.sufficient, bool(correlations.pairs) and all(item.sufficient for item in correlations.pairs), stratified is not None and stratified.adjusted_effect is not None, series, drift, QualificationState.DEGRADED if failures else QualificationState.QUALIFIED, tuple(failures))


@dataclass(frozen=True, slots=True)
class MLQualificationEvidence:
    frozen_split: PartitionSplit | None; readiness: MLReadinessReport | None
    baseline_count: int; calibration: ModelQuality | None; cohort_metrics: tuple[CohortPerformance, ...]
    monitoring: ModelMonitoringReport | None; rollback_target: str | None; decision_improved: bool


@dataclass(frozen=True, slots=True)
class MLQualification:
    evidence: MLQualificationEvidence; state: QualificationState; failures: tuple[str, ...]
    uncertainty: str = "model qualification proves only supplied frozen evaluation evidence; learned outputs remain derived/predicted, not causal truth"


def qualify_ml(value: MLQualificationEvidence) -> MLQualification:
    """Require every model-release gate before a learned method can be qualified."""
    failures: list[str] = []
    split = value.frozen_split
    if split is None or not split.train or not split.validation or not split.test: failures.append("missing_frozen_train_validation_test_split")
    if value.readiness is None or not value.readiness.allowed: failures.append("readiness_or_leakage_gate_failed")
    if value.baseline_count < 1: failures.append("missing_baseline_comparison")
    if value.calibration is None: failures.append("missing_calibration")
    if not value.cohort_metrics: failures.append("missing_cohort_metrics")
    if value.monitoring is None: failures.append("missing_drift_criteria")
    if not value.rollback_target: failures.append("missing_rollback_target")
    if not value.decision_improved: failures.append("no_proven_improvement_for_intended_decision")
    return MLQualification(value, QualificationState.DEGRADED if failures else QualificationState.QUALIFIED, tuple(failures))
