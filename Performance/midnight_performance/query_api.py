"""Versioned, bounded, project-scoped read API for Performance evidence.

The ledger remains the canonical evidence owner.  This facade deliberately has
no storage handles other than its own project's ledger and accepts projections
only as already-built, explicitly qualified read models.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping

from .analysis import AnalysisDescriptor, AnalysisResult, Reprocessor
from .contracts import ClaimKind, EntityKind, Identity
from .episode import Episode, EpisodeProjector
from .ledger import EvidenceLedger
from .observation_model import ObservationEnvelope


QUERY_API_VERSION = 1
_MAX_LIMIT = 100


class QueryResource(str, Enum):
    """Stable resource names exposed by the query contract."""

    PROMPT_RUNS = "prompt_runs"
    AGENT_RUNS = "agent_runs"
    CHANGE_SETS = "change_sets"
    ANALYSES = "analyses"
    METRICS = "metrics"
    VERIFICATION = "verification"
    FEEDBACK = "feedback"
    OUTCOMES = "outcomes"
    EPISODES = "episodes"
    DATASETS = "datasets"
    EXPERIMENTS = "experiments"
    MODELS = "models"
    MEMORY = "memory"
    SIMILARITY = "similarity"
    RELATIONSHIPS = "relationships"
    RECOMMENDATIONS = "recommendations"


@dataclass(frozen=True, slots=True)
class QueryAuthorization:
    """Server-issued read capability; callers cannot select another project."""

    project: Identity
    allowed_kinds: frozenset[EntityKind] = frozenset(EntityKind)
    may_request_analysis: bool = False

    def __post_init__(self) -> None:
        if self.project.kind is not EntityKind.PROJECT:
            raise ValueError("query authorization requires a project identity")


@dataclass(frozen=True, slots=True)
class QueryPage:
    api_version: int
    project: Identity
    items: tuple[ObservationEnvelope, ...]
    total_matching: int
    limit: int
    offset: int = 0

    def __post_init__(self) -> None:
        if self.total_matching < 0 or self.limit < 1 or self.offset < 0:
            raise ValueError("query page counts, limit, and offset must be bounded")
        if len(self.items) > self.limit:
            raise ValueError("query page cannot contain more items than its limit")

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total_matching


@dataclass(frozen=True, slots=True)
class QueryProjection:
    """A rebuildable read model, never an authority upgrade or database proxy."""

    name: str
    version: str
    claim_kind: ClaimKind
    records: tuple[Mapping[str, object], ...]
    provenance: tuple[str, ...]
    uncertainty: str

    def __post_init__(self) -> None:
        if not all((self.name.strip(), self.version.strip(), self.uncertainty.strip())):
            raise ValueError("projection name, version, and uncertainty are required")
        if self.claim_kind is ClaimKind.OBSERVED:
            raise ValueError("projections must not represent themselves as raw observed evidence")


class PerformanceQueryAPI:
    """A small read facade for evidence, episodes, qualified projections, and reprocessing."""

    def __init__(self, ledger: EvidenceLedger, *, projections: Mapping[str, QueryProjection] = ()) -> None:
        self._ledger = ledger
        self._projections = dict(projections)
        if any(name != projection.name for name, projection in self._projections.items()):
            raise ValueError("projection map keys must match projection names")

    @property
    def project(self) -> Identity:
        return self._ledger.project

    def query_evidence(
        self,
        authorization: QueryAuthorization,
        *,
        kinds: frozenset[EntityKind] | None = None,
        subject: Identity | None = None,
        claim_kinds: frozenset[ClaimKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> QueryPage:
        """Read one stable slice of matching evidence.

        ``offset`` is deliberately explicit rather than a hidden cursor because
        the underlying append-only ledger is replayed locally.  Callers that
        need more than one page must compare ``total_matching`` between pages
        and report truncation/staleness if the matching set changes while they
        paginate.
        """
        self._authorize(authorization)
        if not 1 <= limit <= _MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")
        if offset < 0:
            raise ValueError("offset must not be negative")
        selected_kinds = authorization.allowed_kinds if kinds is None else kinds
        if not selected_kinds <= authorization.allowed_kinds:
            raise PermissionError("requested evidence kind is not authorized")
        matching = tuple(
            envelope for envelope in self._ledger.replay()
            if envelope.observation.identity.kind in selected_kinds
            and (subject is None or envelope.observation.subject == subject)
            and (claim_kinds is None or envelope.observation.claim_kind in claim_kinds)
        )
        return QueryPage(
            QUERY_API_VERSION,
            self.project,
            matching[offset:offset + limit],
            len(matching),
            limit,
            offset,
        )

    def episodes(self, authorization: QueryAuthorization, *, limit: int = 50) -> tuple[Episode, ...]:
        self._authorize(authorization)
        if not 1 <= limit <= _MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")
        observations = tuple(
            envelope.observation for envelope in self._ledger.replay()
            if envelope.observation.identity.kind in authorization.allowed_kinds
        )
        episodes = EpisodeProjector().rebuild(observations)
        return tuple(episodes[key] for key in sorted(episodes, key=lambda item: item.canonical))[:limit]

    def projection(self, authorization: QueryAuthorization, name: str) -> QueryProjection:
        self._authorize(authorization)
        try:
            return self._projections[name]
        except KeyError as exc:
            raise KeyError(f"unknown Performance projection: {name}") from exc

    def list_projections(self, authorization: QueryAuthorization) -> tuple[tuple[str, str], ...]:
        self._authorize(authorization)
        return tuple(sorted((item.name, item.version) for item in self._projections.values()))

    def resources(self, authorization: QueryAuthorization) -> tuple[QueryResource, ...]:
        """Return the complete API vocabulary, including resources with no records."""
        self._authorize(authorization)
        return tuple(QueryResource)

    def request_analysis(
        self,
        authorization: QueryAuthorization,
        descriptor: AnalysisDescriptor,
        analyzer: Callable[[tuple[ObservationEnvelope, ...]], Mapping[str, object]],
    ) -> AnalysisResult:
        self._authorize(authorization)
        if not authorization.may_request_analysis:
            raise PermissionError("analysis requests require explicit authorization")
        # Reprocessing is user-invoked and pure: it does not append evidence or change agent execution.
        return Reprocessor().run(descriptor, tuple(self._ledger.replay()), analyzer)

    def _authorize(self, authorization: QueryAuthorization) -> None:
        if authorization.project != self.project:
            raise PermissionError("cross-project Performance reads are rejected")
