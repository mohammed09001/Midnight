"""Passive normalizer for supplied Claude Code hook payloads."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .harness import Capability, ObservationAdapter

CLAUDE_ADAPTER = ObservationAdapter("claude-code", "1", frozenset({Capability.SESSION_LIFECYCLE, Capability.PROMPT, Capability.TOOL_CALL, Capability.FILE_CHANGE, Capability.SUBAGENT, Capability.PERMISSION, Capability.COMPLETION, Capability.TRANSCRIPT}), frozenset({"approved-native-hook"}))
_KNOWN = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "StopFailure", "SubagentStart", "SubagentStop", "PermissionRequest", "SessionEnd", "PreCompact"}

@dataclass(frozen=True, slots=True)
class ClaudeObservation:
    hook: str
    session_id: str | None
    payload: Mapping[str, Any]
    gaps: tuple[str, ...] = ()

def normalize_claude_hook(raw: Mapping[str, Any], *, transcript_enabled: bool = False) -> ClaudeObservation:
    hook = raw.get("hook_event_name")
    if not isinstance(hook, str) or not hook:
        raise ValueError("Claude hook requires hook_event_name")
    gaps = [] if hook in _KNOWN else [f"unavailable:unrecognized-hook:{hook}"]
    if raw.get("session_id") is None:
        gaps.append("unavailable:session_id")
    if raw.get("transcript_path") and not transcript_enabled:
        gaps.append("unavailable:transcript:privacy-disabled")
    return ClaudeObservation(hook, raw.get("session_id") if isinstance(raw.get("session_id"), str) else None, {k: v for k, v in raw.items() if k not in {"hook_event_name", "session_id", "transcript_path"}}, tuple(gaps))
