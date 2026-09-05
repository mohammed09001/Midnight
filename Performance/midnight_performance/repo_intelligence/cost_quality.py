"""Cost-quality routing, scoped caches, and exact execution accounting."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

from ..contracts import EntityKind, Identity
from .authorization import RepoIntelligenceAuthorization, cache_key, ensure_same_project
from .contracts import CacheStatus, CostRecord, CostResourceKind
from .identities import RepoIdentity, RepoIntelligenceKind, deterministic_repo_identity


class WorkClass(str, Enum):
    DETERMINISTIC = "deterministic"
    RETRIEVAL_ONLY = "retrieval_only"
    CLASSIFICATION_RANKING = "classification_ranking"
    SEMANTIC_MATCHING = "semantic_matching"
    BOUNDED_SYNTHESIS = "bounded_synthesis"
    DEEP_CROSS_SOURCE_REASONING = "deep_cross_source_reasoning"


class MethodTier(str, Enum):
    DETERMINISTIC = "deterministic_local"
    RETRIEVAL = "lexical_graph_retrieval"
    EMBEDDING = "embedding"
    SMALL_MODEL = "small_model"
    EXTERNAL = "targeted_external"
    STRONG_MODEL = "strong_model"


class CacheKind(str, Enum):
    SOURCE_CONTENT = "source_content"
    PARSED_DOCUMENT = "parsed_document"
    EMBEDDING = "embedding"
    SEARCH_RESULT = "search_result"
    RELEVANCE = "relevance"
    GRAPH_SUMMARY = "graph_summary"
    SYNTHESIS = "synthesis"


@dataclass(frozen=True, slots=True)
class TaskProfile:
    project: Identity
    job: RepoIdentity
    work_class: WorkClass
    task_key: str
    required_quality: float
    uncertainty: float
    freshness_need: float
    privacy_risk: float
    expected_information_gain: float
    estimated_cost_micros: int
    latency_class: str
    evidence_set_hash: str
    template_version: str = "1"
    model_family: str = "provider-neutral"

    def __post_init__(self) -> None:
        if self.project.kind is not EntityKind.PROJECT or self.job.kind is not RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB:
            raise ValueError("routing profiles require project and job identities")
        if not self.task_key.strip() or not self.latency_class.strip() or not self.evidence_set_hash.strip():
            raise ValueError("routing profiles require task, latency, and evidence-set identities")
        if any(not 0 <= value <= 1 for value in (self.required_quality, self.uncertainty, self.freshness_need, self.privacy_risk, self.expected_information_gain)):
            raise ValueError("routing quality features must be between zero and one")
        if self.estimated_cost_micros < 0:
            raise ValueError("estimated cost must not be negative")


@dataclass(frozen=True, slots=True)
class Spend:
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    remote_bytes: int = 0
    wall_time_ms: float = 0
    strong_model_calls: int = 0
    search_fetch_calls: int = 0
    cost_micros: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in (self.requests, self.tokens_in, self.tokens_out, self.remote_bytes, self.wall_time_ms, self.strong_model_calls, self.search_fetch_calls, self.cost_micros)):
            raise ValueError("spend cannot be negative")

    def plus(self, other: "Spend") -> "Spend":
        return Spend(*(getattr(self, name) + getattr(other, name) for name in self.__dataclass_fields__))


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    requests: int
    tokens_in: int
    tokens_out: int
    remote_bytes: int
    wall_time_ms: float
    strong_model_calls: int
    search_fetch_calls: int
    cost_micros: int


@dataclass(slots=True)
class BudgetLedger:
    limits: BudgetLimits
    used: Spend = field(default_factory=Spend)

    def allows(self, spend: Spend) -> bool:
        projected = self.used.plus(spend)
        return all(getattr(projected, name) <= getattr(self.limits, name) for name in self.limits.__dataclass_fields__)

    def consume(self, spend: Spend) -> None:
        if not self.allows(spend):
            raise RuntimeError("hard budget exhausted")
        self.used = self.used.plus(spend)


@dataclass(frozen=True, slots=True)
class MethodResult:
    output: str
    evidence_coverage: float
    uncertainty: float
    spend: Spend = Spend()

    def __post_init__(self) -> None:
        if not 0 <= self.evidence_coverage <= 1 or not 0 <= self.uncertainty <= 1:
            raise ValueError("method quality measures must be between zero and one")

class PricedExecutor(Protocol):
    def estimate(self, tier: MethodTier, profile: TaskProfile) -> Spend: ...
    def execute(self, tier: MethodTier, profile: TaskProfile) -> MethodResult: ...


@dataclass(frozen=True, slots=True)
class CacheEntry:
    project: Identity
    value: MethodResult
    stored_at: datetime
    expires_at: datetime
    evidence_set_hash: str


class ScopedCaches:
    """Distinct, project-bound ephemeral caches; persistence may implement this API."""

    def __init__(self, project: Identity) -> None:
        if project.kind is not EntityKind.PROJECT:
            raise ValueError("scoped caches require a project")
        self.project = project
        self._entries: dict[CacheKind, dict[str, CacheEntry]] = {kind: {} for kind in CacheKind}

    def get(self, kind: CacheKind, key: str, *, project: Identity, now: datetime, evidence_set_hash: str) -> MethodResult | None:
        if project != self.project:
            raise PermissionError("cross-project cache read denied")
        entry = self._entries[kind].get(key)
        if entry is None or entry.expires_at < now or entry.evidence_set_hash != evidence_set_hash:
            return None
        return entry.value

    def put(self, kind: CacheKind, key: str, value: MethodResult, *, project: Identity, now: datetime, ttl: timedelta, evidence_set_hash: str) -> None:
        if project != self.project:
            raise PermissionError("cross-project cache write denied")
        if ttl <= timedelta(0):
            raise ValueError("cache TTL must be positive")
        self._entries[kind][key] = CacheEntry(project, value, now, now + ttl, evidence_set_hash)


@dataclass(frozen=True, slots=True)
class RouteResult:
    output: str | None
    accepted_tier: MethodTier | None
    attempted_tiers: tuple[MethodTier, ...]
    costs: tuple[CostRecord, ...]
    cache_hit: bool
    gap: str | None
    final_spend: Spend


_LADDERS = {
    WorkClass.DETERMINISTIC: (MethodTier.DETERMINISTIC,),
    WorkClass.RETRIEVAL_ONLY: (MethodTier.RETRIEVAL, MethodTier.EMBEDDING),
    WorkClass.CLASSIFICATION_RANKING: (MethodTier.DETERMINISTIC, MethodTier.SMALL_MODEL, MethodTier.STRONG_MODEL),
    WorkClass.SEMANTIC_MATCHING: (MethodTier.RETRIEVAL, MethodTier.EMBEDDING, MethodTier.SMALL_MODEL),
    WorkClass.BOUNDED_SYNTHESIS: (MethodTier.RETRIEVAL, MethodTier.SMALL_MODEL, MethodTier.STRONG_MODEL),
    WorkClass.DEEP_CROSS_SOURCE_REASONING: (MethodTier.RETRIEVAL, MethodTier.SMALL_MODEL, MethodTier.EXTERNAL, MethodTier.STRONG_MODEL),
}


def _resource(tier: MethodTier) -> CostResourceKind:
    if tier is MethodTier.EMBEDDING:
        return CostResourceKind.EMBEDDING
    if tier in (MethodTier.SMALL_MODEL, MethodTier.STRONG_MODEL):
        return CostResourceKind.MODEL_INFERENCE
    if tier is MethodTier.EXTERNAL:
        return CostResourceKind.EXTERNAL_FETCH
    return CostResourceKind.LOCAL_COMPUTE


def _cache_kind(profile: TaskProfile) -> CacheKind:
    return CacheKind.SYNTHESIS if profile.work_class in (WorkClass.BOUNDED_SYNTHESIS, WorkClass.DEEP_CROSS_SOURCE_REASONING) else CacheKind.RELEVANCE


def route(profile: TaskProfile, authorization: RepoIntelligenceAuthorization, executor: PricedExecutor, caches: ScopedCaches, budget: BudgetLedger, *, now: datetime, ttl: timedelta = timedelta(hours=1)) -> RouteResult:
    ensure_same_project(authorization, project=profile.project)
    material = hashlib.sha256(f"{profile.task_key}|{profile.evidence_set_hash}|{profile.template_version}|{profile.model_family}".encode()).hexdigest()
    key = cache_key(_cache_kind(profile).value, profile.project, material)
    cached = caches.get(_cache_kind(profile), key, project=profile.project, now=now, evidence_set_hash=profile.evidence_set_hash)
    if cached is not None and cached.evidence_coverage >= profile.required_quality and cached.uncertainty <= profile.uncertainty:
        return RouteResult(cached.output, None, (), (), True, None, budget.used)

    attempted: list[MethodTier] = []
    costs: list[CostRecord] = []
    for index, tier in enumerate(_LADDERS[profile.work_class]):
        estimate = executor.estimate(tier, profile)
        if not budget.allows(estimate):
            return RouteResult(None, None, tuple(attempted), tuple(costs), False, f"hard budget prevented {tier.value}; quality gap remains", budget.used)
        result = executor.execute(tier, profile)
        if not budget.allows(result.spend):
            raise RuntimeError("provider exceeded its authorized preflight estimate")
        budget.consume(result.spend)
        attempted.append(tier)
        cost = CostRecord(deterministic_repo_identity(RepoIntelligenceKind.COST_RECORD, f"{profile.job.canonical}|{tier.value}|{index}"), profile.project, profile.job, _resource(tier), "cost-quality-router", result.spend.wall_time_ms, now, CacheStatus.MISS, tokens_in=result.spend.tokens_in, tokens_out=result.spend.tokens_out, cost_micros=result.spend.cost_micros)
        costs.append(cost)
        if result.evidence_coverage >= profile.required_quality and result.uncertainty <= profile.uncertainty:
            caches.put(_cache_kind(profile), key, result, project=profile.project, now=now, ttl=ttl, evidence_set_hash=profile.evidence_set_hash)
            return RouteResult(result.output, tier, tuple(attempted), tuple(costs), False, None, budget.used)
    return RouteResult(None, None, tuple(attempted), tuple(costs), False, "all allowed methods failed the evidence coverage or uncertainty gate", budget.used)


def prune_communities(communities: tuple[tuple[str, float], ...], *, relevance_threshold: float, maximum: int) -> tuple[str, ...]:
    """Early relevance pruning before any community summary/model work."""
    if maximum < 0 or not 0 <= relevance_threshold <= 1:
        raise ValueError("invalid community pruning controls")
    eligible = ((name, score) for name, score in communities if score >= relevance_threshold)
    return tuple(name for name, _ in sorted(eligible, key=lambda item: (-item[1], item[0]))[:maximum])


__all__ = ["BudgetLedger", "BudgetLimits", "CacheKind", "MethodResult", "MethodTier", "RouteResult", "ScopedCaches", "Spend", "TaskProfile", "WorkClass", "prune_communities", "route"]
