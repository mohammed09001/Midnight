"""Immutable model lineage registry and monitoring projections; no model serving or evidence ownership."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Mapping

from .contracts import ClaimKind
from .data_drift import DriftReport, detect_drift
from .dataset import DatasetRow
from .learning_models import BinaryModel
from .model_assurance import ModelQuality, calibrate_model

_METHOD = "model-registry-monitoring"
_VERSION = "1"


class ApprovalState(str, Enum):
    PENDING = "pending"; APPROVED = "approved"; REJECTED = "rejected"


class DeploymentState(str, Enum):
    NOT_DEPLOYED = "not_deployed"; DEPLOYED = "deployed"; DEGRADED = "degraded"; RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class ModelRegistration:
    model_id: str; version: str; dataset_fingerprint: str; feature_schema: tuple[str, ...]; code_version: str
    hyperparameters: Mapping[str, str | float | int]; metrics: Mapping[str, float]; calibration: ModelQuality | None
    trained_at: datetime; approval: ApprovalState = ApprovalState.PENDING; deployment: DeploymentState = DeploymentState.NOT_DEPLOYED
    parent_version: str | None = None; rollback_target: str | None = None

    def __post_init__(self) -> None:
        if not all((self.model_id.strip(), self.version.strip(), self.dataset_fingerprint.strip(), self.code_version.strip())) or not self.feature_schema:
            raise ValueError("registration requires identity, dataset, feature schema, and code version")
        if self.trained_at.tzinfo is None or any(not name.strip() for name in self.feature_schema): raise ValueError("registration requires timezone-aware time and named features")
        if any(not 0 <= value <= 1 for value in self.metrics.values()): raise ValueError("registered metrics must be zero-one values")
        if self.deployment is DeploymentState.DEPLOYED and self.approval is not ApprovalState.APPROVED: raise ValueError("only approved models may deploy")


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    records: tuple[ModelRegistration, ...] = ()

    def add(self, record: ModelRegistration) -> "ModelRegistry":
        keys = {(item.model_id, item.version) for item in self.records}
        if (record.model_id, record.version) in keys: raise ValueError("model version already registered")
        versions = {item.version for item in self.records if item.model_id == record.model_id}
        if record.parent_version and record.parent_version not in versions: raise ValueError("parent version is not registered")
        if record.rollback_target and record.rollback_target not in versions: raise ValueError("rollback target is not registered")
        return ModelRegistry(self.records + (record,))

    def version(self, model_id: str, version: str) -> ModelRegistration | None:
        return next((item for item in self.records if item.model_id == model_id and item.version == version), None)


def set_approval(registry: ModelRegistry, model_id: str, version: str, approval: ApprovalState) -> ModelRegistry:
    record = registry.version(model_id, version)
    if record is None: raise KeyError("unknown model version")
    if record.deployment is DeploymentState.DEPLOYED and approval is not ApprovalState.APPROVED: raise ValueError("deployed model approval cannot be revoked without rollback")
    return ModelRegistry(tuple(replace(item, approval=approval) if item == record else item for item in registry.records))


def deploy(registry: ModelRegistry, model_id: str, version: str) -> ModelRegistry:
    record = registry.version(model_id, version)
    if record is None: raise KeyError("unknown model version")
    if record.approval is not ApprovalState.APPROVED: raise PermissionError("unapproved model cannot deploy")
    return ModelRegistry(tuple(replace(item, deployment=DeploymentState.DEPLOYED) if item == record else item for item in registry.records))


@dataclass(frozen=True, slots=True)
class MonitoringPolicy:
    max_model_age_days: int; max_brier_increase: float; minimum_cohort_size: int = 2
    def __post_init__(self) -> None:
        if self.max_model_age_days < 1 or self.max_brier_increase < 0 or self.minimum_cohort_size < 1: raise ValueError("monitoring thresholds must be valid")


@dataclass(frozen=True, slots=True)
class CohortPerformance:
    cohort: str; count: int; brier_score: float | None


@dataclass(frozen=True, slots=True)
class ModelMonitoringReport:
    model_id: str; version: str; drift: DriftReport; calibration_degraded: bool; stale: bool; cohorts: tuple[CohortPerformance, ...]
    degraded: bool; reasons: tuple[str, ...]; method: str = _METHOD; method_version: str = _VERSION; claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "monitoring signals describe whether model assumptions remain supported by supplied observations; they do not verify runtime or Watch outcomes"


def monitor_model(record: ModelRegistration, model: BinaryModel, reference: tuple[DatasetRow, ...], current: tuple[DatasetRow, ...], *, now: datetime, policy: MonitoringPolicy, cohort_key: str = "project") -> ModelMonitoringReport:
    """Combine feature/label drift, held-out calibration degradation, cohort Brier scores, and model age."""
    if now.tzinfo is None: raise ValueError("monitoring time must be timezone-aware")
    features = record.feature_schema
    if any(set(row.features) != set(features) for row in (*reference, *current)): raise ValueError("monitoring rows must match the registered feature schema")
    drift = detect_drift(reference, current, numeric=features, include_label=True, min_reference=1, min_current=1)
    current_quality = calibrate_model(model, current, bins=2)[1] if current and all(row.label is not None for row in current) else None
    calibration_degraded = record.calibration is None or current_quality is None or current_quality.brier_score - record.calibration.brier_score > policy.max_brier_increase
    stale = (now - record.trained_at).days > policy.max_model_age_days
    groups: dict[str, list[DatasetRow]] = {}
    for row in current: groups.setdefault(row.agent_metadata.get(cohort_key, "unknown"), []).append(row)
    cohorts = []
    for name, rows in sorted(groups.items()):
        quality = calibrate_model(model, tuple(rows), bins=2)[1] if len(rows) >= policy.minimum_cohort_size and all(row.label is not None for row in rows) else None
        cohorts.append(CohortPerformance(name, len(rows), quality.brier_score if quality else None))
    reasons = []
    if drift.drifted_variables: reasons.append(f"drift: {list(drift.drifted_variables)}")
    if calibration_degraded: reasons.append("calibration degraded or unavailable")
    if stale: reasons.append("model is stale")
    return ModelMonitoringReport(record.model_id, record.version, drift, calibration_degraded, stale, tuple(cohorts), bool(reasons), tuple(reasons))


def apply_monitoring(registry: ModelRegistry, report: ModelMonitoringReport) -> ModelRegistry:
    """Mark only the matching deployed registry record degraded when the monitor signals unsupported assumptions."""
    record = registry.version(report.model_id, report.version)
    if record is None: raise KeyError("unknown model version")
    if not report.degraded or record.deployment is not DeploymentState.DEPLOYED: return registry
    return ModelRegistry(tuple(replace(item, deployment=DeploymentState.DEGRADED) if item == record else item for item in registry.records))
