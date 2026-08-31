"""Passive OpenCode event/snapshot normalization with snapshot deduplication."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib, json
from typing import Any, Mapping

from .harness import Capability, ObservationAdapter

OPENCODE_ADAPTER = ObservationAdapter("opencode", "1", frozenset({Capability.SESSION_LIFECYCLE, Capability.PROMPT, Capability.TOOL_CALL, Capability.COMMAND, Capability.FILE_CHANGE, Capability.COMPLETION, Capability.USAGE, Capability.NATIVE_DIFF, Capability.SUBAGENT}), frozenset({"observer-plugin", "session-snapshot"}))

@dataclass(frozen=True, slots=True)
class OpenCodeObservation:
    event_type: str
    session_id: str | None
    payload: Mapping[str, Any]
    gaps: tuple[str, ...] = ()

class OpenCodeObserver:
    def __init__(self) -> None: self._seen: set[str] = set()
    def normalize(self, raw: Mapping[str, Any]) -> OpenCodeObservation | None:
        event = raw.get("type")
        if not isinstance(event, str) or not event: raise ValueError("OpenCode event requires type")
        fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
        if fingerprint in self._seen: return None
        self._seen.add(fingerprint)
        gaps = []
        if raw.get("session_id") is None: gaps.append("unavailable:session_id")
        if raw.get("parent_session_id") is None and event.startswith("session.child"): gaps.append("unavailable:parent_session_id")
        if raw.get("adapter_version") is None: gaps.append("unavailable:adapter_version")
        return OpenCodeObservation(event, raw.get("session_id") if isinstance(raw.get("session_id"), str) else None, {k: v for k, v in raw.items() if k not in {"type", "session_id"}}, tuple(gaps))
