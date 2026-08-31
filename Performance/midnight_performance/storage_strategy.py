"""Storage workload boundaries and measured analytical-storage selection.

This module is a contract, not a distributed storage deployment.  It records
which existing owner is authoritative and refuses to select columnar storage
without a repeatable workload measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import median
from time import perf_counter
from typing import Callable, Mapping


STORAGE_STRATEGY_VERSION = 1


class StorageWorkload(str, Enum):
    PRODUCT_STATE = "product_state"
    OBSERVATIONS = "observations"
    ANALYTICAL_DATASETS = "analytical_datasets"
    EMBEDDINGS = "embeddings"
    EXPERIMENT_ARTIFACTS = "experiment_artifacts"
    MODEL_ARTIFACTS = "model_artifacts"
    MEMORY = "memory"


class StorageRole(str, Enum):
    CANONICAL = "canonical"
    REBUILDABLE = "rebuildable"
    DURABLE_ARTIFACT = "durable_artifact"
    INTERFACE = "interface"


class AnalyticalEngine(str, Enum):
    RELATIONAL_PROJECTION = "relational_projection"
    COLUMNAR = "columnar"


@dataclass(frozen=True, slots=True)
class StorageBoundary:
    workload: StorageWorkload
    role: StorageRole
    owner: str
    engine: str
    external_ai_optional: bool = True

    def __post_init__(self) -> None:
        if not self.owner.strip() or not self.engine.strip():
            raise ValueError("storage boundary requires an owner and engine")


def storage_boundaries() -> tuple[StorageBoundary, ...]:
    """Current local-first boundaries; no distributed infrastructure is selected."""
    return (
        StorageBoundary(StorageWorkload.PRODUCT_STATE, StorageRole.INTERFACE, "product-state interface", "host-selected local/BYOC store"),
        StorageBoundary(StorageWorkload.OBSERVATIONS, StorageRole.CANONICAL, "EvidenceLedger", "project-isolated JSONL"),
        StorageBoundary(StorageWorkload.ANALYTICAL_DATASETS, StorageRole.REBUILDABLE, "DatasetSnapshot", "in-memory relational projection"),
        StorageBoundary(StorageWorkload.EMBEDDINGS, StorageRole.REBUILDABLE, "EmbeddingVector", "provider-versioned retrieval projection"),
        StorageBoundary(StorageWorkload.EXPERIMENT_ARTIFACTS, StorageRole.DURABLE_ARTIFACT, "ExperimentDefinition/DatasetSnapshot", "versioned immutable contract"),
        StorageBoundary(StorageWorkload.MODEL_ARTIFACTS, StorageRole.DURABLE_ARTIFACT, "ModelRegistry", "versioned immutable contract"),
        StorageBoundary(StorageWorkload.MEMORY, StorageRole.INTERFACE, "KnowledgeRecord", "versioned Memory interface"),
    )


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    workload: str
    iterations: int
    median_ms: float
    p95_ms: float

    def __post_init__(self) -> None:
        if not self.workload.strip() or self.iterations < 1 or self.median_ms < 0 or self.p95_ms < 0:
            raise ValueError("benchmark result is invalid")


@dataclass(frozen=True, slots=True)
class AnalyticalStorageDecision:
    engine: AnalyticalEngine
    measured: bool
    reason: str
    benchmark: BenchmarkResult | None = None


def benchmark_analytical_workload(workload: str, operation: Callable[[], object], *, iterations: int = 10, clock: Callable[[], float] = perf_counter) -> BenchmarkResult:
    """Run a bounded, repeatable caller-supplied dataset/cohort/experiment operation."""
    if not workload.strip() or iterations < 1:
        raise ValueError("benchmark requires a workload name and positive iterations")
    durations = []
    for _ in range(iterations):
        started = clock()
        operation()
        durations.append(max(0.0, (clock() - started) * 1000))
    ordered = sorted(durations)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * .95 + .999999) - 1))
    return BenchmarkResult(workload, iterations, round(median(durations), 3), round(ordered[index], 3))


def select_analytical_engine(benchmark: BenchmarkResult | None, *, p95_budget_ms: float, minimum_iterations: int = 10) -> AnalyticalStorageDecision:
    """Keep relational projections until measured p95 latency exceeds the declared budget."""
    if p95_budget_ms <= 0 or minimum_iterations < 1:
        raise ValueError("budget and minimum iterations must be positive")
    if benchmark is None:
        return AnalyticalStorageDecision(AnalyticalEngine.RELATIONAL_PROJECTION, False, "no measured workload; distributed or columnar storage is not selected")
    if benchmark.iterations < minimum_iterations:
        return AnalyticalStorageDecision(AnalyticalEngine.RELATIONAL_PROJECTION, False, "insufficient benchmark iterations for an infrastructure decision", benchmark)
    if benchmark.p95_ms <= p95_budget_ms:
        return AnalyticalStorageDecision(AnalyticalEngine.RELATIONAL_PROJECTION, True, "measured relational projection is within the p95 budget", benchmark)
    return AnalyticalStorageDecision(AnalyticalEngine.COLUMNAR, True, "measured relational projection exceeds the p95 budget", benchmark)
