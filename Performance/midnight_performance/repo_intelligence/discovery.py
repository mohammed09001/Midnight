"""Bounded, privacy-gated external discovery and explainable relevance ranking.

This module deliberately ships no HTTP client.  Providers live behind the
ports, making fixture tests the release evidence and ensuring private project
material is never uploaded by the core.  A run consumes an already compiled
ResearchQuestion, so question formation and its privacy transform remain
separate, auditable stages.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from time import perf_counter

from .authorization import RepoIntelligenceAuthorization, require_external_access
from .contracts import (
    CacheStatus,
    CostRecord,
    CostResourceKind,
    JobTrigger,
    LineageReceipt,
    ProjectIntelligenceJob,
    QuestionStatus,
    ResearchQuestion,
)
from .identities import RepoIntelligenceKind, deterministic_repo_identity
from .ports import DiscoveredSource, RepoIntelligenceProviders, require_budget_grant
from .runtime_contract import StageReasonCode
from .sources import SourceClass, TrustClass
from ..privacy import PrivacyPolicy, PrivacyViolation


_AUTHORITY = {
    TrustClass.VENDOR_AUTHORITATIVE: 1.0,
    TrustClass.PEER_REVIEWED: 0.9,
    TrustClass.COMMUNITY: 0.45,
    TrustClass.UNVERIFIED: 0.1,
    TrustClass.FIRST_PARTY_LOCAL: 0.0,
}
_SOURCE_TRUST = {
    SourceClass.OFFICIAL_DOCS: TrustClass.VENDOR_AUTHORITATIVE,
    SourceClass.STANDARDS: TrustClass.VENDOR_AUTHORITATIVE,
    SourceClass.PAPERS: TrustClass.PEER_REVIEWED,
    SourceClass.GITHUB_REPOSITORY: TrustClass.COMMUNITY,
    SourceClass.WEB: TrustClass.COMMUNITY,
}


def canonical_locator(locator: str) -> str:
    """Normalize enough URL syntax to prevent duplicate fetches, not identity spoofing."""
    raw = locator.strip()
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    try:
        scheme, remainder = raw.split("://", 1)
    except ValueError as error:
        raise ValueError("external locators must be absolute http(s) URLs") from error
    authority, separator, tail = remainder.partition("/")
    if scheme.lower() not in ("http", "https") or not authority:
        raise ValueError("external locators must be absolute http(s) URLs")
    path_and_query = "/" + tail if separator else "/"
    path, separator, query = path_and_query.partition("?")
    normalized = f"{scheme.lower()}://{authority.lower()}{path.rstrip('/') or '/'}"
    return normalized + (f"?{query}" if separator else "")


@dataclass(frozen=True, slots=True)
class RelevanceScore:
    """Auditable score; popularity is intentionally not an input."""

    project_match: float
    hotspot_match: float
    evidence_quality: float
    source_authority: float
    freshness: float
    novelty: float
    learning_value: float
    diversity: float
    redundancy: float = 0.0
    privacy_risk: float = 0.0
    cost: float = 0.0

    def __post_init__(self) -> None:
        for value in (
            self.project_match, self.hotspot_match, self.evidence_quality,
            self.source_authority, self.freshness, self.novelty,
            self.learning_value, self.diversity, self.redundancy,
            self.privacy_risk, self.cost,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("relevance features must be between zero and one")

    @property
    def total(self) -> float:
        positive = (
            self.project_match + self.hotspot_match + self.evidence_quality +
            self.source_authority + self.freshness + self.novelty +
            self.learning_value + self.diversity
        ) / 8.0
        return round(max(0.0, min(1.0, positive - (self.redundancy + self.privacy_risk + self.cost) / 3.0)), 6)


@dataclass(frozen=True, slots=True)
class RankedDiscovery:
    source: DiscoveredSource
    score: RelevanceScore
    canonical_locator: str
    explanation: str


@dataclass(frozen=True, slots=True)
class DiscoveryRun:
    """The complete bounded result, including an honest no-spend reason."""

    ranked: tuple[RankedDiscovery, ...]
    costs: tuple[CostRecord, ...]
    stopped_reason: str
    reason_code: StageReasonCode | None = None


def score_discovery(hit: DiscoveredSource, *, seen_locators: frozenset[str] = frozenset()) -> RelevanceScore:
    locator = canonical_locator(hit.locator)
    if hit.source_class not in _SOURCE_TRUST:
        raise ValueError("external discovery providers may return only external source classes")
    # Provider relevance is a candidate hint, never a popularity substitute.
    match = hit.relevance if hit.relevance is not None else 0.5
    trust = _SOURCE_TRUST[hit.source_class]
    duplicate = 1.0 if locator in seen_locators else 0.0
    return RelevanceScore(
        project_match=match,
        hotspot_match=match,
        evidence_quality=match,
        source_authority=_AUTHORITY[trust],
        freshness=0.5,  # Search hits carry no capture/publish evidence yet.
        novelty=1.0 - duplicate,
        learning_value=match,
        diversity=0.5,
        redundancy=duplicate,
    )


def rank_discoveries(hits: tuple[DiscoveredSource, ...], *, limit: int, seen_locators: frozenset[str] = frozenset()) -> tuple[RankedDiscovery, ...]:
    """Deduplicate candidates then use stable score/title/URL ordering."""
    if limit < 1:
        raise ValueError("discovery limit must be positive")
    unique: dict[str, DiscoveredSource] = {}
    for hit in hits:
        locator = canonical_locator(hit.locator)
        old = unique.get(locator)
        if old is None or (hit.relevance or 0.0) > (old.relevance or 0.0):
            unique[locator] = hit
    ranked = []
    for locator, hit in unique.items():
        score = score_discovery(hit, seen_locators=seen_locators)
        ranked.append(RankedDiscovery(hit, score, locator, f"authority={score.source_authority:.2f}; candidate match={score.project_match:.2f}; popularity excluded"))
    return tuple(sorted(ranked, key=lambda item: (-item.score.total, item.source.title.lower(), item.canonical_locator))[:limit])


def discover(
    question: ResearchQuestion,
    job: ProjectIntelligenceJob,
    authorization: RepoIntelligenceAuthorization,
    providers: RepoIntelligenceProviders,
    *,
    limit: int = 10,
    seen_locators: frozenset[str] = frozenset(),
    privacy_policy: PrivacyPolicy | None = None,
    lineage_receipt: LineageReceipt | None = None,
) -> DiscoveryRun:
    """Execute exactly one discovery call after every fail-closed gate passes.

    Critical invariant (Execution RI-13): a proactive external research job
    cannot exist without a valid project-scoped Performance lineage receipt,
    except when the user explicitly asked for external research
    (``job.trigger is JobTrigger.USER_PULL``). This is enforced here, at the
    function boundary, rather than only by pipeline convention, so no future
    caller can silently bypass it.
    """
    if question.project != job.project or authorization.project != question.project:
        raise PermissionError("cross-project discovery is denied")
    if lineage_receipt is None and job.trigger is not JobTrigger.USER_PULL:
        raise PermissionError(
            "proactive external research requires a project-scoped Performance lineage receipt "
            "(or an explicit user request via JobTrigger.USER_PULL)"
        )
    if lineage_receipt is not None and lineage_receipt.project != question.project:
        raise PermissionError("cross-project lineage receipt denied")
    if question.status is not QuestionStatus.OPEN:
        code = (
            StageReasonCode.INTERNAL_SUFFICIENT
            if question.status is QuestionStatus.ANSWERED_INTERNAL
            else StageReasonCode.NOT_APPLICABLE
        )
        return DiscoveryRun(
            (), (), f"question is {question.status.value}; no external research is eligible", reason_code=code
        )
    require_external_access(authorization, now=providers.clock_or_default().now())
    # Local import: research_security.py imports canonical_locator from this
    # module, so a module-level import here would be circular.
    from .research_security import prepare_outbound_query

    try:
        safe_query_text = prepare_outbound_query(
            question.question_text, authorization, privacy_policy or PrivacyPolicy()
        )
    except PrivacyViolation as exc:
        return DiscoveryRun((), (), str(exc), reason_code=StageReasonCode.PRIVACY_DENIED)
    if providers.external_discovery is None:
        return DiscoveryRun((), (), "external discovery provider unavailable")
    if not providers.external_discovery.available().available:
        return DiscoveryRun((), (), "external discovery provider unavailable")
    if job.budget.max_network_requests == 0:
        return DiscoveryRun((), (), "job network budget is zero")
    grant = require_budget_grant(providers, job)
    if not grant.granted:
        return DiscoveryRun((), (), f"budget denied: {grant.reason}")

    started = perf_counter()
    safe_question = replace(question, question_text=safe_query_text)
    hits = providers.external_discovery.search(safe_question, limit=limit)
    elapsed = round((perf_counter() - started) * 1000, 3)
    now: datetime = providers.clock_or_default().now()
    cost = CostRecord(
        identity=deterministic_repo_identity(RepoIntelligenceKind.COST_RECORD, f"{job.identity.canonical}|search|{question.identity.canonical}"),
        project=job.project, job=job.identity, resource=CostResourceKind.EXTERNAL_SEARCH,
        provider="external_discovery", latency_ms=elapsed, occurred_at=now,
        cache_status=CacheStatus.MISS, budget_authorized=True,
    )
    if providers.budget_meter is not None:
        providers.budget_meter.record(cost)
    ranked = rank_discoveries(tuple(hits), limit=limit, seen_locators=seen_locators)
    return DiscoveryRun(ranked, (cost,), "no candidates" if not ranked else "discovery complete; fetch requires a separate relevance gate")


__all__ = ["DiscoveryRun", "RankedDiscovery", "RelevanceScore", "canonical_locator", "discover", "rank_discoveries", "score_discovery"]
