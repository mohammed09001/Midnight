"""Passive, bring-your-own coding-harness observation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class Capability(str, Enum):
    PROMPT = "prompt"
    SESSION_LIFECYCLE = "session_lifecycle"
    TURN_LIFECYCLE = "turn_lifecycle"
    MODEL_METADATA = "model_metadata"
    TOOL_CALL = "tool_call"
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    SUBAGENT = "subagent"
    PERMISSION = "permission"
    VERIFICATION = "verification"
    COMPLETION = "completion"
    USAGE = "usage"
    NATIVE_DIFF = "native_diff"
    TRANSCRIPT = "transcript"


@dataclass(frozen=True, slots=True)
class ObservationAdapter:
    name: str
    version: str
    capabilities: frozenset[Capability]
    integration_modes: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("adapter name and version are required")
        forbidden = {"launch", "terminal-wrapper", "provider-auth", "worktree-orchestration"}
        if forbidden & self.integration_modes:
            raise ValueError("observation adapters must not host or orchestrate coding harnesses")

    def gap(self, capability: Capability) -> str | None:
        if capability not in self.capabilities:
            return f"unavailable:{capability.value}"
        return None

    def declared_gaps(self) -> Mapping[Capability, str]:
        return {capability: self.gap(capability) for capability in Capability if self.gap(capability) is not None}
