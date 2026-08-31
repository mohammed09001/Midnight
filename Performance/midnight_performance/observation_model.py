"""Provider-neutral observation envelope with narrow OpenTelemetry mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .contracts import ClaimKind, EntityKind, Identity, Observation


OBSERVATION_SCHEMA_VERSION = 1


class ObservationLayer(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"
    DERIVED = "derived"


class ObservationType(str, Enum):
    PROMPT = "prompt"
    AGENT_LIFECYCLE = "agent_lifecycle"
    MODEL_USAGE = "model_usage"
    TOOL = "tool"
    COMMAND = "command"
    FILE_EDIT = "file_edit"
    SESSION_BOUNDARY = "session_boundary"
    TURN_BOUNDARY = "turn_boundary"
    VERIFICATION = "verification"
    REPOSITORY_CHANGE = "repository_change"
    FEEDBACK = "feedback"
    EXTERNAL_OUTCOME = "external_outcome"


class EvidenceSourceKind(str, Enum):
    PROVIDER_HOOK = "provider_hook"
    PLUGIN_EVENT = "plugin_event"
    TRANSCRIPT = "transcript"
    COMMAND_RESULT = "command_result"
    VCS_OPERATION = "vcs_operation"
    FILESYSTEM_BASELINE = "filesystem_baseline"
    CI_RESULT = "ci_result"
    USER_FEEDBACK = "user_feedback"
    WATCH_RUNTIME = "watch_runtime"
    WATCH_DATA = "watch_data"
    SECURITY = "security"
    EXTERNAL_AI = "external_ai"
    EVALUATOR = "evaluator"


@dataclass(frozen=True, slots=True)
class ObservationEnvelope:
    """A versioned envelope that never conflates raw events and derived analysis."""

    observation: Observation
    project: Identity
    observation_type: ObservationType
    layer: ObservationLayer
    provider: str
    provider_event_id: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    source_kind: EvidenceSourceKind = EvidenceSourceKind.PROVIDER_HOOK
    source_sequence: int | None = None
    integrity_checksum: str | None = None
    signer: str | None = None
    schema_version: int = OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.project.kind is not EntityKind.PROJECT:
            raise ValueError("envelopes must belong to a Performance project")
        if not self.provider.strip() or not self.provider_event_id.strip():
            raise ValueError("provider and provider_event_id are required for provenance")
        if self.schema_version < 1:
            raise ValueError("envelope schema version must be positive")
        if self.source_sequence is not None and self.source_sequence < 0:
            raise ValueError("source sequence must not be negative")
        if self.integrity_checksum is not None and (len(self.integrity_checksum) != 64 or any(char not in "0123456789abcdef" for char in self.integrity_checksum)):
            raise ValueError("integrity checksum must be a lowercase SHA-256 hex digest")
        if self.signer is not None and not self.signer.strip():
            raise ValueError("signer must be non-empty when supplied")
        if self.layer is ObservationLayer.DERIVED and self.observation.claim_kind is ClaimKind.OBSERVED:
            raise ValueError("derived envelopes cannot claim observed evidence")
        if self.layer is not ObservationLayer.DERIVED and self.observation.claim_kind is ClaimKind.DERIVED:
            raise ValueError("derived claim requires a derived envelope")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.to_dict(),
            "project": self.project.canonical,
            "observation_type": self.observation_type.value,
            "layer": self.layer.value,
            "provider": self.provider,
            "provider_event_id": self.provider_event_id,
            "attributes": dict(self.attributes),
            "source_kind": self.source_kind.value,
            "source_sequence": self.source_sequence,
            "integrity_checksum": self.integrity_checksum,
            "signer": self.signer,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ObservationEnvelope":
        return cls(
            observation=Observation.from_dict(raw["observation"]),
            project=Identity.parse(str(raw["project"])),
            observation_type=ObservationType(raw["observation_type"]),
            layer=ObservationLayer(raw["layer"]),
            provider=str(raw["provider"]),
            provider_event_id=str(raw["provider_event_id"]),
            attributes=dict(raw.get("attributes", {})),
            source_kind=EvidenceSourceKind(raw.get("source_kind", EvidenceSourceKind.PROVIDER_HOOK.value)),
            source_sequence=int(raw["source_sequence"]) if raw.get("source_sequence") is not None else None,
            integrity_checksum=str(raw["integrity_checksum"]) if raw.get("integrity_checksum") is not None else None,
            signer=str(raw["signer"]) if raw.get("signer") is not None else None,
            schema_version=int(raw.get("schema_version", OBSERVATION_SCHEMA_VERSION)),
        )


def from_opentelemetry(attributes: Mapping[str, Any], observation: Observation, project: Identity, *, provider_event_id: str) -> ObservationEnvelope:
    """Import the stable GenAI keys without adopting OTel as Performance's model."""
    operation = str(attributes.get("gen_ai.operation.name", "agent"))
    mapped = {
        "chat": ObservationType.MODEL_USAGE,
        "invoke_agent": ObservationType.AGENT_LIFECYCLE,
        "execute_tool": ObservationType.TOOL,
    }.get(operation, ObservationType.AGENT_LIFECYCLE)
    return ObservationEnvelope(
        observation=observation,
        project=project,
        observation_type=mapped,
        layer=ObservationLayer.NORMALIZED,
        provider=str(attributes.get("gen_ai.provider.name", "opentelemetry")),
        provider_event_id=provider_event_id,
        attributes={key: value for key, value in attributes.items() if key.startswith("gen_ai.")},
    )


def to_opentelemetry(envelope: ObservationEnvelope) -> dict[str, Any]:
    """Export interoperable semantics only; Performance entities stay in its envelope."""
    result = dict(envelope.attributes)
    result.setdefault("gen_ai.provider.name", envelope.provider)
    result["midnight.performance.observation_type"] = envelope.observation_type.value
    result["midnight.performance.layer"] = envelope.layer.value
    return result
