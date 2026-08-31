"""Content-free operational telemetry for Performance itself."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from time import perf_counter
from typing import Callable


class PerformanceMetric(str, Enum):
    INGESTION_LATENCY = "ingestion_latency_ms"
    ADAPTER_HEALTH = "adapter_health"
    CODE_WATCH_INTEGRATION_HEALTH = "code_watch_integration_health"
    ANALYSIS_LATENCY = "analysis_latency_ms"
    FEATURE_EXTRACTION_LATENCY = "feature_extraction_latency_ms"
    DATASET_FRESHNESS = "dataset_freshness_seconds"
    EVALUATOR_LATENCY = "evaluator_latency_ms"
    EVALUATOR_COST = "evaluator_cost"
    MODEL_INFERENCE_LATENCY = "model_inference_latency_ms"
    DRIFT_JOB_LATENCY = "drift_job_latency_ms"
    MEMORY_PROMOTION_LATENCY = "memory_promotion_latency_ms"
    MEMORY_RETRIEVAL_LATENCY = "memory_retrieval_latency_ms"
    RECOMMENDATION_LATENCY = "recommendation_latency_ms"
    QUEUE_DEPTH = "queue_depth"
    FAILURE = "failure"
    DROPPED_EVIDENCE = "dropped_evidence"


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    metric: PerformanceMetric
    value: float
    subject: str
    succeeded: bool | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.subject.strip() or self.value < 0 or self.observed_at.tzinfo is None:
            raise ValueError("telemetry requires a subject, non-negative value, and timezone-aware time")


class PerformanceTelemetry:
    """In-memory, caller-owned measurements. It records no prompts, source, or secrets."""

    def __init__(self) -> None:
        self._samples: list[TelemetrySample] = []

    @property
    def samples(self) -> tuple[TelemetrySample, ...]:
        return tuple(self._samples)

    def record(self, metric: PerformanceMetric, value: float, *, subject: str, succeeded: bool | None = None, observed_at: datetime | None = None) -> TelemetrySample:
        sample = TelemetrySample(metric, value, subject, succeeded, observed_at or datetime.now(timezone.utc))
        self._samples.append(sample)
        return sample

    def measure(self, metric: PerformanceMetric, *, subject: str, operation: Callable[[], object], clock: Callable[[], float] = perf_counter) -> object:
        started = clock()
        try:
            result = operation()
        except Exception:
            self.record(metric, max(0.0, (clock() - started) * 1000), subject=subject, succeeded=False)
            self.record(PerformanceMetric.FAILURE, 1, subject=subject, succeeded=False)
            raise
        self.record(metric, max(0.0, (clock() - started) * 1000), subject=subject, succeeded=True)
        return result
