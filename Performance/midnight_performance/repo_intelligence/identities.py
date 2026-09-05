"""Stable identities for Midnight Repo Intelligent derived state.

Repo Intelligent is a project-scoped intelligence extension of Midnight
Performance.  It owns only its derived project-intelligence state, so its
records carry their own ``ri:`` identity namespace instead of extending
Performance's ``mp:`` entity-kind vocabulary.  References to Performance
entities keep using the canonical ``mp:`` identities owned by Performance;
references to Memory stay ``ExternalReference`` pointers owned by the
memory bridge.  Nothing here opens a sibling database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import NAMESPACE_URL, UUID, uuid5


REPO_INTELLIGENCE_CONTRACT_VERSION = 1

_IDENTITY_NAMESPACE = "midnight-repo-intelligent"

CANONICAL_PREFIX = "ri"


class RepoIntelligenceKind(str, Enum):
    """Record kinds Repo Intelligent durably owns."""

    PROJECT_INTELLIGENCE_JOB = "project_intelligence_job"
    INTERNAL_SIGNAL = "internal_signal"
    PROJECT_ENTITY_REF = "project_entity_ref"
    EXTERNAL_SOURCE_REF = "external_source_ref"
    RESEARCH_QUESTION = "research_question"
    EVIDENCE_BUNDLE = "evidence_bundle"
    PROJECT_INSIGHT = "project_insight"
    LINEAGE_RECEIPT = "lineage_receipt"
    GRAPH_LINK = "graph_link"
    EXPOSURE = "exposure"
    LEARNING_OUTCOME = "learning_outcome"
    COST_RECORD = "cost_record"
    CONCEPT = "concept"
    MEMORY_REF = "memory_ref"
    ANALOGY_RECORD = "analogy_record"


@dataclass(frozen=True, slots=True)
class RepoIdentity:
    """A stable Repo Intelligent identity, including its contract version."""

    kind: RepoIntelligenceKind
    value: UUID
    version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("repo intelligence identity version must be positive")

    @property
    def canonical(self) -> str:
        return f"{CANONICAL_PREFIX}:v{self.version}:{self.kind.value}:{self.value}"

    @classmethod
    def parse(cls, raw: str) -> "RepoIdentity":
        prefix, version, kind, value = raw.split(":", 3)
        if prefix != CANONICAL_PREFIX or not version.startswith("v"):
            raise ValueError("not a Midnight Repo Intelligent identity")
        return cls(RepoIntelligenceKind(kind), UUID(value), int(version[1:]))


def deterministic_repo_identity(
    kind: RepoIntelligenceKind,
    stable_key: str,
    *,
    version: int = REPO_INTELLIGENCE_CONTRACT_VERSION,
) -> RepoIdentity:
    """Create a replay-stable identity from a project-bound stable key."""
    if not stable_key.strip():
        raise ValueError("deterministic repo intelligence identities require a stable key")
    value = uuid5(NAMESPACE_URL, f"{_IDENTITY_NAMESPACE}:v{version}:{kind.value}:{stable_key}")
    return RepoIdentity(kind=kind, value=value, version=version)


def is_repo_intelligence_canonical(raw: str) -> bool:
    """True when ``raw`` parses as a Repo Intelligent canonical identity."""
    try:
        RepoIdentity.parse(raw)
    except (ValueError, AttributeError):
        return False
    return True


def is_performance_canonical(raw: str) -> bool:
    """True when ``raw`` parses as a Performance ``mp:`` canonical identity.

    Import is deferred so this module stays importable without pulling the
    Performance contract surface into identity-only callers.
    """
    from ..contracts import Identity

    try:
        Identity.parse(raw)
    except (ValueError, AttributeError):
        return False
    return True
