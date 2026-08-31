"""Pure, passive normalizer for approved Codex lifecycle events.

It consumes supplied native hook/app-server/SDK event dictionaries only. It
does not launch Codex, acquire credentials, wrap a terminal, or infer missing
lifecycle fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .harness import Capability, ObservationAdapter


CODEX_ADAPTER = ObservationAdapter(
    name="codex", version="1",
    capabilities=frozenset({Capability.SESSION_LIFECYCLE, Capability.TURN_LIFECYCLE, Capability.TOOL_CALL, Capability.COMMAND, Capability.FILE_CHANGE, Capability.COMPLETION, Capability.USAGE, Capability.NATIVE_DIFF, Capability.VERIFICATION}),
    integration_modes=frozenset({"approved-native-hook", "app-server-events", "sdk-events"}),
)


@dataclass(frozen=True, slots=True)
class CodexObservation:
    event_type: str
    session_id: str | None
    turn_id: str | None
    item_id: str | None
    payload: Mapping[str, Any]
    gaps: tuple[str, ...] = ()


_EVENT_CAPABILITY = {
    "thread.started": Capability.SESSION_LIFECYCLE,
    "turn.started": Capability.TURN_LIFECYCLE,
    "turn.completed": Capability.COMPLETION,
    "turn.failed": Capability.COMPLETION,
    "turn.interrupted": Capability.COMPLETION,
    "item.command_execution": Capability.COMMAND,
    "item.file_change": Capability.FILE_CHANGE,
    "item.diff_updated": Capability.NATIVE_DIFF,
    "item.tool_progress": Capability.TOOL_CALL,
    "turn.usage": Capability.USAGE,
    "item.verification": Capability.VERIFICATION,
}


def normalize_codex_event(raw: Mapping[str, Any]) -> CodexObservation:
    """Normalize one supplied event, preserving unknown fields as explicit gaps."""
    event_type = raw.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("Codex event requires a string type")
    capability = _EVENT_CAPABILITY.get(event_type)
    gaps: list[str] = []
    if capability is None:
        gaps.append(f"unavailable:unrecognized-event:{event_type}")
    if raw.get("session_id") is None:
        gaps.append("unavailable:session_id")
    if event_type.startswith("turn.") and raw.get("turn_id") is None:
        gaps.append("unavailable:turn_id")
    return CodexObservation(
        event_type=event_type,
        session_id=raw.get("session_id") if isinstance(raw.get("session_id"), str) else None,
        turn_id=raw.get("turn_id") if isinstance(raw.get("turn_id"), str) else None,
        item_id=raw.get("item_id") if isinstance(raw.get("item_id"), str) else None,
        payload={key: value for key, value in raw.items() if key not in {"type", "session_id", "turn_id", "item_id"}},
        gaps=tuple(gaps),
    )
