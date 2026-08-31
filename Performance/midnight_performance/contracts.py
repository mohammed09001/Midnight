"""Stable identity and correlation contracts.

The types intentionally encode evidence strength rather than treating model or
agent text as proof.  They contain no sibling database adapters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5


CONTRACT_VERSION = 1


class EntityKind(str, Enum):
    PROJECT = "project"
    WORKSPACE = "workspace"
    REPOSITORY = "repository"
    REPOSITORY_SNAPSHOT = "repository_snapshot"
    PROMPT = "prompt"
    PROMPT_VERSION = "prompt_version"
    PROMPT_RUN = "prompt_run"
    AGENT_RUN = "agent_run"
    AGENT_SESSION = "agent_session"
    AGENT_TURN = "agent_turn"
    TOOL_OBSERVATION = "tool_observation"
    COMMAND_OBSERVATION = "command_observation"
    CHANGE_SET = "change_set"
    FILE_CHANGE = "file_change"
    CODE_REGION = "code_region"
    SYMBOL = "symbol"
    VERIFICATION_RUN = "verification_run"
    FEEDBACK_RECORD = "feedback_record"
    OUTCOME_OBSERVATION = "outcome_observation"
    EPISODE = "episode"
    ANALYSIS_VERSION = "analysis_version"
    DATASET_ITEM = "dataset_item"
    EXPERIMENT_RUN = "experiment_run"
    MODEL_VERSION = "model_version"
    MEMORY_RECORD = "memory_record"
    RECOMMENDATION = "recommendation"


class ClaimKind(str, Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    INFERRED = "inferred"
    STATISTICAL = "statistical"
    PREDICTED = "predicted"
    RECOMMENDED = "recommended"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Identity:
    """A stable Performance-local identity, including its contract version."""

    kind: EntityKind
    value: UUID
    version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("identity version must be positive")

    @property
    def canonical(self) -> str:
        return f"mp:v{self.version}:{self.kind.value}:{self.value}"

    @classmethod
    def parse(cls, raw: str) -> "Identity":
        prefix, version, kind, value = raw.split(":", 3)
        if prefix != "mp" or not version.startswith("v"):
            raise ValueError("not a Midnight Performance identity")
        return cls(EntityKind(kind), UUID(value), int(version[1:]))


def new_identity(kind: EntityKind, *, version: int = CONTRACT_VERSION) -> Identity:
    return Identity(kind=kind, value=uuid4(), version=version)


def deterministic_identity(kind: EntityKind, stable_key: str, *, version: int = CONTRACT_VERSION) -> Identity:
    """Create a replay-stable identity from a provider event key or content hash."""
    if not stable_key.strip():
        raise ValueError("deterministic identities require a stable key")
    return Identity(kind=kind, value=uuid5(NAMESPACE_URL, f"midnight-performance:v{version}:{kind.value}:{stable_key}"), version=version)


@dataclass(frozen=True, slots=True)
class ExternalReference:
    """A correlation pointer, never a cross-product database capability."""

    provider: str
    kind: str
    value: str
    contract_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not all((self.provider.strip(), self.kind.strip(), self.value.strip())):
            raise ValueError("external references require provider, kind, and value")
        if self.contract_version < 1:
            raise ValueError("external reference version must be positive")


@dataclass(frozen=True, slots=True)
class Observation:
    """An immutable, attributable Performance evidence record."""

    identity: Identity
    claim_kind: ClaimKind
    subject: Identity
    payload: Mapping[str, Any]
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "performance"
    episode: Identity | None = None
    external_references: tuple[ExternalReference, ...] = ()
    schema_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.identity.kind not in {
            EntityKind.PROMPT,
            EntityKind.PROMPT_VERSION,
            EntityKind.PROMPT_RUN,
            EntityKind.AGENT_RUN,
            EntityKind.AGENT_SESSION,
            EntityKind.AGENT_TURN,
            EntityKind.TOOL_OBSERVATION,
            EntityKind.COMMAND_OBSERVATION,
            EntityKind.CHANGE_SET,
            EntityKind.FILE_CHANGE,
            EntityKind.VERIFICATION_RUN,
            EntityKind.FEEDBACK_RECORD,
            EntityKind.OUTCOME_OBSERVATION,
            EntityKind.MEMORY_RECORD,
            EntityKind.RECOMMENDATION,
        }:
            raise ValueError("observation identity must use an evidence entity kind")
        if self.episode and self.episode.kind is not EntityKind.EPISODE:
            raise ValueError("episode link must identify an episode")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.schema_version < 1:
            raise ValueError("schema version must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "claim_kind": self.claim_kind.value,
            "subject": self.subject.canonical,
            "payload": dict(self.payload),
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
            "episode": self.episode.canonical if self.episode else None,
            "external_references": [asdict(ref) for ref in self.external_references],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Observation":
        return cls(
            identity=Identity.parse(str(raw["identity"])),
            claim_kind=ClaimKind(str(raw["claim_kind"])),
            subject=Identity.parse(str(raw["subject"])),
            payload=dict(raw["payload"]),
            observed_at=datetime.fromisoformat(str(raw["observed_at"])),
            source=str(raw["source"]),
            episode=Identity.parse(raw["episode"]) if raw.get("episode") else None,
            external_references=tuple(ExternalReference(**ref) for ref in raw.get("external_references", [])),
            schema_version=int(raw.get("schema_version", CONTRACT_VERSION)),
        )
