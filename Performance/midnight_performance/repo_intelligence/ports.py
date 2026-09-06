"""Provider-neutral ports for Repo Intelligent.

Every network, model, embedding, memory, and persistence boundary is a
port with an explicit availability report.  The core runs with no
providers configured: optional ports are honestly unavailable, never
silently faked, and no adapter code lives in the core.  Fixture-backed
fakes for tests live with the tests, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol, runtime_checkable

from ..ai_provider import AnalysisRequest, AnalysisResponse
from ..contracts import Identity
from ..memory_bridge import LessonDeliveryResult, MemoryReadResult
from ..query_api import QueryAuthorization, QueryPage, QueryProjection
from .contracts import CostRecord, GraphLink, ProjectIntelligenceJob, ResearchQuestion
from .identities import RepoIdentity
from .sources import EXTERNAL_TEXT_POLICY, SourceClass


@dataclass(frozen=True, slots=True)
class PortAvailability:
    """Honest availability report; an unavailable port must state why."""

    port: str
    available: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.port.strip():
            raise ValueError("port name must not be blank")
        if not self.available and not (self.reason or "").strip():
            raise ValueError("unavailable ports require a reason")


@dataclass(frozen=True, slots=True)
class UntrustedText:
    """External text as inert, provenance-carrying evidence.

    Carries no interpretation surface: downstream code must treat the
    content as data that may contain prompt-injection attempts, never as
    instructions.
    """

    content: str
    content_digest: str
    source_class: SourceClass
    policy_note: str = EXTERNAL_TEXT_POLICY

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise ValueError("untrusted text content must be a string")
        if len(self.content_digest) != 64 or any(c not in "0123456789abcdef" for c in self.content_digest):
            raise ValueError("untrusted text requires a lowercase 64-char hex content digest")


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    """A discovery hit; a candidate pointer, not yet captured evidence."""

    provider: str
    locator: str
    title: str
    source_class: SourceClass
    relevance: float | None = None

    def __post_init__(self) -> None:
        for label, value in (("provider", self.provider), ("locator", self.locator), ("title", self.title)):
            if not value.strip():
                raise ValueError(f"discovered sources require a non-blank {label}")
        if self.relevance is not None and not 0.0 <= self.relevance <= 1.0:
            raise ValueError("relevance must be between zero and one")


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """One fetched external document: an ExternalSourceRef plus untrusted text."""

    source_ref: object
    text: UntrustedText

    def __post_init__(self) -> None:
        from .contracts import ExternalSourceRef

        if not isinstance(self.source_ref, ExternalSourceRef):
            raise ValueError("fetched documents require an ExternalSourceRef")
        if self.source_ref.content_digest != self.text.content_digest:
            raise ValueError("fetched document digest must match the untrusted text digest")


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    """One embedding with explicit model provenance."""

    model: str
    dim: int
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("embeddings require a model name")
        if self.dim < 1:
            raise ValueError("embedding dim must be positive")
        if len(self.values) != self.dim:
            raise ValueError("embedding values must match dim")
        if any(not isinstance(v, float) or v != v or v in (float("inf"), float("-inf")) for v in self.values):
            raise ValueError("embedding values must be finite floats")


@dataclass(frozen=True, slots=True)
class BudgetGrant:
    """A budget decision for one job; denial is explicit and reasoned."""

    job: RepoIdentity
    granted: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.granted and not (self.reason or "").strip():
            raise ValueError("denied budget grants require a reason")


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    """Aggregate accounted usage for one project."""

    project: Identity
    model_calls: int = 0
    network_requests: int = 0
    cost_micros: int = 0
    fetched_documents: int = 0

    def __post_init__(self) -> None:
        if self.project.kind.value != "project":
            raise ValueError("budget usage requires a project identity")
        for label, value in (
            ("model_calls", self.model_calls),
            ("network_requests", self.network_requests),
            ("cost_micros", self.cost_micros),
            ("fetched_documents", self.fetched_documents),
        ):
            if value < 0:
                raise ValueError(f"{label} must not be negative")


@dataclass(frozen=True, slots=True)
class GraphProjectionResult:
    """A deterministic, rebuildable overlay projection report."""

    project: Identity
    link_count: int
    generation: str

    def __post_init__(self) -> None:
        if self.project.kind.value != "project":
            raise ValueError("graph projections require a project identity")
        if self.link_count < 0:
            raise ValueError("link_count must not be negative")
        if not self.generation.strip():
            raise ValueError("graph projections require a generation digest")


@runtime_checkable
class ClockPort(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    """The only clock adapter shipped in the core; tests inject fakes."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@runtime_checkable
class BudgetMeterPort(Protocol):
    def authorize(self, job: ProjectIntelligenceJob) -> BudgetGrant: ...
    def record(self, cost: CostRecord) -> None: ...
    def usage(self, project: Identity) -> BudgetUsage: ...


@runtime_checkable
class PerformanceReadsPort(Protocol):
    """Bounded reads through Performance's canonical query surface."""

    def query(
        self,
        authorization: QueryAuthorization,
        *,
        kinds: frozenset | None = None,
        subject: Identity | None = None,
        claim_kinds: frozenset | None = None,
        limit: int = 50,
    ) -> QueryPage: ...

    def projection(self, authorization: QueryAuthorization, name: str) -> QueryProjection: ...


@runtime_checkable
class MemoryBridgePort(Protocol):
    """Qualified Memory context strictly through the supported bridge types."""

    def read_context(self, project_key: str, *, size: int = 20, query: str | None = None) -> MemoryReadResult: ...

    def propose_lesson(self, envelope: Mapping[str, object]) -> LessonDeliveryResult: ...


@runtime_checkable
class RepositoryIntelligencePort(Protocol):
    """Repository structure reads owned by the live repository, not agent prose."""

    def available(self) -> PortAvailability: ...

    def resolve_entity_refs(self, repository_key: str, paths: tuple[str, ...]) -> tuple: ...


@runtime_checkable
class ExternalDiscoveryPort(Protocol):
    def available(self) -> PortAvailability: ...

    def search(self, question: ResearchQuestion, *, limit: int = 10) -> tuple[DiscoveredSource, ...]: ...


@runtime_checkable
class FetchParsePort(Protocol):
    def available(self) -> PortAvailability: ...

    def fetch(self, locator: str, source_class: SourceClass) -> FetchedDocument: ...


@runtime_checkable
class EmbeddingPort(Protocol):
    def available(self) -> PortAvailability: ...

    def embed(self, texts: tuple[str, ...]) -> tuple[EmbeddingVector, ...]: ...


@runtime_checkable
class ModelGenerationPort(Protocol):
    """Satisfied by any Performance ``AnalysisProvider``-shaped adapter."""

    def available(self) -> PortAvailability: ...

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse: ...


@runtime_checkable
class GraphProjectionPort(Protocol):
    def available(self) -> PortAvailability: ...

    def rebuild(self, project: Identity, links: tuple[GraphLink, ...]) -> GraphProjectionResult: ...


_PORT_NAMES = (
    "repository_intelligence",
    "performance_reads",
    "memory_bridge",
    "external_discovery",
    "fetch_parse",
    "embeddings",
    "model_generation",
    "graph_projection",
    "clock",
    "budget_meter",
)


@dataclass(frozen=True, slots=True)
class RepoIntelligenceProviders:
    """Optional provider bundle; every slot may be absent in the core."""

    repository_intelligence: RepositoryIntelligencePort | None = None
    performance_reads: PerformanceReadsPort | None = None
    memory_bridge: MemoryBridgePort | None = None
    external_discovery: ExternalDiscoveryPort | None = None
    fetch_parse: FetchParsePort | None = None
    embeddings: EmbeddingPort | None = None
    model_generation: ModelGenerationPort | None = None
    graph_projection: GraphProjectionPort | None = None
    clock: ClockPort | None = None
    budget_meter: BudgetMeterPort | None = None

    def availability(self) -> tuple[PortAvailability, ...]:
        configured = {
            "repository_intelligence": self.repository_intelligence,
            "performance_reads": self.performance_reads,
            "memory_bridge": self.memory_bridge,
            "external_discovery": self.external_discovery,
            "fetch_parse": self.fetch_parse,
            "embeddings": self.embeddings,
            "model_generation": self.model_generation,
            "graph_projection": self.graph_projection,
            "clock": self.clock,
            "budget_meter": self.budget_meter,
        }
        reports: list[PortAvailability] = []
        for name in _PORT_NAMES:
            port = configured[name]
            if port is None:
                reports.append(
                    PortAvailability(port=name, available=False, reason="no provider configured (optional)")
                )
                continue
            report_method = getattr(port, "available", None)
            if callable(report_method):
                reports.append(report_method())
            else:
                reports.append(PortAvailability(port=name, available=True))
        return tuple(reports)

    def clock_or_default(self) -> ClockPort:
        return self.clock if self.clock is not None else SystemClock()


def require_budget_grant(providers: RepoIntelligenceProviders, job: ProjectIntelligenceJob) -> BudgetGrant:
    """Fail closed: no budget meter configured means no spend is authorized."""
    meter = providers.budget_meter
    if meter is None:
        return BudgetGrant(job=job.identity, granted=False, reason="no budget meter configured")
    return meter.authorize(job)


__all__ = [
    "BudgetGrant",
    "BudgetMeterPort",
    "BudgetUsage",
    "DiscoveredSource",
    "EmbeddingPort",
    "EmbeddingVector",
    "ExternalDiscoveryPort",
    "FetchParsePort",
    "FetchedDocument",
    "GraphProjectionPort",
    "GraphProjectionResult",
    "MemoryBridgePort",
    "ModelGenerationPort",
    "PerformanceReadsPort",
    "PortAvailability",
    "RepoIntelligenceProviders",
    "RepositoryIntelligencePort",
    "SystemClock",
    "UntrustedText",
    "require_budget_grant",
]
