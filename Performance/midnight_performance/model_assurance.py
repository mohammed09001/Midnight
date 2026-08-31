"""Calibration, uncertainty, explainability, and Watch-regression risk projections."""
from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt

from .contracts import ClaimKind
from .dataset import DatasetRow
from .learning_models import BinaryModel, ModelKind, _stump, fit_logistic
from .ml import FeatureAvailability, FeaturePipeline, MLReadinessReport

_METHOD = "model-assurance"
_VERSION = "1"


def _ready(report: MLReadinessReport) -> None:
    if not report.allowed: raise PermissionError("ML readiness gate did not allow training")


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float; upper: float; count: int; predicted_mean: float | None; observed_rate: float | None


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrator:
    positive_label: str; bins: tuple[CalibrationBin, ...]; source_model: ModelKind

    def calibrate(self, probability: float) -> float | None:
        for item in self.bins:
            if item.lower <= probability < item.upper or (item.upper == 1 and probability == 1):
                if item.observed_rate is not None:
                    return item.observed_rate
        return None


@dataclass(frozen=True, slots=True)
class ModelQuality:
    brier_score: float; log_loss: float; precision: float | None; recall: float | None
    calibration: tuple[CalibrationBin, ...]; method: str = _METHOD; method_version: str = _VERSION
    claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "metrics cover only the supplied held-out calibration rows"


def calibrate_model(model: BinaryModel, rows: tuple[DatasetRow, ...], *, bins: int = 5) -> tuple[ProbabilityCalibrator, ModelQuality]:
    """Measure held-out calibration and make a binned empirical calibrator; absent bins stay unknown."""
    if bins < 2 or not rows or any(row.label is None for row in rows): raise ValueError("calibration requires labeled rows and at least two bins")
    values = [(model.probability(row), int(row.label == model.positive_label)) for row in rows]
    grouped = [[] for _ in range(bins)]
    for probability, target in values: grouped[min(bins - 1, int(probability * bins))].append((probability, target))
    calibration = tuple(CalibrationBin(index / bins, (index + 1) / bins, len(group), round(sum(x for x, _ in group) / len(group), 3) if group else None, round(sum(y for _, y in group) / len(group), 3) if group else None) for index, group in enumerate(grouped))
    probabilities, targets = zip(*values)
    brier = sum((p - y) ** 2 for p, y in values) / len(values)
    log_loss = -sum(y * log(max(p, 1e-12)) + (1 - y) * log(max(1 - p, 1e-12)) for p, y in values) / len(values)
    predicted = [p >= .5 for p in probabilities]
    true_positive = sum(p and bool(y) for p, y in zip(predicted, targets)); false_positive = sum(p and not y for p, y in zip(predicted, targets)); false_negative = sum(not p and bool(y) for p, y in zip(predicted, targets))
    quality = ModelQuality(round(brier, 3), round(log_loss, 3), round(true_positive / (true_positive + false_positive), 3) if true_positive + false_positive else None, round(true_positive / (true_positive + false_negative), 3) if true_positive + false_negative else None, calibration)
    return ProbabilityCalibrator(model.positive_label, calibration, model.kind), quality


@dataclass(frozen=True, slots=True)
class FeatureContribution:
    feature: str; value: float; contribution: float


@dataclass(frozen=True, slots=True)
class LocalExplanation:
    prompt_run_id: str; model: ModelKind; intercept: float | None; contributions: tuple[FeatureContribution, ...]
    claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "contributions describe this model's calculation, not causal effect or repository truth"


def explain_prediction(model: BinaryModel, row: DatasetRow) -> LocalExplanation:
    """Return exact local terms for supported interpretable models; never a score without its signals."""
    if model.kind is ModelKind.LOGISTIC:
        contributions = tuple(sorted((FeatureContribution(name, float(row.features.get(name) or 0), round(weight * float(row.features.get(name) or 0), 6)) for name, weight in zip(model.feature_names, model.parameters[1:])), key=lambda item: (-abs(item.contribution), item.feature)))
        return LocalExplanation(row.prompt_run_id, model.kind, model.parameters[0], contributions)
    if model.kind is ModelKind.STUMP:
        index, cut, _, _ = model.parameters; name = model.feature_names[int(index)]; value = float(row.features.get(name) or 0)
        return LocalExplanation(row.prompt_run_id, model.kind, None, (FeatureContribution(name, value, 1.0 if value >= cut else -1.0),))
    return LocalExplanation(row.prompt_run_id, model.kind, None, ())


@dataclass(frozen=True, slots=True)
class RiskEstimate:
    prompt_run_id: str; probability: float | None; interval: tuple[float, float] | None; abstained: bool; explanation: LocalExplanation
    claim_kind: ClaimKind = ClaimKind.PREDICTED
    uncertainty: str = "risk is a calibrated historical association with later Watch regression labels, not a causal or verified regression claim"


def _interval(probability: float, n: int) -> tuple[float, float]:
    margin = 1.96 * sqrt(max(0.0, probability * (1 - probability) / max(1, n)))
    return round(max(0.0, probability - margin), 3), round(min(1.0, probability + margin), 3)


@dataclass(frozen=True, slots=True)
class RegressionRiskReport:
    model: BinaryModel; calibrator: ProbabilityCalibrator; quality: ModelQuality; baseline_quality: tuple[ModelQuality, ...]; estimates: tuple[RiskEstimate, ...]
    method: str = _METHOD; method_version: str = _VERSION; claim_kind: ClaimKind = ClaimKind.PREDICTED


def estimate_regression_risk(readiness: MLReadinessReport, pipeline: FeaturePipeline, train: tuple[DatasetRow, ...], calibration: tuple[DatasetRow, ...], candidates: tuple[DatasetRow, ...], *, regression_label: str, minimum_confidence: float = .6, change_size_feature: str, verification_feature: str) -> RegressionRiskReport:
    """Fit a pre-run model for later Watch labels, calibrate it, compare two simple feature baselines, and abstain when confidence is inadequate."""
    _ready(readiness)
    if pipeline.prediction_at is not FeatureAvailability.PRE_RUN: raise ValueError("regression-risk estimation requires a pre-run feature pipeline")
    if not 0 <= minimum_confidence <= 1: raise ValueError("minimum confidence must be between zero and one")
    schema = {item.name for item in pipeline.features}
    if not train or any(set(row.features) != schema for row in (*train, *calibration, *candidates)):
        raise ValueError("risk rows must exactly match the pre-run pipeline feature schema")
    if change_size_feature not in train[0].features or verification_feature not in train[0].features: raise ValueError("declared baseline features must exist in training schema")
    model = fit_logistic(train, regression_label)
    calibrator, quality = calibrate_model(model, calibration)
    baselines = []
    for feature in (change_size_feature, verification_feature):
        reduced = tuple(DatasetRow(row.prompt_run_id, row.observed_at, {feature: row.features[feature]}, row.label, row.label_confidence, row.agent_metadata, row.lineage) for row in train)
        reduced_calibration = tuple(DatasetRow(row.prompt_run_id, row.observed_at, {feature: row.features[feature]}, row.label, row.label_confidence, row.agent_metadata, row.lineage) for row in calibration)
        _, baseline = calibrate_model(_stump(reduced, regression_label), reduced_calibration)
        baselines.append(baseline)
    estimates = []
    for row in candidates:
        raw = model.probability(row); calibrated = calibrator.calibrate(raw)
        confidence = max(raw, 1 - raw)
        abstained = calibrated is None or confidence < minimum_confidence
        estimates.append(RiskEstimate(row.prompt_run_id, None if abstained else calibrated, None if abstained else _interval(calibrated, len(calibration)), abstained, explain_prediction(model, row)))
    return RegressionRiskReport(model, calibrator, quality, tuple(baselines), tuple(estimates))
