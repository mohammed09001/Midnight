"""Integrated Repo Intelligent 02 qualification and economics contracts.

The layer is intentionally declarative: it consumes recorded scenario and
workload results, never turns missing evidence into a pass, and never treats
an aggregate cost win as acceptable when a workload's quality floor regresses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class QualificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class EconomicVerdict(str, Enum):
    VERIFIED_BENEFIT = "VERIFIED BENEFIT"
    QUALITY_BENEFIT = "QUALITY BENEFIT"
    NO_VERIFIED_BENEFIT = "NO VERIFIED BENEFIT YET"
    REGRESSION = "REGRESSION"


@dataclass(frozen=True, slots=True)
class BaselineSnapshot:
    """Evidence-backed baseline; unavailable commands/platforms stay UNKNOWN."""

    performance: QualificationStatus
    memory: QualificationStatus
    repo_intelligent: QualificationStatus
    desktop: QualificationStatus
    python_runtime: str
    node_runtime: str
    platforms: tuple[tuple[str, QualificationStatus], ...]
    external_provider: QualificationStatus
    commands: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    status: QualificationStatus
    evidence: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("qualification scenarios require a name")


@dataclass(frozen=True, slots=True)
class EconomicsMetrics:
    deterministic_resolutions: int = 0
    cache_reuses: int = 0
    local_retrieval_resolutions: int = 0
    ml_accepts: int = 0
    ml_abstains: int = 0
    ml_escalations: int = 0
    external_calls: int = 0
    small_model_calls: int = 0
    strong_model_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    compute_cost_micros: int = 0
    network_cost_micros: int = 0
    qualified_answers: int = 0
    total_answers: int = 0
    attention_exposures: int = 0
    false_suppressions: int = 0
    false_escalations: int = 0

    def __post_init__(self) -> None:
        values = (
            self.deterministic_resolutions, self.cache_reuses, self.local_retrieval_resolutions,
            self.ml_accepts, self.ml_abstains, self.ml_escalations, self.external_calls,
            self.small_model_calls, self.strong_model_calls, self.tokens_in, self.tokens_out,
            self.latency_ms, self.compute_cost_micros, self.network_cost_micros,
            self.qualified_answers, self.total_answers, self.attention_exposures,
            self.false_suppressions, self.false_escalations,
        )
        if any(value < 0 for value in values):
            raise ValueError("economics metrics cannot be negative")
        if self.qualified_answers > self.total_answers:
            raise ValueError("qualified answers cannot exceed total answers")

    @property
    def total_cost_micros(self) -> int:
        return self.compute_cost_micros + self.network_cost_micros

    @property
    def quality_rate(self) -> float | None:
        return self.qualified_answers / self.total_answers if self.total_answers else None


@dataclass(frozen=True, slots=True)
class WorkloadComparison:
    workload: str
    baseline: EconomicsMetrics
    repo_intelligent_02: EconomicsMetrics
    quality_floor: float
    quality_preserved: bool
    cost_delta_micros: int
    latency_delta_ms: float
    verdict: EconomicVerdict

    def __post_init__(self) -> None:
        if not self.workload.strip() or not 0.0 <= self.quality_floor <= 1.0:
            raise ValueError("workload and quality floor are invalid")


def compare_workload(
    workload: str,
    baseline: EconomicsMetrics,
    repo_intelligent_02: EconomicsMetrics,
    *,
    quality_floor: float,
) -> WorkloadComparison:
    """Compare one workload; quality floors are checked before economics."""
    if not 0.0 <= quality_floor <= 1.0:
        raise ValueError("quality floor must be between zero and one")
    optimized_quality = repo_intelligent_02.quality_rate
    quality_preserved = optimized_quality is not None and optimized_quality >= quality_floor
    cost_delta = repo_intelligent_02.total_cost_micros - baseline.total_cost_micros
    latency_delta = repo_intelligent_02.latency_ms - baseline.latency_ms
    if not quality_preserved:
        verdict = EconomicVerdict.REGRESSION
    elif cost_delta < 0 or latency_delta < 0:
        verdict = EconomicVerdict.VERIFIED_BENEFIT
    elif (repo_intelligent_02.quality_rate or 0.0) > (baseline.quality_rate or 0.0):
        verdict = EconomicVerdict.QUALITY_BENEFIT
    else:
        verdict = EconomicVerdict.NO_VERIFIED_BENEFIT
    return WorkloadComparison(workload, baseline, repo_intelligent_02, quality_floor, quality_preserved, cost_delta, latency_delta, verdict)


@dataclass(frozen=True, slots=True)
class IntegratedQualificationReport:
    scenarios: tuple[ScenarioResult, ...]
    workloads: tuple[WorkloadComparison, ...]
    baseline: BaselineSnapshot
    adversarial: tuple[ScenarioResult, ...] = ()

    @property
    def goal(self) -> QualificationStatus:
        all_results = self.scenarios + self.adversarial
        if any(item.status is QualificationStatus.FAIL for item in all_results):
            return QualificationStatus.FAIL
        if any(item.status is QualificationStatus.UNKNOWN for item in all_results) or any(
            status is QualificationStatus.UNKNOWN for _, status in self.baseline.platforms
        ):
            return QualificationStatus.UNKNOWN
        return QualificationStatus.PASS

    @property
    def economic_verdict(self) -> EconomicVerdict:
        if not self.workloads:
            return EconomicVerdict.NO_VERIFIED_BENEFIT
        if any(item.verdict is EconomicVerdict.REGRESSION for item in self.workloads):
            return EconomicVerdict.REGRESSION
        if any(item.verdict is EconomicVerdict.VERIFIED_BENEFIT for item in self.workloads):
            return EconomicVerdict.VERIFIED_BENEFIT
        if any(item.verdict is EconomicVerdict.QUALITY_BENEFIT for item in self.workloads):
            return EconomicVerdict.QUALITY_BENEFIT
        return EconomicVerdict.NO_VERIFIED_BENEFIT


def build_integrated_report(
    baseline: BaselineSnapshot,
    scenarios: tuple[ScenarioResult, ...],
    workloads: tuple[WorkloadComparison, ...] = (),
    *,
    adversarial: tuple[ScenarioResult, ...] = (),
) -> IntegratedQualificationReport:
    """Build the final report without upgrading unknown or missing evidence."""
    return IntegratedQualificationReport(tuple(scenarios), tuple(workloads), baseline, tuple(adversarial))


__all__ = [
    "BaselineSnapshot", "EconomicVerdict", "EconomicsMetrics", "IntegratedQualificationReport",
    "QualificationStatus", "ScenarioResult", "WorkloadComparison", "build_integrated_report",
    "compare_workload",
]
