"""Verified-outcome online learning with bounded, disposable state.

This module is deliberately narrower than the continuous research loop.  It
updates only the two lightweight decisions that already have closed feature
contracts and deterministic fallbacks.  Predictions are never labels, model
state is project-local, and every accepted label is checkpointed atomically
with its idempotency receipt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol

from ..contracts import EntityKind, Identity
from .contracts import LearnedDecisionRecord
from .lightweight_intelligence import (
    FEATURE_SCHEMA_VERSION,
    FETCH_WORTH_IT,
    ROUTING_CONFIDENCE,
    CalibrationReport,
    DeterministicBaseline,
    FeatureVector,
    OnlineLogisticModel,
    ShadowModeGate,
    calibrate,
)


ONLINE_TASKS = frozenset({FETCH_WORTH_IT, ROUTING_CONFIDENCE})
TASK_REWARD_DEFINITIONS = {
    FETCH_WORTH_IT: "true only when the fetched source produced independently verified useful evidence",
    ROUTING_CONFIDENCE: "true only when the selected rung met its quality floor without later escalation or correction",
}


class LabelSource(str, Enum):
    INDEPENDENT_VERIFICATION = "independent_verification"
    PROJECT_OUTCOME = "project_outcome"
    USER_FEEDBACK = "user_feedback"
    REPLAY_BENCHMARK = "replay_benchmark"
    BOUNDED_PROXY = "bounded_proxy"


class Attribution(str, Enum):
    CERTAIN = "certain"
    AMBIGUOUS = "ambiguous"


class ModelStatus(str, Enum):
    COLD_START = "cold_start"
    SHADOW = "shadow"
    PRODUCTION = "production"
    DEGRADED = "degraded"
    STALE = "stale"


class UpdateDisposition(str, Enum):
    UPDATED = "updated"
    DUPLICATE = "duplicate"
    NO_LABEL = "no_label"
    AMBIGUOUS = "ambiguous_attribution"
    INELIGIBLE_SOURCE = "ineligible_label_source"
    DISABLED = "disabled"
    ALREADY_LABELED = "already_labeled"


@dataclass(frozen=True, slots=True)
class VerifiedLabel:
    """A label pointer, not a copy of the canonical outcome or feedback."""

    event_id: str
    project: Identity
    decision_id: str
    value: bool | None
    source: LabelSource
    evidence_ref: str
    occurred_at: datetime
    attribution: Attribution = Attribution.CERTAIN

    def __post_init__(self) -> None:
        if self.project.kind is not EntityKind.PROJECT:
            raise ValueError("online labels require a project identity")
        if not self.event_id.strip() or not self.decision_id.strip() or not self.evidence_ref.strip():
            raise ValueError("label event, decision, and evidence references must not be blank")
        if self.occurred_at.tzinfo is None:
            raise ValueError("label time must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "project": self.project.canonical,
            "decision_id": self.decision_id,
            "value": self.value,
            "source": self.source.value,
            "evidence_ref": self.evidence_ref,
            "occurred_at": self.occurred_at.isoformat(),
            "attribution": self.attribution.value,
        }


@dataclass(frozen=True, slots=True)
class DriftPolicy:
    minimum_window: int = 20
    rolling_window: int = 100
    maximum_calibration_error: float = 0.25
    maximum_reward_shift: float = 0.25
    maximum_feature_mean_shift: float = 0.30
    maximum_cost_latency_ratio: float = 2.0
    maximum_abstention_rate: float = 0.35
    maximum_escalation_rate: float = 0.80

    def __post_init__(self) -> None:
        if self.minimum_window < 2 or self.rolling_window < self.minimum_window:
            raise ValueError("drift windows must be bounded and monotonic")
        if any(value < 0 for value in (
            self.maximum_calibration_error, self.maximum_reward_shift,
            self.maximum_feature_mean_shift, self.maximum_cost_latency_ratio,
            self.maximum_abstention_rate, self.maximum_escalation_rate,
        )):
            raise ValueError("drift thresholds must not be negative")


@dataclass(frozen=True, slots=True)
class OnlineLearningPolicy:
    enabled: bool = True
    allow_proxy_labels: bool = False
    minimum_shadow_samples: int = 20
    minimum_production_samples: int = 200
    maximum_queue_size: int = 100
    drift: DriftPolicy = DriftPolicy()

    def __post_init__(self) -> None:
        if self.minimum_shadow_samples < 1 or self.minimum_production_samples < self.minimum_shadow_samples:
            raise ValueError("sample thresholds must be positive and monotonic")
        if self.maximum_queue_size < 1:
            raise ValueError("maximum queue size must be positive")


@dataclass(frozen=True, slots=True)
class ExplorationPolicy:
    """Deterministic, low-risk eligibility gate; disabled by default.

    The controller does not itself choose a counterfactual action.  A router
    may use this gate only after its normal privacy/security rules and quality
    floors have passed, and must still record the alternative as shadow-only
    unless an explicit future bandit integration owns the final decision.
    """

    enabled: bool = False
    rate: float = 0.01
    daily_budget: int = 5
    maximum_privacy_risk: float = 0.10

    def __post_init__(self) -> None:
        if not 0.0 <= self.rate <= 1.0 or not 0.0 <= self.maximum_privacy_risk <= 1.0:
            raise ValueError("exploration rates and risks must be between zero and one")
        if self.daily_budget < 0:
            raise ValueError("exploration budget must not be negative")

    def allows(self, project: Identity, decision_id: str, *, privacy_risk: float, security_sensitive: bool, used_today: int) -> bool:
        if project.kind is not EntityKind.PROJECT or not decision_id.strip():
            raise ValueError("exploration requires a project and decision id")
        if not 0.0 <= privacy_risk <= 1.0 or used_today < 0:
            raise ValueError("invalid exploration context")
        if not self.enabled or security_sensitive or privacy_risk > self.maximum_privacy_risk or used_today >= self.daily_budget:
            return False
        bucket = int(hashlib.sha256(f"{project.canonical}|{decision_id}".encode()).hexdigest()[:12], 16) / float(0xFFFFFFFFFFFF)
        return bucket < self.rate


@dataclass(frozen=True, slots=True)
class OnlineObservation:
    prediction: float
    label: bool
    features: tuple[tuple[str, float], ...]
    action: str
    cost_micros: int | None
    latency_ms: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction": self.prediction, "label": self.label,
            "features": [list(item) for item in self.features], "action": self.action,
            "cost_micros": self.cost_micros, "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "OnlineObservation":
        return cls(float(raw["prediction"]), bool(raw["label"]), tuple((str(k), float(v)) for k, v in raw["features"]), str(raw["action"]), raw.get("cost_micros"), raw.get("latency_ms"))


@dataclass(frozen=True, slots=True)
class DriftAssessment:
    drifted: bool
    reasons: tuple[str, ...]
    metrics: tuple[tuple[str, float | None], ...]


@dataclass(frozen=True, slots=True)
class ModelCheckpoint:
    project: Identity
    decision_type: str
    feature_schema_version: int
    weights: tuple[float, ...]
    bias: float
    learning_rate: float
    update_count: int
    status: ModelStatus
    production_authority: bool
    observations: tuple[OnlineObservation, ...]
    evidence_refs: tuple[str, ...]
    updated_at: datetime
    drift_reasons: tuple[str, ...] = ()
    checkpoint_hash: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "project": self.project.canonical, "decision_type": self.decision_type,
            "feature_schema_version": self.feature_schema_version,
            "weights": list(self.weights), "bias": self.bias, "learning_rate": self.learning_rate,
            "update_count": self.update_count, "status": self.status.value,
            "production_authority": self.production_authority,
            "observations": [item.to_dict() for item in self.observations],
            "evidence_refs": list(self.evidence_refs), "updated_at": self.updated_at.isoformat(),
            "drift_reasons": list(self.drift_reasons),
        }

    @staticmethod
    def digest(payload: Mapping[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.payload()
        payload["checkpoint_hash"] = self.checkpoint_hash or self.digest(payload)
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ModelCheckpoint":
        payload = dict(raw)
        claimed = str(payload.pop("checkpoint_hash", ""))
        if not claimed or claimed != cls.digest(payload):
            raise ValueError("online-learning checkpoint hash mismatch")
        checkpoint = cls(
            project=Identity.parse(str(payload["project"])), decision_type=str(payload["decision_type"]),
            feature_schema_version=int(payload["feature_schema_version"]),
            weights=tuple(float(v) for v in payload["weights"]), bias=float(payload["bias"]),
            learning_rate=float(payload["learning_rate"]), update_count=int(payload["update_count"]),
            status=ModelStatus(str(payload["status"])), production_authority=bool(payload["production_authority"]),
            observations=tuple(OnlineObservation.from_dict(v) for v in payload["observations"]),
            evidence_refs=tuple(str(v) for v in payload["evidence_refs"]),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
            drift_reasons=tuple(str(v) for v in payload.get("drift_reasons", ())), checkpoint_hash=claimed,
        )
        if checkpoint.decision_type not in ONLINE_TASKS or checkpoint.feature_schema_version != FEATURE_SCHEMA_VERSION:
            raise ValueError("unsupported online-learning checkpoint schema")
        return checkpoint

    def model(self) -> OnlineLogisticModel:
        initial = OnlineLogisticModel.initial(self.decision_type, learning_rate=self.learning_rate)
        return replace(initial, weights=self.weights, bias=self.bias, version=str(self.update_count))


@dataclass(frozen=True, slots=True)
class OnlineUpdateResult:
    disposition: UpdateDisposition
    checkpoint: ModelCheckpoint | None
    drift: DriftAssessment | None
    reason: str


class OnlineLearningStore(Protocol):
    def get_learned_decision(self, project: Identity, identity: str) -> LearnedDecisionRecord | None: ...
    def load_online_checkpoint(self, project: Identity, decision_type: str) -> ModelCheckpoint | None: ...
    def online_event_exists(self, project: Identity, event_id: str) -> bool: ...
    def record_online_no_update(self, label: VerifiedLabel, disposition: UpdateDisposition) -> bool: ...
    def apply_online_update(self, label: VerifiedLabel, decision: LearnedDecisionRecord, checkpoint: ModelCheckpoint) -> bool: ...
    def save_online_checkpoint(self, checkpoint: ModelCheckpoint) -> None: ...


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def detect_online_drift(observations: tuple[OnlineObservation, ...], policy: DriftPolicy) -> DriftAssessment:
    """Lightweight rolling drift signals; unavailable measures remain explicit."""
    metrics: dict[str, float | None] = {
        "calibration_error": None, "reward_shift": None, "feature_distribution_shift": None,
        "latency_ratio": None, "cost_ratio": None, "task_distribution_shift": None,
        "abstention_rate": None, "escalation_rate": None,
    }
    reasons: list[str] = []
    if len(observations) < policy.minimum_window:
        return DriftAssessment(False, (), tuple(metrics.items()))
    window = observations[-policy.rolling_window:]
    metrics["calibration_error"] = _mean([abs(item.prediction - float(item.label)) for item in window])
    half = max(1, len(window) // 2)
    before, current = window[:half], window[half:]
    metrics["reward_shift"] = abs((_mean([float(v.label) for v in before]) or 0.0) - (_mean([float(v.label) for v in current]) or 0.0))
    feature_shifts = []
    for name, _ in window[0].features:
        left = _mean([dict(item.features)[name] for item in before])
        right = _mean([dict(item.features)[name] for item in current])
        if left is not None and right is not None:
            feature_shifts.append(abs(left - right))
    metrics["feature_distribution_shift"] = max(feature_shifts, default=0.0)
    for field, metric in (("latency_ms", "latency_ratio"), ("cost_micros", "cost_ratio")):
        left = _mean([float(getattr(item, field)) for item in before if getattr(item, field) is not None])
        right = _mean([float(getattr(item, field)) for item in current if getattr(item, field) is not None])
        if left is not None and right is not None:
            metrics[metric] = right / max(1.0, left)
    metrics["escalation_rate"] = sum(item.action in {"skip", "escalate"} for item in window) / len(window)
    metrics["abstention_rate"] = sum(abs(item.prediction - 0.5) < 0.1 for item in window) / len(window)
    checks = (
        ("calibration", metrics["calibration_error"], policy.maximum_calibration_error),
        ("reward", metrics["reward_shift"], policy.maximum_reward_shift),
        ("feature_distribution", metrics["feature_distribution_shift"], policy.maximum_feature_mean_shift),
        ("latency", metrics["latency_ratio"], policy.maximum_cost_latency_ratio),
        ("cost", metrics["cost_ratio"], policy.maximum_cost_latency_ratio),
        ("escalation", metrics["escalation_rate"], policy.maximum_escalation_rate),
        ("abstention", metrics["abstention_rate"], policy.maximum_abstention_rate),
    )
    for name, value, threshold in checks:
        if value is not None and value > threshold:
            reasons.append(f"{name}_drift")
    return DriftAssessment(bool(reasons), tuple(reasons), tuple(metrics.items()))


class OnlineLearningController:
    """Immediate-checkpoint controller: no uncontrolled background worker."""

    def __init__(self, project: Identity, store: OnlineLearningStore, *, policy: OnlineLearningPolicy = OnlineLearningPolicy()) -> None:
        if project.kind is not EntityKind.PROJECT:
            raise ValueError("online learning requires a project")
        self.project, self.store, self.policy = project, store, policy

    def _same_project(self, project: Identity) -> None:
        if project != self.project:
            raise PermissionError("cross-project online learning denied")

    def process(self, label: VerifiedLabel) -> OnlineUpdateResult:
        self._same_project(label.project)
        if self.store.online_event_exists(self.project, label.event_id):
            return OnlineUpdateResult(UpdateDisposition.DUPLICATE, None, None, "event was already applied")
        if not self.policy.enabled:
            self.store.record_online_no_update(label, UpdateDisposition.DISABLED)
            return OnlineUpdateResult(UpdateDisposition.DISABLED, None, None, "project opted out")
        if label.value is None:
            self.store.record_online_no_update(label, UpdateDisposition.NO_LABEL)
            return OnlineUpdateResult(UpdateDisposition.NO_LABEL, None, None, "no legitimate label")
        if label.attribution is Attribution.AMBIGUOUS:
            self.store.record_online_no_update(label, UpdateDisposition.AMBIGUOUS)
            return OnlineUpdateResult(UpdateDisposition.AMBIGUOUS, None, None, "outcome attribution is ambiguous")
        if label.source is LabelSource.BOUNDED_PROXY and not self.policy.allow_proxy_labels:
            self.store.record_online_no_update(label, UpdateDisposition.INELIGIBLE_SOURCE)
            return OnlineUpdateResult(UpdateDisposition.INELIGIBLE_SOURCE, None, None, "proxy labels are disabled")
        decision = self.store.get_learned_decision(self.project, label.decision_id)
        if decision is None:
            raise KeyError(f"unknown project-scoped learned decision: {label.decision_id}")
        if decision.project != self.project:
            raise PermissionError("cross-project learned decision denied")
        if decision.decision_type not in ONLINE_TASKS:
            raise ValueError("decision type is intentionally excluded from online learning")
        if decision.outcome_label is not None:
            self.store.record_online_no_update(label, UpdateDisposition.ALREADY_LABELED)
            return OnlineUpdateResult(UpdateDisposition.ALREADY_LABELED, None, None, "decision already has a legitimate label")

        current = self.store.load_online_checkpoint(self.project, decision.decision_type)
        model = current.model() if current is not None else OnlineLogisticModel.initial(decision.decision_type)
        features = FeatureVector(decision.decision_type, decision.feature_schema_version, decision.features)
        updated = model.partial_fit(features, bool(label.value))
        observations = (() if current is None else current.observations) + (
            OnlineObservation(decision.prediction, bool(label.value), decision.features, decision.action_chosen, decision.cost_micros, decision.latency_ms),
        )
        observations = observations[-self.policy.drift.rolling_window:]
        drift = detect_online_drift(observations, self.policy.drift)
        update_count = (current.update_count if current else 0) + 1
        status = ModelStatus.DEGRADED if drift.drifted else (ModelStatus.SHADOW if update_count >= self.policy.minimum_shadow_samples else ModelStatus.COLD_START)
        authority = bool(current and current.production_authority and not drift.drifted)
        checkpoint = ModelCheckpoint(
            self.project, decision.decision_type, FEATURE_SCHEMA_VERSION, updated.weights, updated.bias,
            updated.learning_rate, update_count, status if not authority else ModelStatus.PRODUCTION, authority,
            observations, ((current.evidence_refs if current else ()) + (label.evidence_ref,))[-self.policy.drift.rolling_window:],
            label.occurred_at, drift.reasons,
        )
        checkpoint = replace(checkpoint, checkpoint_hash=ModelCheckpoint.digest(checkpoint.payload()))
        if not self.store.apply_online_update(label, decision, checkpoint):
            return OnlineUpdateResult(UpdateDisposition.DUPLICATE, None, None, "event won an idempotency race")
        return OnlineUpdateResult(UpdateDisposition.UPDATED, checkpoint, drift, "verified label applied exactly once")

    def gate(self, decision_type: str, *, baseline_threshold: float) -> ShadowModeGate:
        """Corrupt/deleted/missing state naturally returns the deterministic gate."""
        if decision_type not in ONLINE_TASKS:
            raise ValueError("decision type is not eligible for online learning")
        checkpoint = self.store.load_online_checkpoint(self.project, decision_type)
        if checkpoint is None or checkpoint.status in {ModelStatus.DEGRADED, ModelStatus.STALE}:
            return ShadowModeGate(decision_type, DeterministicBaseline(decision_type), baseline_threshold)
        calibration: CalibrationReport | None = calibrate(
            checkpoint.model(), tuple((FeatureVector(decision_type, FEATURE_SCHEMA_VERSION, item.features), item.label) for item in checkpoint.observations)
        ) if checkpoint.observations else None
        production_min = self.policy.minimum_production_samples if checkpoint.production_authority else checkpoint.update_count + 1
        return ShadowModeGate(
            decision_type, DeterministicBaseline(decision_type), baseline_threshold,
            model=checkpoint.model(), sample_count=checkpoint.update_count, calibration=calibration,
            min_samples_for_shadow=self.policy.minimum_shadow_samples,
            min_samples_for_production=production_min,
        )

    def enable_production_authority(self, decision_type: str, *, now: datetime) -> ModelCheckpoint:
        """Explicitly grant authority only after sample, calibration, and drift gates."""
        if now.tzinfo is None:
            raise ValueError("promotion time must be timezone-aware")
        checkpoint = self.store.load_online_checkpoint(self.project, decision_type)
        if checkpoint is None:
            raise RuntimeError("no learned checkpoint is available")
        if checkpoint.status in {ModelStatus.DEGRADED, ModelStatus.STALE} or checkpoint.drift_reasons:
            raise RuntimeError("a degraded or stale model cannot be promoted")
        if checkpoint.update_count < self.policy.minimum_production_samples:
            raise RuntimeError("minimum production sample threshold has not been met")
        examples = tuple(
            (FeatureVector(decision_type, FEATURE_SCHEMA_VERSION, item.features), item.label)
            for item in checkpoint.observations
        )
        report = calibrate(checkpoint.model(), examples)
        if report.expected_calibration_error > self.policy.drift.maximum_calibration_error:
            raise RuntimeError("calibration threshold has not been met")
        promoted = replace(checkpoint, status=ModelStatus.PRODUCTION, production_authority=True, updated_at=now, checkpoint_hash="")
        promoted = replace(promoted, checkpoint_hash=ModelCheckpoint.digest(promoted.payload()))
        self.store.save_online_checkpoint(promoted)
        return promoted


__all__ = [
    "ONLINE_TASKS", "TASK_REWARD_DEFINITIONS", "Attribution", "DriftAssessment", "DriftPolicy", "ExplorationPolicy", "LabelSource",
    "ModelCheckpoint", "ModelStatus", "OnlineLearningController", "OnlineLearningPolicy",
    "OnlineObservation", "OnlineUpdateResult", "UpdateDisposition", "VerifiedLabel",
    "detect_online_drift",
]
