"""Invisible-by-default interaction policy for Midnight Performance.

Passive intelligence is confined to observation and rebuildable intelligence.
Active intelligence requires an explicit user invocation on a declared surface.
Neither mode can inject prompt context or alter a coding harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


INTERACTION_POLICY_VERSION = 1


class InteractionMode(str, Enum):
    PASSIVE = "passive"
    ACTIVE = "active"


class PassiveOperation(str, Enum):
    OBSERVE = "observe"
    RECORD = "record"
    NORMALIZE = "normalize"
    CORRELATE = "correlate"
    ANALYZE = "analyze"
    INDEX = "index"
    LEARN = "learn"


class ActiveSurface(str, Enum):
    MIDNIGHT_COMMAND = "midnight_command"
    PERFORMANCE_COMMAND = "performance_command"
    DASHBOARD = "dashboard"
    API = "api"
    MCP_HOST = "mcp_host"


@dataclass(frozen=True, slots=True)
class InteractionPolicy:
    """Policy that prevents passive observation from becoming agent intervention."""

    version: int = INTERACTION_POLICY_VERSION
    passive_operations: frozenset[PassiveOperation] = frozenset(PassiveOperation)
    active_surfaces: frozenset[ActiveSurface] = frozenset(ActiveSurface)
    silent_passive: bool = True
    inject_prompt_context: bool = False
    modify_agent_behavior: bool = False

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("interaction policy version must be positive")
        if not self.silent_passive:
            raise ValueError("passive intelligence must remain silent")
        if self.inject_prompt_context or self.modify_agent_behavior:
            raise ValueError("Performance interaction policy must not inject prompt context or modify agent behavior")

    def authorize_passive(self, operation: PassiveOperation) -> InteractionMode:
        if operation not in self.passive_operations:
            raise PermissionError(f"passive operation is disabled: {operation.value}")
        return InteractionMode.PASSIVE

    def authorize_active(self, surface: ActiveSurface, *, explicitly_invoked: bool) -> InteractionMode:
        if not explicitly_invoked:
            raise PermissionError("active intelligence requires explicit user invocation")
        if surface not in self.active_surfaces:
            raise PermissionError(f"active surface is disabled: {surface.value}")
        return InteractionMode.ACTIVE

    def emits_notification(self, mode: InteractionMode) -> bool:
        """Only a response to an already-active invocation may be surfaced."""
        return mode is InteractionMode.ACTIVE
