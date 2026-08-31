"""Readiness-gated, reproducible learning projections; never causal or canonical truth."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import exp, sqrt
from typing import Mapping

from .contracts import ClaimKind
from .dataset import DatasetRow
from .ml import MLReadinessReport

_METHOD = "classical-learning-projections"
_VERSION = "1"


class ModelKind(str, Enum):
    MAJORITY = "deterministic_majority"
    CALIBRATED_FREQUENCY = "calibrated_frequency"
    LOGISTIC = "regularized_logistic"
    STUMP = "decision_stump"
    NEAREST_NEIGHBOR = "nearest_neighbor"


@dataclass(frozen=True, slots=True)
class BinaryModel:
    kind: ModelKind
    feature_names: tuple[str, ...]
    positive_label: str
    parameters: tuple[float, ...]
    threshold: float = .5

    def probability(self, row: DatasetRow) -> float:
        values = tuple(float(row.features.get(name) or 0.0) for name in self.feature_names)
        if self.kind in {ModelKind.MAJORITY, ModelKind.CALIBRATED_FREQUENCY}:
            return self.parameters[0]
        if self.kind is ModelKind.LOGISTIC:
            score = self.parameters[0] + sum(weight * value for weight, value in zip(self.parameters[1:], values))
            return round(1 / (1 + exp(-max(-30.0, min(30.0, score)))), 6)
        if self.kind is ModelKind.STUMP:
            index, cut, below, above = self.parameters
            return above if values[int(index)] >= cut else below
        raise ValueError("nearest-neighbor models require reference rows and are evaluated directly")


@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    kind: ModelKind
    accuracy: float
    brier_score: float
    method: str = _METHOD
    method_version: str = _VERSION
    claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "evaluation is limited to supplied held-out rows; it does not establish production usefulness or causation"


def _require_ready(readiness: MLReadinessReport) -> None:
    if not readiness.allowed:
        raise PermissionError("ML readiness gate did not allow training")


def _schema(rows: tuple[DatasetRow, ...]) -> tuple[str, ...]:
    if not rows:
        raise ValueError("training requires rows")
    names = tuple(sorted(rows[0].features))
    if not names or any(tuple(sorted(row.features)) != names for row in rows):
        raise ValueError("training rows require one non-empty, consistent feature schema")
    return names


def _labels(rows: tuple[DatasetRow, ...], positive: str) -> tuple[int, ...]:
    if not positive.strip() or any(row.label is None for row in rows):
        raise ValueError("training rows and positive label must be labeled")
    return tuple(int(row.label == positive) for row in rows)


def fit_logistic(rows: tuple[DatasetRow, ...], positive_label: str, *, iterations: int = 300, learning_rate: float = .3, l2: float = .01) -> BinaryModel:
    """Deterministic, regularized binary logistic baseline over zero-imputed features."""
    names, targets = _schema(rows), _labels(rows, positive_label)
    if len(set(targets)) < 2:
        raise ValueError("logistic training requires both positive and negative labels")
    weights = [0.0] * (len(names) + 1)
    matrix = [tuple(float(row.features[name] or 0.0) for name in names) for row in rows]
    for _ in range(iterations):
        gradients = [0.0] * len(weights)
        for values, target in zip(matrix, targets):
            probability = 1 / (1 + exp(-max(-30.0, min(30.0, weights[0] + sum(w * x for w, x in zip(weights[1:], values))))))
            error = probability - target
            gradients[0] += error
            for index, value in enumerate(values, start=1): gradients[index] += error * value
        for index in range(len(weights)):
            regularizer = l2 * weights[index] if index else 0.0
            weights[index] -= learning_rate * (gradients[index] / len(rows) + regularizer)
    return BinaryModel(ModelKind.LOGISTIC, names, positive_label, tuple(round(value, 8) for value in weights))


def _majority(rows: tuple[DatasetRow, ...], positive: str) -> BinaryModel:
    names, targets = _schema(rows), _labels(rows, positive)
    return BinaryModel(ModelKind.MAJORITY, names, positive, (sum(targets) / len(targets),))


def _calibrated_frequency(rows: tuple[DatasetRow, ...], positive: str) -> BinaryModel:
    """The observed held-in class frequency is a transparent calibrated-probability reference."""
    names, targets = _schema(rows), _labels(rows, positive)
    return BinaryModel(ModelKind.CALIBRATED_FREQUENCY, names, positive, (sum(targets) / len(targets),))


def _stump(rows: tuple[DatasetRow, ...], positive: str) -> BinaryModel:
    names, targets = _schema(rows), _labels(rows, positive)
    best = None
    for index, name in enumerate(names):
        values = sorted({float(row.features[name] or 0.0) for row in rows})
        for cut in values:
            below = [target for row, target in zip(rows, targets) if float(row.features[name] or 0.0) < cut]
            above = [target for row, target in zip(rows, targets) if float(row.features[name] or 0.0) >= cut]
            if not below or not above: continue
            probs = (sum(below) / len(below), sum(above) / len(above))
            error = sum((target - (probs[1] if float(row.features[name] or 0.0) >= cut else probs[0])) ** 2 for row, target in zip(rows, targets))
            candidate = (error, index, cut, *probs)
            if best is None or candidate < best: best = candidate
    if best is None: return _majority(rows, positive)
    _, index, cut, below, above = best
    return BinaryModel(ModelKind.STUMP, names, positive, (float(index), cut, below, above))


def _knn_probability(train: tuple[DatasetRow, ...], row: DatasetRow, names: tuple[str, ...], positive: str, k: int = 3) -> float:
    distances = []
    for candidate in train:
        distance = sqrt(sum((float(candidate.features[name] or 0.0) - float(row.features[name] or 0.0)) ** 2 for name in names))
        distances.append((distance, candidate.prompt_run_id, int(candidate.label == positive)))
    nearest = sorted(distances)[:min(k, len(distances))]
    return sum(item[2] for item in nearest) / len(nearest)


def _evaluate(model: BinaryModel, train: tuple[DatasetRow, ...], test: tuple[DatasetRow, ...]) -> ModelEvaluation:
    if not test: raise ValueError("evaluation requires held-out rows")
    targets = _labels(test, model.positive_label)
    probabilities = [_knn_probability(train, row, model.feature_names, model.positive_label) if model.kind is ModelKind.NEAREST_NEIGHBOR else model.probability(row) for row in test]
    accuracy = sum((probability >= .5) == bool(target) for probability, target in zip(probabilities, targets)) / len(test)
    brier = sum((probability - target) ** 2 for probability, target in zip(probabilities, targets)) / len(test)
    return ModelEvaluation(model.kind, round(accuracy, 3), round(brier, 3))


def evaluate_classical_baselines(readiness: MLReadinessReport, train: tuple[DatasetRow, ...], test: tuple[DatasetRow, ...], *, positive_label: str) -> tuple[ModelEvaluation, ...]:
    """Evaluate deterministic, logistic, stump, and nearest-neighbor baselines only after readiness passes."""
    _require_ready(readiness)
    models = (_majority(train, positive_label), _calibrated_frequency(train, positive_label), fit_logistic(train, positive_label), _stump(train, positive_label), BinaryModel(ModelKind.NEAREST_NEIGHBOR, _schema(train), positive_label, ()))
    return tuple(_evaluate(model, train, test) for model in models)


@dataclass(frozen=True, slots=True)
class Cluster:
    cluster_id: int
    members: tuple[str, ...]
    centroid: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ClusterReport:
    feature_names: tuple[str, ...]
    clusters: tuple[Cluster, ...]
    stability: float
    surfaced: bool
    method: str = _METHOD
    method_version: str = _VERSION
    claim_kind: ClaimKind = ClaimKind.INFERRED
    uncertainty: str = "clusters are exploratory patterns, not taxonomy or causal concepts; surfacing requires stability and human interpretation"


def _kmeans(rows: tuple[DatasetRow, ...], names: tuple[str, ...], k: int, offset: int) -> tuple[int, ...]:
    points = [tuple(float(row.features[name] or 0.0) for name in names) for row in rows]
    centroids = [points[(index + offset) % len(points)] for index in range(k)]
    assignments = [0] * len(points)
    for _ in range(50):
        new = [min(range(k), key=lambda group: (sum((value - center) ** 2 for value, center in zip(point, centroids[group])), group)) for point in points]
        if new == assignments: break
        assignments = new
        for group in range(k):
            members = [point for point, assigned in zip(points, assignments) if assigned == group]
            if members: centroids[group] = tuple(sum(point[index] for point in members) / len(members) for index in range(len(names)))
    return tuple(assignments)


def cluster_experiences(rows: tuple[DatasetRow, ...], *, k: int, interpretations: Mapping[int, str] | None = None, minimum_stability: float = .8) -> ClusterReport:
    """Deterministic k-means with a second initialization for co-assignment stability."""
    names = _schema(rows)
    if not 2 <= k <= len(rows) or not 0 <= minimum_stability <= 1:
        raise ValueError("k must be between two and row count; stability must be bounded")
    ordered = tuple(sorted(rows, key=lambda row: row.prompt_run_id))
    first, second = _kmeans(ordered, names, k, 0), _kmeans(ordered, names, k, 1)
    pairs = [(left, right) for left in range(len(ordered)) for right in range(left + 1, len(ordered))]
    stability = 1.0 if not pairs else sum((first[a] == first[b]) == (second[a] == second[b]) for a, b in pairs) / len(pairs)
    clusters = []
    for group in range(k):
        members = tuple(row.prompt_run_id for row, assigned in zip(ordered, first) if assigned == group)
        if not members: continue
        vectors = [tuple(float(row.features[name] or 0.0) for name in names) for row, assigned in zip(ordered, first) if assigned == group]
        clusters.append(Cluster(group, members, tuple(round(sum(vector[i] for vector in vectors) / len(vectors), 6) for i in range(len(names)))))
    interpretations = interpretations or {}
    surfaced = stability >= minimum_stability and all(interpretations.get(cluster.cluster_id, "").strip() for cluster in clusters)
    return ClusterReport(names, tuple(clusters), round(stability, 3), surfaced)


@dataclass(frozen=True, slots=True)
class LearnedOutcomeAssociation:
    prompt_run_id: str
    probability: float
    uncertainty: float
    feature_weights: tuple[tuple[str, float], ...]
    claim_kind: ClaimKind = ClaimKind.PREDICTED
    uncertainty_note: str = "predicted association is non-causal and depends on the supplied training data and feature timing"


def rank_outcome_associations(readiness: MLReadinessReport, train: tuple[DatasetRow, ...], candidates: tuple[DatasetRow, ...], *, outcome_label: str) -> tuple[LearnedOutcomeAssociation, ...]:
    """Rank held-out historical experiences by a readiness-gated logistic outcome association."""
    _require_ready(readiness)
    model = fit_logistic(train, outcome_label)
    weights = tuple(sorted(zip(model.feature_names, model.parameters[1:]), key=lambda item: (-abs(item[1]), item[0])))
    ranked = []
    for row in candidates:
        probability = model.probability(row)
        ranked.append(LearnedOutcomeAssociation(row.prompt_run_id, probability, round(4 * probability * (1 - probability), 3), weights))
    return tuple(sorted(ranked, key=lambda item: (-item.probability, item.prompt_run_id)))
