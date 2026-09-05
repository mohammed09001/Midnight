"""Content-free observability and reproducible learning-value evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..contracts import EntityKind, Identity
from .authorization import RepoIntelligenceAuthorization, ensure_same_project


class OperationName(str, Enum):
    SIGNAL_DETECTION = "repo_intelligence.signal_detection"
    INTERNAL_RETRIEVAL = "repo_intelligence.internal_retrieval"
    EXTERNAL_SEARCH = "repo_intelligence.external_search"
    EXTERNAL_FETCH = "repo_intelligence.external_fetch"
    GRAPH_TRAVERSAL = "repo_intelligence.graph_traversal"
    MODEL_CLASSIFICATION = "repo_intelligence.model_classification"
    MODEL_SYNTHESIS = "repo_intelligence.model_synthesis"
    CACHE_LOOKUP = "repo_intelligence.cache_lookup"
    INSIGHT_GENERATION = "repo_intelligence.insight_generation"
    EXPOSURE = "repo_intelligence.exposure"
    FEEDBACK_OUTCOME = "repo_intelligence.feedback_outcome"
    BUDGET_DECISION = "repo_intelligence.budget_decision"
    FAILURE_DEGRADATION = "repo_intelligence.failure_degradation"


class RecordKind(str, Enum):
    SPAN = "span"
    EVENT = "event"


_ALLOWED_ATTRIBUTES = frozenset({
    "accepted", "useful", "duplicate", "unsupported", "evidence_coverage",
    "internal_only", "search_results", "search_selected", "strong_model",
    "cache_hit", "cost_micros", "tokens", "cancelled", "hotspot",
    "hotspot_converted", "time_to_useful_ms", "provenance_accurate",
    "later_positive_association", "later_negative_association", "degraded",
    "failure_class", "source_class", "method_tier",
})


@dataclass(frozen=True, slots=True)
class OperationRecord:
    project: Identity
    operation: OperationName
    kind: RecordKind
    observed_at: datetime
    succeeded: bool
    duration_ms: float | None = None
    attributes: tuple[tuple[str, str | int | float | bool], ...] = ()

    def __post_init__(self) -> None:
        if self.project.kind is not EntityKind.PROJECT or self.observed_at.tzinfo is None:
            raise ValueError("operation records require a project and timezone-aware time")
        if self.kind is RecordKind.SPAN and self.duration_ms is None:
            raise ValueError("duration-bearing spans require duration_ms")
        if self.kind is RecordKind.EVENT and self.duration_ms is not None:
            raise ValueError("point-in-time events cannot carry duration")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("operation duration cannot be negative")
        keys = [key for key, _ in self.attributes]
        if len(keys) != len(set(keys)) or any(key not in _ALLOWED_ATTRIBUTES for key in keys):
            raise ValueError("operation attributes must be unique and low-cardinality allowlisted fields")
        for key, value in self.attributes:
            if isinstance(value, str) and (len(value) > 80 or any(marker in value.lower() for marker in ("api_key", "password=", "token=", "-----begin"))):
                raise ValueError(f"sensitive or verbose telemetry attribute rejected: {key}")

    def attribute_map(self) -> dict[str, str | int | float | bool]:
        return dict(self.attributes)


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    insight_acceptance_rate: float | None
    insight_usefulness_rate: float | None
    duplicate_exposure_rate: float | None
    unsupported_claim_rate: float | None
    mean_evidence_coverage: float | None
    mean_time_to_useful_insight_ms: float | None
    internal_only_resolution_rate: float | None
    external_search_yield: float | None
    strong_model_escalation_rate: float | None
    cache_hit_rate: float | None
    cost_per_useful_insight_micros: float | None
    tokens_per_useful_insight: float | None
    research_abandonment_rate: float | None
    hotspot_to_learning_conversion: float | None
    later_positive_association_rate: float | None
    association_disclosure: str = "later verification/rework association is observational and never causal proof"


def _rate(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def derive_metrics(records: tuple[OperationRecord, ...], authorization: RepoIntelligenceAuthorization) -> MetricSnapshot:
    """Pure projection: the same recorded events always produce the same metrics."""
    rows = []
    for record in records:
        ensure_same_project(authorization, project=record.project)
        rows.append(record.attribute_map())
    insights = sum(bool(row.get("accepted")) or "unsupported" in row for row in rows)
    accepted = sum(bool(row.get("accepted")) for row in rows)
    useful = sum(bool(row.get("useful")) for row in rows)
    exposures = sum(record.operation is OperationName.EXPOSURE for record in records)
    duplicates = sum(bool(row.get("duplicate")) for row in rows)
    unsupported = sum(bool(row.get("unsupported")) for row in rows)
    coverage = [float(row["evidence_coverage"]) for row in rows if "evidence_coverage" in row]
    useful_times = [float(row["time_to_useful_ms"]) for row in rows if "time_to_useful_ms" in row]
    internal = sum(bool(row.get("internal_only")) and bool(row.get("accepted")) for row in rows)
    search_results = sum(float(row.get("search_results", 0)) for row in rows)
    selected = sum(float(row.get("search_selected", 0)) for row in rows)
    model_calls = sum(record.operation in (OperationName.MODEL_CLASSIFICATION, OperationName.MODEL_SYNTHESIS) for record in records)
    strong = sum(bool(row.get("strong_model")) for row in rows)
    cache_lookups = sum(record.operation is OperationName.CACHE_LOOKUP for record in records)
    cache_hits = sum(bool(row.get("cache_hit")) for row in rows)
    cost = sum(float(row.get("cost_micros", 0)) for row in rows)
    tokens = sum(float(row.get("tokens", 0)) for row in rows)
    research = sum(record.operation in (OperationName.EXTERNAL_SEARCH, OperationName.EXTERNAL_FETCH, OperationName.MODEL_SYNTHESIS) for record in records)
    cancelled = sum(bool(row.get("cancelled")) for row in rows)
    hotspots = sum(bool(row.get("hotspot")) for row in rows)
    conversions = sum(bool(row.get("hotspot_converted")) for row in rows)
    association_rows = [row for row in rows if "later_positive_association" in row or "later_negative_association" in row]
    positive = sum(bool(row.get("later_positive_association")) for row in association_rows)
    return MetricSnapshot(
        _rate(accepted, insights), _rate(useful, accepted), _rate(duplicates, exposures),
        _rate(unsupported, insights), round(sum(coverage) / len(coverage), 6) if coverage else None,
        round(sum(useful_times) / len(useful_times), 3) if useful_times else None,
        _rate(internal, accepted), _rate(selected, search_results), _rate(strong, model_calls),
        _rate(cache_hits, cache_lookups), _rate(cost, useful), _rate(tokens, useful),
        _rate(cancelled, research), _rate(conversions, hotspots), _rate(positive, len(association_rows)),
    )


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    minimum_acceptance: float = 0.6
    minimum_usefulness: float = 0.5
    maximum_unsupported_claim_rate: float = 0.0
    minimum_evidence_coverage: float = 0.8
    minimum_provenance_accuracy: float = 1.0

    def __post_init__(self) -> None:
        if any(not 0 <= value <= 1 for value in (
            self.minimum_acceptance, self.minimum_usefulness,
            self.maximum_unsupported_claim_rate, self.minimum_evidence_coverage,
            self.minimum_provenance_accuracy,
        )):
            raise ValueError("quality thresholds must be between zero and one")


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    passed: bool
    failures: tuple[str, ...]


def evaluate_release(snapshot: MetricSnapshot, records: tuple[OperationRecord, ...], thresholds: QualityThresholds = QualityThresholds()) -> ReleaseGate:
    failures = []
    checks = (
        ("insight acceptance", snapshot.insight_acceptance_rate, thresholds.minimum_acceptance, True),
        ("insight usefulness", snapshot.insight_usefulness_rate, thresholds.minimum_usefulness, True),
        ("unsupported claim rate", snapshot.unsupported_claim_rate, thresholds.maximum_unsupported_claim_rate, False),
        ("evidence coverage", snapshot.mean_evidence_coverage, thresholds.minimum_evidence_coverage, True),
    )
    for name, value, threshold, minimum in checks:
        if value is None:
            failures.append(f"{name} is unmeasured")
        elif (value < threshold if minimum else value > threshold):
            failures.append(f"{name}={value} failed threshold {threshold}")
    provenance = [bool(record.attribute_map().get("provenance_accurate")) for record in records if "provenance_accurate" in record.attribute_map()]
    accuracy = _rate(sum(provenance), len(provenance))
    if accuracy is None or accuracy < thresholds.minimum_provenance_accuracy:
        failures.append("provenance accuracy is unmeasured or below threshold")
    return ReleaseGate(not failures, tuple(failures))


class DatasetCategory(str, Enum):
    HOTSPOT_UNDERSTANDING = "repository_hotspot_understanding"
    ARCHITECTURE_CONNECTION = "architecture_concept_connection"
    EXTERNAL_ANALOGUE = "external_analogue_discovery"
    STALE_CONTRADICTION = "stale_contradictory_source_handling"
    GLOBAL_CATCH_UP = "global_catch_me_up"
    LOCAL_COMPONENT = "local_component_question"
    PRIVATE_QUERY = "privacy_preserving_query_abstraction"
    COST_QUALITY = "cost_quality_routing"


class EvaluationVariant(str, Enum):
    LEXICAL_VECTOR = "A_lexical_vector"
    INTERNAL_GRAPH = "B_internal_graph"
    INTERNAL_EXTERNAL = "C_internal_external"
    FULL_ADAPTIVE = "D_full_adaptive"


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    category: DatasetCategory
    expected_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.expected_evidence_refs:
            raise ValueError("evaluation cases require identity and expected evidence")


@dataclass(frozen=True, slots=True)
class VariantResult:
    variant: EvaluationVariant
    quality: float
    comprehensiveness: float
    diversity: float
    provenance_accuracy: float
    latency_ms: float
    cost_micros: int

    def __post_init__(self) -> None:
        if any(not 0 <= value <= 1 for value in (self.quality, self.comprehensiveness, self.diversity, self.provenance_accuracy)):
            raise ValueError("variant quality measures must be between zero and one")
        if self.latency_ms < 0 or self.cost_micros < 0:
            raise ValueError("variant latency and cost cannot be negative")


def rank_variants(results: tuple[VariantResult, ...]) -> tuple[VariantResult, ...]:
    """Stable comparison; quality dominates, then provenance, latency and cost."""
    return tuple(sorted(results, key=lambda row: (-row.quality, -row.provenance_accuracy, row.latency_ms, row.cost_micros, row.variant.value)))


__all__ = ["DatasetCategory", "EvaluationCase", "EvaluationVariant", "MetricSnapshot", "OperationName", "OperationRecord", "QualityThresholds", "RecordKind", "ReleaseGate", "VariantResult", "derive_metrics", "evaluate_release", "rank_variants"]
