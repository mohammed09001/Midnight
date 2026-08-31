"""Combined analytical-data health projection; degraded evidence never becomes success."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .data_drift import DriftReport
from .dataset_versioning import DatasetSnapshot
from .quality import QualityReport, QualitySeverity, validate_quality


class DataHealthIssue(str, Enum):
    MISSING_CODE_WATCH_LINKS = "missing_code_watch_links"
    STALE_DATASET = "stale_dataset"
    DELAYED_FEEDBACK = "delayed_feedback"
    FEATURE_GENERATION_FAILURES = "feature_generation_failures"
    LABEL_IMBALANCE = "label_imbalance"
    DRIFT = "drift"
    INCOMPLETE_OUTCOME_WINDOW = "incomplete_outcome_window"


@dataclass(frozen=True, slots=True)
class DataHealthFinding:
    issue: DataHealthIssue
    severity: QualitySeverity
    detail: str


@dataclass(frozen=True, slots=True)
class DataHealthReport:
    dataset_fingerprint: str
    checked_at: datetime
    findings: tuple[DataHealthFinding, ...]
    quality: QualityReport
    degraded: bool
    uncertainty: str = "health findings describe supplied analytical evidence; they do not verify external Code, Watch, or runtime systems"


def assess_data_health(snapshot: DatasetSnapshot, *, now: datetime, maximum_dataset_age_seconds: float, maximum_feedback_delay_seconds: float, feature_failures: int = 0, incomplete_outcome_windows: int = 0, drift: DriftReport | None = None) -> DataHealthReport:
    """Assess supplied evidence and preserve unknown/absent integration state as a finding."""
    if now.tzinfo is None or maximum_dataset_age_seconds < 0 or maximum_feedback_delay_seconds < 0 or feature_failures < 0 or incomplete_outcome_windows < 0:
        raise ValueError("health monitoring inputs are invalid")
    quality = validate_quality(snapshot.rows, snapshot.definition)
    findings: list[DataHealthFinding] = []
    def add(issue: DataHealthIssue, severity: QualitySeverity, detail: str) -> None:
        findings.append(DataHealthFinding(issue, severity, detail))
    missing_links = sum(1 for row in snapshot.rows if not any(ref.startswith("c") for ref in row.lineage) or not any(ref.startswith("v") for ref in row.lineage))
    if missing_links:
        add(DataHealthIssue.MISSING_CODE_WATCH_LINKS, QualitySeverity.WARNING, f"{missing_links} rows lack Code or Watch/verification lineage")
    latest = max((row.observed_at for row in snapshot.rows), default=None)
    if latest is None or (now - latest).total_seconds() > maximum_dataset_age_seconds:
        add(DataHealthIssue.STALE_DATASET, QualitySeverity.WARNING, "dataset has no recent rows within the configured freshness window")
    delayed = sum(1 for row in snapshot.rows if row.label is None and (now - row.observed_at).total_seconds() > maximum_feedback_delay_seconds)
    if delayed:
        add(DataHealthIssue.DELAYED_FEEDBACK, QualitySeverity.WARNING, f"{delayed} rows remain unlabeled after the feedback delay")
    if feature_failures:
        add(DataHealthIssue.FEATURE_GENERATION_FAILURES, QualitySeverity.CRITICAL, f"{feature_failures} feature-generation failures reported")
    if any(item.check == "class_imbalance" for item in quality.findings):
        add(DataHealthIssue.LABEL_IMBALANCE, QualitySeverity.WARNING, "quality report found label imbalance")
    if drift is None or any(not item.sufficient for item in drift.results):
        add(DataHealthIssue.DRIFT, QualitySeverity.WARNING, "drift evidence is missing or insufficient")
    elif drift.drifted_variables:
        add(DataHealthIssue.DRIFT, QualitySeverity.WARNING, f"drifted variables: {list(drift.drifted_variables)}")
    if incomplete_outcome_windows:
        add(DataHealthIssue.INCOMPLETE_OUTCOME_WINDOW, QualitySeverity.WARNING, f"{incomplete_outcome_windows} outcome windows are incomplete")
    findings.sort(key=lambda item: item.issue.value)
    degraded = not quality.passes or bool(findings)
    return DataHealthReport(snapshot.fingerprint, now, tuple(findings), quality, degraded)
