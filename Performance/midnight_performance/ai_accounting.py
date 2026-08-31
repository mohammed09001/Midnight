"""Qualified accounting projections for optional AI analysis.

Rows are supplied execution facts.  Summaries are derived comparisons and do
not turn provider output into evidence about repository changes or outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from time import perf_counter
from typing import Callable

from .ai_provider import AnalysisMode, AnalysisProvider, AnalysisRequest, AnalysisResponse, request_provider_analysis
from .contracts import ClaimKind
from .privacy import PrivacyPolicy
from .telemetry import PerformanceMetric, PerformanceTelemetry


@dataclass(frozen=True, slots=True)
class AIAnalysisAttempt:
    provider: str
    provider_version: str
    model: str
    latency_ms: float
    cost: float | None
    succeeded: bool
    evaluator_agreement: float | None = None
    usefulness: float | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not all((self.provider.strip(), self.provider_version.strip(), self.model.strip())):
            raise ValueError("AI accounting requires provider, version, and model")
        if self.latency_ms < 0 or self.cost is not None and self.cost < 0:
            raise ValueError("latency and cost must not be negative")
        if any(value is not None and not 0 <= value <= 1 for value in (self.evaluator_agreement, self.usefulness)):
            raise ValueError("agreement and usefulness must be zero-one when measured")
        if self.succeeded and self.failure_reason is not None:
            raise ValueError("successful analysis cannot have a failure reason")
        if not self.succeeded and not self.failure_reason:
            raise ValueError("failed analysis requires a failure reason")


@dataclass(frozen=True, slots=True)
class AIAccountingSummary:
    provider: str
    provider_version: str
    model: str
    attempts: int
    total_cost: float | None
    mean_latency_ms: float | None
    failure_rate: float
    mean_evaluator_agreement: float | None
    mean_usefulness: float | None
    claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "cost may be unavailable for local models; agreement and usefulness only describe supplied evaluators or labels"


@dataclass(frozen=True, slots=True)
class AccountedAnalysis:
    response: AnalysisResponse | None
    attempt: AIAnalysisAttempt
    error: str | None = None


def execute_accounted_analysis(provider: AnalysisProvider, policy: PrivacyPolicy, request: AnalysisRequest, *, mode: AnalysisMode = AnalysisMode(), clock: Callable[[], float] = perf_counter, telemetry: PerformanceTelemetry | None = None) -> AccountedAnalysis:
    """Execute an explicit provider request and preserve a latency/failure fact for comparison."""
    descriptor = getattr(provider, "descriptor", None)
    provider_name = getattr(descriptor, "provider", "undeclared-provider")
    provider_version = getattr(descriptor, "version", "unknown")
    started = clock()
    try:
        response = request_provider_analysis(provider, policy, request, mode=mode)
    except Exception as exc:
        latency_ms = round(max(0.0, (clock() - started) * 1000), 3)
        if telemetry is not None:
            telemetry.record(PerformanceMetric.ANALYSIS_LATENCY, latency_ms, subject=provider_name, succeeded=False)
            telemetry.record(PerformanceMetric.FAILURE, 1, subject=provider_name, succeeded=False)
        return AccountedAnalysis(None, AIAnalysisAttempt(provider_name, provider_version, "unknown", latency_ms, None, False, failure_reason=type(exc).__name__), type(exc).__name__)
    latency_ms = round(max(0.0, (clock() - started) * 1000), 3)
    if telemetry is not None:
        telemetry.record(PerformanceMetric.ANALYSIS_LATENCY, latency_ms, subject=response.provider, succeeded=True)
        if response.cost is not None:
            telemetry.record(PerformanceMetric.EVALUATOR_COST, response.cost, subject=response.provider, succeeded=True)
    return AccountedAnalysis(response, AIAnalysisAttempt(response.provider, response.provider_version, response.model, latency_ms, response.cost, True))


def summarize_ai_attempts(attempts: tuple[AIAnalysisAttempt, ...]) -> tuple[AIAccountingSummary, ...]:
    """Group comparable provider/model attempts without inventing unavailable values."""
    groups: dict[tuple[str, str, str], list[AIAnalysisAttempt]] = {}
    for item in attempts:
        groups.setdefault((item.provider, item.provider_version, item.model), []).append(item)
    summaries = []
    for key in sorted(groups):
        rows = groups[key]
        costs = [item.cost for item in rows if item.cost is not None]
        agreements = [item.evaluator_agreement for item in rows if item.evaluator_agreement is not None]
        usefulness = [item.usefulness for item in rows if item.usefulness is not None]
        summaries.append(AIAccountingSummary(
            *key, len(rows), round(sum(costs), 6) if costs else None,
            round(mean(item.latency_ms for item in rows), 3),
            round(sum(not item.succeeded for item in rows) / len(rows), 3),
            round(mean(agreements), 3) if agreements else None,
            round(mean(usefulness), 3) if usefulness else None,
        ))
    return tuple(summaries)
