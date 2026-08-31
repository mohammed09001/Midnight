"""Versioned ML preparation projections; no model training or canonical evidence ownership.

The inputs are already-authorized Performance evidence projections.  These
helpers make eligibility, feature timing, and evaluation partitions explicit
before an external trainer is permitted to consume them.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Mapping

from .contracts import ClaimKind
from .data_drift import DriftReport
from .dataset import DatasetRow
from .quality import QualityReport, QualitySeverity


_METHOD = "ml-preparation"
_VERSION = "1"
_POST_RUN_SOURCES = frozenset({"code_change", "execution", "verification", "user_feedback", "watch_outcome"})


class FeatureSource(str, Enum):
    PROMPT_STRUCTURE = "prompt_structure"
    CODE_CHANGE = "code_change"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    USER_FEEDBACK = "user_feedback"
    WATCH_OUTCOME = "watch_outcome"
    HISTORICAL_CONTEXT = "historical_context"
    SIMILARITY = "similarity"


class FeatureAvailability(str, Enum):
    PRE_RUN = "pre_run"
    POST_RUN = "post_run"


class ReadinessStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    source: FeatureSource
    available_at: FeatureAvailability

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("feature names must be non-empty")
        if self.name == "label":
            raise ValueError("labels are targets, never model features")
        if self.source.value in _POST_RUN_SOURCES and self.available_at is not FeatureAvailability.POST_RUN:
            raise ValueError(f"{self.source.value} is inherently post-run and cannot be used for pre-run prediction")


@dataclass(frozen=True, slots=True)
class FeatureInput:
    prompt_run_id: str
    observed_at: datetime
    values: Mapping[FeatureSource, Mapping[str, float | None]]
    label: str | None = None
    label_confidence: float | None = None
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.prompt_run_id.strip() or self.observed_at.tzinfo is None:
            raise ValueError("feature input requires id and timezone-aware observation time")
        if self.label is not None and not self.label.strip():
            raise ValueError("labels must be non-empty when supplied")
        if self.label_confidence is not None and not 0 <= self.label_confidence <= 1:
            raise ValueError("label confidence must be between zero and one")
        if any(not ref.strip() for ref in self.lineage):
            raise ValueError("lineage references must be non-empty")
        for source, values in self.values.items():
            if not isinstance(source, FeatureSource):
                raise ValueError("feature values must use FeatureSource keys")
            for name, value in values.items():
                if not name.strip() or (value is not None and not 0 <= value <= 1):
                    raise ValueError("feature values require non-empty names and zero-one values")


@dataclass(frozen=True, slots=True)
class FeaturePipeline:
    use_case: str
    version: str
    prediction_at: FeatureAvailability
    features: tuple[FeatureSpec, ...]

    def __post_init__(self) -> None:
        if not self.use_case.strip() or not self.version.strip() or not self.features:
            raise ValueError("pipeline requires use case, version, and features")
        names = [item.name for item in self.features]
        if len(names) != len(set(names)):
            raise ValueError("pipeline feature names must be unique")
        if self.prediction_at is FeatureAvailability.PRE_RUN and any(item.available_at is not FeatureAvailability.PRE_RUN for item in self.features):
            raise ValueError("pre-run pipelines cannot include post-run outcome, feedback, change, execution, or verification features")

    def extract(self, inputs: tuple[FeatureInput, ...]) -> tuple[DatasetRow, ...]:
        """Produce deterministic, schema-complete rows from supplied source values only."""
        ids = [item.prompt_run_id for item in inputs]
        if len(ids) != len(set(ids)):
            raise ValueError("feature inputs must have unique prompt run ids")
        rows = []
        for item in sorted(inputs, key=lambda value: (value.observed_at, value.prompt_run_id)):
            values = {spec.name: item.values.get(spec.source, {}).get(spec.name) for spec in self.features}
            rows.append(DatasetRow(item.prompt_run_id, item.observed_at, values, item.label, item.label_confidence, {}, item.lineage))
        return tuple(rows)

    @property
    def fingerprint(self) -> str:
        payload = {"use_case": self.use_case, "version": self.version, "prediction_at": self.prediction_at.value,
                   "features": [(item.name, item.source.value, item.available_at.value) for item in self.features]}
        return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BaselineEvidence:
    metric: str
    score: float
    deterministic: bool
    evaluation_fingerprint: str

    def __post_init__(self) -> None:
        if not self.metric.strip() or not self.evaluation_fingerprint.strip() or not 0 <= self.score <= 1:
            raise ValueError("baseline requires metric, bounded score, and evaluation fingerprint")


@dataclass(frozen=True, slots=True)
class MLReadinessPolicy:
    use_case: str
    version: str
    minimum_rows: int
    minimum_label_confidence: float
    minimum_feature_coverage: float
    minimum_minority_share: float
    minimum_baseline_score: float

    def __post_init__(self) -> None:
        if not self.use_case.strip() or not self.version.strip() or self.minimum_rows < 1:
            raise ValueError("readiness policy requires use case, version, and positive minimum rows")
        for value in (self.minimum_label_confidence, self.minimum_feature_coverage, self.minimum_minority_share, self.minimum_baseline_score):
            if not 0 <= value <= 1:
                raise ValueError("readiness thresholds must be between zero and one")


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    status: ReadinessStatus
    detail: str


@dataclass(frozen=True, slots=True)
class MLReadinessReport:
    policy: MLReadinessPolicy
    checks: tuple[ReadinessCheck, ...]
    method: str = _METHOD
    method_version: str = _VERSION
    claim_kind: ClaimKind = ClaimKind.DERIVED

    @property
    def allowed(self) -> bool:
        return bool(self.checks) and all(item.status is ReadinessStatus.PASS for item in self.checks)


def assess_ml_readiness(policy: MLReadinessPolicy, rows: tuple[DatasetRow, ...], quality: QualityReport, drift: DriftReport | None, baseline: BaselineEvidence | None, *, leakage_controls_passed: bool) -> MLReadinessReport:
    """Gate a use case; missing drift or baseline evidence blocks rather than passing by default."""
    rows = tuple(rows)
    labeled = tuple(row for row in rows if row.label is not None)
    feature_total = len(rows) * len(rows[0].features) if rows else 0
    present = sum(value is not None for row in rows for value in row.features.values())
    coverage = present / feature_total if feature_total else None
    confidences = [row.label_confidence for row in labeled if row.label_confidence is not None]
    label_quality = sum(confidences) / len(labeled) if len(confidences) == len(labeled) and labeled else None
    labels = Counter(row.label for row in labeled)
    minority_share = min(labels.values()) / len(labeled) if len(labels) >= 2 else 0.0
    critical_quality = tuple(item.check for item in quality.findings if item.severity is QualitySeverity.CRITICAL)
    drift_unknown = drift is None or any(not item.sufficient for item in drift.results)
    drifted = bool(drift and drift.drifted_variables)
    checks = (
        ReadinessCheck("dataset_size", ReadinessStatus.PASS if len(rows) >= policy.minimum_rows else ReadinessStatus.FAIL, f"{len(rows)} rows; minimum {policy.minimum_rows}"),
        ReadinessCheck("label_quality", ReadinessStatus.PASS if label_quality is not None and label_quality >= policy.minimum_label_confidence else ReadinessStatus.UNKNOWN if label_quality is None else ReadinessStatus.FAIL, f"mean label confidence={label_quality}; minimum {policy.minimum_label_confidence}"),
        ReadinessCheck("feature_coverage", ReadinessStatus.PASS if coverage is not None and coverage >= policy.minimum_feature_coverage else ReadinessStatus.UNKNOWN if coverage is None else ReadinessStatus.FAIL, f"feature coverage={coverage}; minimum {policy.minimum_feature_coverage}"),
        ReadinessCheck("class_balance", ReadinessStatus.PASS if minority_share >= policy.minimum_minority_share else ReadinessStatus.FAIL, f"minority share={round(minority_share, 3)}; minimum {policy.minimum_minority_share}"),
        ReadinessCheck("quality_controls", ReadinessStatus.PASS if not critical_quality else ReadinessStatus.FAIL, f"critical quality findings: {list(critical_quality)}"),
        ReadinessCheck("leakage_controls", ReadinessStatus.PASS if leakage_controls_passed else ReadinessStatus.FAIL, "partition leakage controls must be explicitly verified"),
        ReadinessCheck("drift_stability", ReadinessStatus.UNKNOWN if drift_unknown else ReadinessStatus.FAIL if drifted else ReadinessStatus.PASS, "drift evidence is missing/insufficient" if drift_unknown else f"drifted variables: {list(drift.drifted_variables)}"),
        ReadinessCheck("deterministic_baseline", ReadinessStatus.UNKNOWN if baseline is None else ReadinessStatus.PASS if baseline.deterministic and baseline.score >= policy.minimum_baseline_score else ReadinessStatus.FAIL, "baseline evidence missing" if baseline is None else f"{baseline.metric}={baseline.score}; minimum {policy.minimum_baseline_score}; deterministic={baseline.deterministic}"),
    )
    return MLReadinessReport(policy, checks)


@dataclass(frozen=True, slots=True)
class SplitExample:
    prompt_run_id: str
    project_id: str
    observed_at: datetime
    lineage_group: str
    similarity_group: str

    def __post_init__(self) -> None:
        if not all((self.prompt_run_id.strip(), self.project_id.strip(), self.lineage_group.strip(), self.similarity_group.strip())) or self.observed_at.tzinfo is None:
            raise ValueError("split examples require ids/groups and timezone-aware observation time")


@dataclass(frozen=True, slots=True)
class PartitionSplit:
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]
    fingerprint: str
    method: str = _METHOD
    method_version: str = _VERSION
    claim_kind: ClaimKind = ClaimKind.DERIVED

    @property
    def holdout(self) -> tuple[str, ...]:
        return self.test


def split_by_time_and_project(examples: tuple[SplitExample, ...], *, train_fraction: float = .6, validation_fraction: float = .2) -> PartitionSplit:
    """Create a frozen temporal split over connected project/lineage/similarity groups.

    Refuses data where indivisible groups overlap temporal partitions, since a
    superficially complete split would then leak future or near-duplicate data.
    """
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 or train_fraction + validation_fraction >= 1:
        raise ValueError("fractions must be positive and leave a test fraction")
    examples = tuple(examples)
    ids = [item.prompt_run_id for item in examples]
    if len(ids) != len(set(ids)) or len(examples) < 3:
        raise ValueError("split requires at least three uniquely identified examples")
    parent = {item.prompt_run_id: item.prompt_run_id for item in examples}
    owner: dict[tuple[str, str], str] = {}
    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value
    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left
    for item in examples:
        for group in (("project", item.project_id), ("lineage", item.lineage_group), ("similarity", item.similarity_group)):
            if group in owner:
                union(item.prompt_run_id, owner[group])
            else:
                owner[group] = item.prompt_run_id
    components: dict[str, list[SplitExample]] = {}
    for item in examples:
        components.setdefault(find(item.prompt_run_id), []).append(item)
    ordered = sorted(components.values(), key=lambda group: (max(item.observed_at for item in group), min(item.prompt_run_id for item in group)))
    if len(ordered) < 3:
        raise ValueError("project/lineage/similarity grouping leaves fewer than three non-leaking groups")
    train_end = max(1, round(len(ordered) * train_fraction))
    validation_end = max(train_end + 1, round(len(ordered) * (train_fraction + validation_fraction)))
    validation_end = min(validation_end, len(ordered) - 1)
    parts = (ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:])
    if any(not part for part in parts):
        raise ValueError("fractions do not produce all three partitions")
    latest_train = max(item.observed_at for group in parts[0] for item in group)
    earliest_validation = min(item.observed_at for group in parts[1] for item in group)
    latest_validation = max(item.observed_at for group in parts[1] for item in group)
    earliest_test = min(item.observed_at for group in parts[2] for item in group)
    if latest_train > earliest_validation or latest_validation > earliest_test:
        raise ValueError("grouped examples overlap temporal partitions; refuse a leaky split")
    values = tuple(tuple(sorted(item.prompt_run_id for group in part for item in group)) for part in parts)
    fingerprint = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return PartitionSplit(*values, fingerprint)
