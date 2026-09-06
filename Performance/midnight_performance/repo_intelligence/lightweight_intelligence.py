"""Lightweight, local-first ML/statistical decision support.

Repo Intelligent 02, Execution 04: cheap predictions about routing,
relevance, novelty, and expected value, used to reduce avoidable LLM/network
work -- never a new truth authority, never required for correctness, and
never able to silently take control of a production decision.

Scope of this module: the reusable framework (feature contract,
training-record construction, cold-start/shadow-mode gating, calibration and
abstention, evaluation against deterministic baselines) plus ONE concrete
decision, ``fetch_worth_it`` -- whether a discovered external source is worth
spending a fetch on. That decision today is gated in
``repo_intelligence_pipeline.py`` by a brittle static threshold
(``MINIMUM_FETCH_RELEVANCE``) applied to ``discovery.RelevanceScore.total``.
This module does not rewire that call site: cost-quality routing is Execution
05's ("Adaptive Cost-Quality Router") canonical ownership, so wiring a second
routing authority in ahead of it would violate the "one attention/escalation
authority" rule the master plan sets out. Everything here is verified
standalone, ready for Execution 05 to consume.

No new dependency is introduced. ``Performance/pyproject.toml`` declares zero
dependencies today; per the spec's "Optional implementation libraries"
section, a library such as scikit-learn or River is justified only when a
dependency-free fallback would not remain functional, which is not the case
for a single logistic model over nine bounded features. Preferred model
order (per the master plan's intelligence ladder) is followed: a calibrated
rule/baseline is rung 1, the online logistic model is rung 2; no rung above
that is implemented because nothing here has evidence it is needed.

Hard rules are out of reach of this module by construction, not by
convention: every function here only ever sees bounded ``FeatureVector``
floats derived from ``discovery.RelevanceScore``. It has no access to
privacy policy, provenance, or contradiction state, so it structurally
cannot override the hard rules ``sufficiency.py`` and ``research_security.py``
already enforce upstream of any fetch decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from ..contracts import Identity
from .contracts import LearnedDecisionRecord, new_event_identity
from .cost_quality import MethodResult, Spend, TaskProfile
from .discovery import RelevanceScore
from .identities import RepoIntelligenceKind

FEATURE_SCHEMA_VERSION = 1

FETCH_WORTH_IT = "fetch_worth_it"
ROUTING_CONFIDENCE = "routing_confidence"
KNOWN_DECISION_TYPES = frozenset({FETCH_WORTH_IT, ROUTING_CONFIDENCE})

_FEATURE_NAMES: dict[str, tuple[str, ...]] = {
    FETCH_WORTH_IT: (
        "project_match",
        "hotspot_match",
        "evidence_quality",
        "source_authority",
        "freshness",
        "novelty",
        "learning_value",
        "diversity",
        "redundancy",
    ),
    # A deliberately separate schema from fetch_worth_it (Execution 05):
    # whether the cost-quality router's LIGHTWEIGHT_ML rung can itself
    # resolve a task, from TaskProfile's own bounded routing-input fields.
    ROUTING_CONFIDENCE: (
        "required_quality",
        "uncertainty",
        "freshness_need",
        "privacy_risk",
        "expected_information_gain",
    ),
}

_FETCH = "fetch"
_SKIP = "skip"


def _is_finite_float(value: object) -> bool:
    return isinstance(value, float) and value == value and value not in (float("inf"), float("-inf"))


# ---------------------------------------------------------------------------
# Feature contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """A closed, versioned, floats-only feature set for one decision type.

    Values are structurally forbidden from carrying raw text, secrets, or
    object references: every entry must be a finite float in ``[0, 1]``, and
    only feature names registered for ``decision_type`` are accepted.
    """

    decision_type: str
    schema_version: int
    values: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if self.decision_type not in KNOWN_DECISION_TYPES:
            raise ValueError(f"unknown decision_type {self.decision_type!r}; not eligible for lightweight ML")
        if self.schema_version != FEATURE_SCHEMA_VERSION:
            raise ValueError(
                f"feature schema version {self.schema_version!r} is not supported "
                f"(supported: {FEATURE_SCHEMA_VERSION})"
            )
        allowed = frozenset(_FEATURE_NAMES[self.decision_type])
        names = [name for name, _ in self.values]
        if len(names) != len(set(names)):
            raise ValueError("feature vectors must not repeat a feature name")
        unknown = set(names) - allowed
        if unknown:
            raise ValueError(
                f"feature vector carries unregistered feature(s) {sorted(unknown)}; "
                "forbidden by the feature contract"
            )
        missing = allowed - set(names)
        if missing:
            raise ValueError(
                f"feature vector for {self.decision_type!r} is missing required feature(s) {sorted(missing)}"
            )
        for name, value in self.values:
            if not _is_finite_float(value):
                raise ValueError(f"feature {name!r} must be a finite float, never raw text/objects")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"feature {name!r} must be between zero and one")

    def as_dict(self) -> dict[str, float]:
        return dict(self.values)


def relevance_features(score: RelevanceScore) -> FeatureVector:
    """Convert an already-computed, bounded ``RelevanceScore`` into features.

    No raw text, provider identifiers, or source content pass through this
    conversion -- only the nine bounded relevance dimensions
    ``discovery.score_discovery`` already derives. ``privacy_risk`` and
    ``cost`` are outside this decision's feature contract because
    ``score_discovery`` never sets them (they default to zero).
    """
    names = _FEATURE_NAMES[FETCH_WORTH_IT]
    values = tuple((name, float(getattr(score, name))) for name in names)
    return FeatureVector(decision_type=FETCH_WORTH_IT, schema_version=FEATURE_SCHEMA_VERSION, values=values)


def routing_confidence_features(profile: TaskProfile) -> FeatureVector:
    """Convert a router ``TaskProfile``'s own bounded fields into features.

    No task/evidence text passes through this conversion -- only the five
    ``[0, 1]`` routing-input floats ``TaskProfile`` already validates.
    """
    names = _FEATURE_NAMES[ROUTING_CONFIDENCE]
    values = tuple((name, float(getattr(profile, name))) for name in names)
    return FeatureVector(decision_type=ROUTING_CONFIDENCE, schema_version=FEATURE_SCHEMA_VERSION, values=values)


# ---------------------------------------------------------------------------
# Model classes (cheapest qualified rung first)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeterministicBaseline:
    """Rung 1: the existing calibrated rule, reproduced from feature values alone.

    Recomputes ``RelevanceScore.total`` from a feature vector's own values
    (``privacy_risk``/``cost`` are not part of the ``fetch_worth_it`` feature
    contract and are treated as zero, matching ``score_discovery``'s own
    defaults), so it needs no training data and is always available -- the
    thing every other rung is measured against.
    """

    decision_type: str = FETCH_WORTH_IT

    def __post_init__(self) -> None:
        if self.decision_type not in KNOWN_DECISION_TYPES:
            raise ValueError(f"unknown decision_type {self.decision_type!r}")

    def predict_proba(self, features: FeatureVector) -> float:
        if features.decision_type != self.decision_type:
            raise ValueError("feature vector decision_type does not match this baseline")
        return _BASELINE_FORMULAS[self.decision_type](features.as_dict())

    def action(self, features: FeatureVector, *, threshold: float) -> str:
        return _FETCH if self.predict_proba(features) >= threshold else _SKIP


def _fetch_worth_it_baseline(values: dict[str, float]) -> float:
    positive = sum(
        values[name]
        for name in (
            "project_match",
            "hotspot_match",
            "evidence_quality",
            "source_authority",
            "freshness",
            "novelty",
            "learning_value",
            "diversity",
        )
    ) / 8.0
    penalty = values["redundancy"] / 3.0
    return round(max(0.0, min(1.0, positive - penalty)), 6)


def _routing_confidence_baseline(values: dict[str, float]) -> float:
    """Cheap-rung resolvability: high when little would be gained by escalating.

    Modest required quality, a loose uncertainty tolerance, low freshness
    pressure, low privacy risk, and low expected information gain from a
    stronger method all point toward "this rung already resolves it."
    """
    ease = (
        (1.0 - values["required_quality"])
        + values["uncertainty"]
        + (1.0 - values["freshness_need"])
        + (1.0 - values["privacy_risk"])
        + (1.0 - values["expected_information_gain"])
    ) / 5.0
    return round(max(0.0, min(1.0, ease)), 6)


_BASELINE_FORMULAS: dict[str, "Callable[[dict[str, float]], float]"] = {
    FETCH_WORTH_IT: _fetch_worth_it_baseline,
    ROUTING_CONFIDENCE: _routing_confidence_baseline,
}


@dataclass(frozen=True, slots=True)
class OnlineLogisticModel:
    """Rung 2: a dependency-free online logistic regression.

    Weights are a plain ``tuple[float, ...]`` plus a bias, in the exact
    ``feature_order`` registered for ``decision_type`` -- deterministic
    serialization is trivial (compare, hash, or store the tuple directly).
    ``partial_fit`` returns a new, immutable instance rather than mutating in
    place, matching this package's frozen-dataclass convention.
    """

    decision_type: str
    feature_order: tuple[str, ...]
    weights: tuple[float, ...]
    bias: float = 0.0
    learning_rate: float = 0.1
    version: str = "1"

    def __post_init__(self) -> None:
        if self.decision_type not in KNOWN_DECISION_TYPES:
            raise ValueError(f"unknown decision_type {self.decision_type!r}")
        if self.feature_order != _FEATURE_NAMES[self.decision_type]:
            raise ValueError("feature_order must exactly match the registered feature contract order")
        if len(self.weights) != len(self.feature_order):
            raise ValueError("weights must have one entry per registered feature")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        if not self.version.strip():
            raise ValueError("model version must not be blank")

    @classmethod
    def initial(cls, decision_type: str, *, learning_rate: float = 0.1, version: str = "1") -> "OnlineLogisticModel":
        order = _FEATURE_NAMES[decision_type]
        return cls(decision_type, order, tuple(0.0 for _ in order), 0.0, learning_rate, version)

    def _ordered_values(self, features: FeatureVector) -> tuple[float, ...]:
        if features.decision_type != self.decision_type:
            raise ValueError("feature vector decision_type does not match this model")
        mapping = features.as_dict()
        return tuple(mapping[name] for name in self.feature_order)

    def predict_proba(self, features: FeatureVector) -> float:
        xs = self._ordered_values(features)
        z = self.bias + sum(w * x for w, x in zip(self.weights, xs))
        z = max(-60.0, min(60.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def partial_fit(self, features: FeatureVector, label: bool) -> "OnlineLogisticModel":
        xs = self._ordered_values(features)
        prediction = self.predict_proba(features)
        error = prediction - (1.0 if label else 0.0)
        new_weights = tuple(w - self.learning_rate * error * x for w, x in zip(self.weights, xs))
        new_bias = self.bias - self.learning_rate * error
        return replace(self, weights=new_weights, bias=new_bias)

    def fit(self, examples: tuple[tuple[FeatureVector, bool], ...], *, epochs: int = 1) -> "OnlineLogisticModel":
        model = self
        for _ in range(max(1, epochs)):
            for features, label in examples:
                model = model.partial_fit(features, label)
        return model


# ---------------------------------------------------------------------------
# Calibration and abstention
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    lower: float
    upper: float
    count: int
    mean_predicted: float
    empirical_rate: float


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    buckets: tuple[CalibrationBucket, ...]
    expected_calibration_error: float
    sample_count: int


def _bucket_reliability(
    pairs: tuple[tuple[float, bool], ...], *, buckets: int
) -> tuple[tuple[CalibrationBucket, ...], float]:
    if buckets < 1:
        raise ValueError("bucketed reliability requires at least one bucket")
    if not pairs:
        return (), 0.0
    width = 1.0 / buckets
    rows: list[list[tuple[float, bool]]] = [[] for _ in range(buckets)]
    for probability, label in pairs:
        index = min(buckets - 1, max(0, int(probability / width)))
        rows[index].append((probability, label))
    bucket_reports: list[CalibrationBucket] = []
    weighted_error = 0.0
    total = len(pairs)
    for index, rows_in_bucket in enumerate(rows):
        if not rows_in_bucket:
            continue
        mean_predicted = sum(p for p, _ in rows_in_bucket) / len(rows_in_bucket)
        empirical = sum(1.0 for _, label in rows_in_bucket if label) / len(rows_in_bucket)
        bucket_reports.append(
            CalibrationBucket(index * width, (index + 1) * width, len(rows_in_bucket), round(mean_predicted, 6), round(empirical, 6))
        )
        weighted_error += (len(rows_in_bucket) / total) * abs(mean_predicted - empirical)
    return tuple(bucket_reports), round(weighted_error, 6)


def calibrate(
    predictor: "DeterministicBaseline | OnlineLogisticModel",
    labeled: tuple[tuple[FeatureVector, bool], ...],
    *,
    buckets: int = 5,
) -> CalibrationReport:
    """Measured reliability diagram + expected calibration error (ECE).

    Raw model probability is not automatically calibrated confidence; this
    is the measurement the spec requires before any promotion decision.
    """
    pairs = tuple((predictor.predict_proba(features), label) for features, label in labeled)
    bucket_reports, ece = _bucket_reliability(pairs, buckets=buckets)
    return CalibrationReport(bucket_reports, ece, len(labeled))


@dataclass(frozen=True, slots=True)
class AbstentionPolicy:
    """Ambiguous predictions abstain rather than fabricate confidence."""

    margin: float = 0.1

    def __post_init__(self) -> None:
        if not 0.0 <= self.margin < 0.5:
            raise ValueError("abstention margin must be within [0, 0.5)")

    def abstains(self, probability: float) -> bool:
        return abs(probability - 0.5) < self.margin


# ---------------------------------------------------------------------------
# Cold-start / shadow-mode gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LightweightDecision:
    action: str
    shadow_probability: float | None
    production_probability: float | None
    abstained: bool
    used_model: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ShadowModeGate:
    """Cold start -> shadow mode -> (explicitly promoted) production.

    No learned model may silently take control: ``action`` is read from the
    deterministic baseline in every case except one -- a caller-constructed
    gate whose ``model``, ``sample_count``, and ``calibration`` already meet
    every promotion bar (``eligible_for_production``), and even then the
    model's own abstention zone can still fall back to the baseline.
    """

    decision_type: str
    baseline: DeterministicBaseline
    baseline_threshold: float
    model: OnlineLogisticModel | None = None
    sample_count: int = 0
    calibration: CalibrationReport | None = None
    min_samples_for_shadow: int = 20
    min_samples_for_production: int = 200
    max_calibration_error: float = 0.1
    abstention: AbstentionPolicy = AbstentionPolicy()

    def __post_init__(self) -> None:
        if self.decision_type not in KNOWN_DECISION_TYPES:
            raise ValueError(f"unknown decision_type {self.decision_type!r}")
        if self.baseline.decision_type != self.decision_type:
            raise ValueError("baseline decision_type does not match this gate")
        if not 0.0 <= self.baseline_threshold <= 1.0:
            raise ValueError("baseline_threshold must be between zero and one")
        if self.model is not None and self.model.decision_type != self.decision_type:
            raise ValueError("model decision_type does not match this gate")
        if self.sample_count < 0:
            raise ValueError("sample_count must not be negative")
        if self.min_samples_for_shadow < 0 or self.min_samples_for_production < self.min_samples_for_shadow:
            raise ValueError("sample thresholds must be non-negative and monotonic")
        if not 0.0 <= self.max_calibration_error <= 1.0:
            raise ValueError("max_calibration_error must be between zero and one")

    @property
    def eligible_for_shadow(self) -> bool:
        return self.model is not None and self.sample_count >= self.min_samples_for_shadow

    @property
    def eligible_for_production(self) -> bool:
        return (
            self.eligible_for_shadow
            and self.sample_count >= self.min_samples_for_production
            and self.calibration is not None
            and self.calibration.expected_calibration_error <= self.max_calibration_error
        )

    def decide(self, features: FeatureVector) -> LightweightDecision:
        if features.decision_type != self.decision_type:
            raise ValueError("feature vector decision_type does not match this gate")
        baseline_action = self.baseline.action(features, threshold=self.baseline_threshold)
        if not self.eligible_for_shadow:
            return LightweightDecision(baseline_action, None, None, False, False, "cold_start_deterministic")
        shadow_probability = self.model.predict_proba(features)  # type: ignore[union-attr]
        if not self.eligible_for_production:
            return LightweightDecision(
                baseline_action, shadow_probability, None, False, False, "shadow_mode_no_production_effect"
            )
        if self.abstention.abstains(shadow_probability):
            return LightweightDecision(baseline_action, shadow_probability, None, True, False, "abstained_ambiguous")
        model_action = _FETCH if shadow_probability >= 0.5 else _SKIP
        return LightweightDecision(model_action, shadow_probability, shadow_probability, False, True, "model_promoted")


def abstention_rate(decisions: tuple[LightweightDecision, ...]) -> float:
    if not decisions:
        return 0.0
    return sum(1 for d in decisions if d.abstained) / len(decisions)


def resolve_routing_confidence(gate: ShadowModeGate, profile: TaskProfile) -> MethodResult:
    """Bridge a ``ShadowModeGate`` decision into the router's ``MethodResult`` shape.

    This is the concrete resolver behind ``cost_quality.MethodTier.LIGHTWEIGHT_ML``:
    zero cost/latency (pure local compute). The framework's shared "fetch"
    positive-class label means "resolvable at this rung" for this decision
    type; an abstained or cold-start decision reports zero coverage so the
    router's quality-floor check always fails closed and escalates rather
    than accepting on a fabricated confidence.
    """
    if gate.decision_type != ROUTING_CONFIDENCE:
        raise ValueError("resolve_routing_confidence requires a routing_confidence gate")
    features = routing_confidence_features(profile)
    decision = gate.decide(features)
    probability = decision.production_probability if decision.production_probability is not None else decision.shadow_probability
    resolvable = decision.action == _FETCH
    if decision.abstained or probability is None:
        coverage = 0.0
    else:
        coverage = probability if resolvable else (1.0 - probability)
    return MethodResult(
        output="accept" if resolvable else "escalate", evidence_coverage=coverage, uncertainty=1.0 - coverage, spend=Spend()
    )


# ---------------------------------------------------------------------------
# Training-record construction
# ---------------------------------------------------------------------------


def record_decision(
    project: Identity,
    decision: LightweightDecision,
    features: FeatureVector,
    *,
    model_name: str,
    model_version: str,
    occurred_at: datetime,
    evidence_ids: tuple[str, ...] = (),
    cost_micros: int | None = None,
    latency_ms: float | None = None,
) -> LearnedDecisionRecord:
    """Pure builder: never persists. Callers own storage, as with CostRecord/Exposure."""
    probability = (
        decision.shadow_probability if decision.shadow_probability is not None else decision.production_probability
    )
    prediction = probability if probability is not None else 0.5
    uncertainty = max(0.0, min(1.0, 1.0 - 2.0 * abs(prediction - 0.5)))
    return LearnedDecisionRecord(
        identity=new_event_identity(RepoIntelligenceKind.LEARNED_DECISION_RECORD),
        project=project,
        decision_type=features.decision_type,
        feature_schema_version=features.schema_version,
        features=features.values,
        prediction=prediction,
        uncertainty=uncertainty,
        action_chosen=decision.action,
        model_name=model_name,
        model_version=model_version,
        occurred_at=occurred_at,
        evidence_ids=evidence_ids,
        cost_micros=cost_micros,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Evaluation against baselines
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LearnedModelEvaluation:
    precision: float | None
    recall: float | None
    false_suppression_rate: float | None
    false_escalation_rate: float | None
    calibration_error: float | None
    mean_cost_micros: float | None
    mean_latency_ms: float | None
    sample_count: int


def _feature_vector_from_record(record: LearnedDecisionRecord) -> FeatureVector:
    return FeatureVector(
        decision_type=record.decision_type, schema_version=record.feature_schema_version, values=record.features
    )


def _confusion_metrics(
    records: tuple[LearnedDecisionRecord, ...], action_for: Callable[[LearnedDecisionRecord], str]
) -> tuple[float | None, float | None, float | None, float | None]:
    tp = fp = fn = tn = 0
    for record in records:
        positive_prediction = action_for(record) == _FETCH
        if record.outcome_label:
            tp += positive_prediction
            fn += not positive_prediction
        else:
            fp += positive_prediction
            tn += not positive_prediction
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    false_suppression = fn / (tp + fn) if (tp + fn) else None
    false_escalation = fp / (fp + tn) if (fp + tn) else None
    return precision, recall, false_suppression, false_escalation


def evaluate_against_baselines(
    records: tuple[LearnedDecisionRecord, ...],
    *,
    baseline: DeterministicBaseline,
    baseline_threshold: float,
) -> dict[str, LearnedModelEvaluation]:
    """Compare the model, the deterministic baseline, and always-escalate.

    Only records carrying a real ``outcome_label`` participate; unlabeled
    records are silently excluded, never treated as a negative outcome.
    """
    labeled = tuple(record for record in records if record.outcome_label is not None)
    action_for: dict[str, Callable[[LearnedDecisionRecord], str]] = {
        "model": lambda record: _FETCH if record.prediction >= 0.5 else _SKIP,
        "deterministic_baseline": lambda record: baseline.action(
            _feature_vector_from_record(record), threshold=baseline_threshold
        ),
        "always_escalate": lambda record: _FETCH,
    }
    probability_for: dict[str, Callable[[LearnedDecisionRecord], float]] = {
        "model": lambda record: record.prediction,
        "deterministic_baseline": lambda record: baseline.predict_proba(_feature_vector_from_record(record)),
        "always_escalate": lambda record: 1.0,
    }
    results: dict[str, LearnedModelEvaluation] = {}
    for name, action_fn in action_for.items():
        precision, recall, false_suppression, false_escalation = _confusion_metrics(labeled, action_fn)
        if labeled:
            pairs = tuple((probability_for[name](record), bool(record.outcome_label)) for record in labeled)
            _, calibration_error = _bucket_reliability(pairs, buckets=5)
        else:
            calibration_error = None
        costs = [record.cost_micros for record in labeled if record.cost_micros is not None and action_fn(record) == _FETCH]
        latencies = [record.latency_ms for record in labeled if record.latency_ms is not None and action_fn(record) == _FETCH]
        results[name] = LearnedModelEvaluation(
            precision=precision,
            recall=recall,
            false_suppression_rate=false_suppression,
            false_escalation_rate=false_escalation,
            calibration_error=calibration_error,
            mean_cost_micros=(sum(costs) / len(costs)) if costs else None,
            mean_latency_ms=(sum(latencies) / len(latencies)) if latencies else None,
            sample_count=len(labeled),
        )
    return results


def promotion_reason(evaluation: dict[str, LearnedModelEvaluation]) -> str:
    """A real negative result is a valid outcome; never fabricate promotion."""
    model = evaluation.get("model")
    baseline = evaluation.get("deterministic_baseline")
    if model is None or baseline is None:
        return "NO ML PROMOTION — deterministic baseline remains superior"
    if model.precision is None or model.recall is None or baseline.precision is None or baseline.recall is None:
        return "NO ML PROMOTION — deterministic baseline remains superior"
    calibration_ok = (
        model.calibration_error is not None
        and baseline.calibration_error is not None
        and model.calibration_error <= baseline.calibration_error + 0.05
    )
    strictly_better = (model.precision > baseline.precision and model.recall >= baseline.recall) or (
        model.recall > baseline.recall and model.precision >= baseline.precision
    )
    if strictly_better and calibration_ok:
        return (
            f"model promotion-eligible: precision {model.precision:.3f} vs baseline {baseline.precision:.3f}, "
            f"recall {model.recall:.3f} vs baseline {baseline.recall:.3f}"
        )
    return "NO ML PROMOTION — deterministic baseline remains superior"


__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "FETCH_WORTH_IT",
    "ROUTING_CONFIDENCE",
    "KNOWN_DECISION_TYPES",
    "AbstentionPolicy",
    "CalibrationBucket",
    "CalibrationReport",
    "DeterministicBaseline",
    "FeatureVector",
    "LearnedModelEvaluation",
    "LightweightDecision",
    "OnlineLogisticModel",
    "ShadowModeGate",
    "abstention_rate",
    "calibrate",
    "evaluate_against_baselines",
    "promotion_reason",
    "record_decision",
    "relevance_features",
    "resolve_routing_confidence",
    "routing_confidence_features",
]
