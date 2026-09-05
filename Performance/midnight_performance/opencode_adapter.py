"""Passive OpenCode event/snapshot normalization with snapshot deduplication.

Execution 04, Section D: OpenCode's plugin API (opencode.ai/docs/plugins/,
researched 2026-09) has a real, documented mutation-capable hook surface —
``tool.execute.before`` (can rewrite tool args or throw to block the call),
``shell.env`` (can rewrite injected shell environment), and the
``experimental.*``/``stop`` hooks (can rewrite system-prompt/compaction
content or keep the agent running) all consume a hook's RETURN VALUE to
change behavior. A callback used for Midnight observation must never be one
of those. The correct real integration point is OpenCode's separate
``ctx.event.subscribe`` stream, documented as observation-only with no
mechanism to modify or reject events — any future real wiring must come
from there, never from a mutation-capable hook name.

``OpenCodeObserver.normalize`` machine-checks that invariant rather than
only documenting it: a raw event whose ``type`` names a known
mutation-capable hook is refused outright (a caller integration mistake,
not a provider data gap — hence a raised error, not a soft gap), mirroring
``ObservationAdapter.__post_init__``'s existing hard-reject of forbidden
``integration_modes``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib, json
from typing import Any, Mapping

from .harness import Capability, ObservationAdapter

OPENCODE_ADAPTER = ObservationAdapter("opencode", "1", frozenset({Capability.SESSION_LIFECYCLE, Capability.PROMPT, Capability.TOOL_CALL, Capability.COMMAND, Capability.FILE_CHANGE, Capability.COMPLETION, Capability.USAGE, Capability.NATIVE_DIFF, Capability.SUBAGENT}), frozenset({"observer-plugin", "session-snapshot"}))

# Documented (opencode.ai/docs/plugins/) mutation-capable hooks: their
# return value is consumed to change behavior. An observer must never be
# wired to these — only to `tool.execute.after` and friends, or to the
# separate `ctx.event.subscribe` stream.
_MUTATION_CAPABLE_HOOKS = frozenset({
    "tool.execute.before",
    "shell.env",
    "experimental.chat.system.transform",
    "experimental.session.compacting",
    "stop",
})

@dataclass(frozen=True, slots=True)
class OpenCodeObservation:
    event_type: str
    session_id: str | None
    payload: Mapping[str, Any]
    gaps: tuple[str, ...] = ()
    normalizer_version: str = OPENCODE_ADAPTER.version
    """Version of THIS normalizer, distinct from `adapter_version` — a raw
    payload field the OpenCode plugin itself self-reports (see `.payload`),
    never conflated with it."""

class OpenCodeObserver:
    def __init__(self) -> None: self._seen: set[str] = set()
    def normalize(self, raw: Mapping[str, Any]) -> OpenCodeObservation | None:
        event = raw.get("type")
        if not isinstance(event, str) or not event: raise ValueError("OpenCode event requires type")
        if event in _MUTATION_CAPABLE_HOOKS:
            raise ValueError(f"refusing to observe mutation-capable OpenCode hook '{event}' — wire event.subscribe instead")
        fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
        if fingerprint in self._seen: return None
        self._seen.add(fingerprint)
        gaps = []
        if raw.get("session_id") is None: gaps.append("unavailable:session_id")
        if raw.get("parent_session_id") is None and event.startswith("session.child"): gaps.append("unavailable:parent_session_id")
        if raw.get("adapter_version") is None: gaps.append("unavailable:adapter_version")
        return OpenCodeObservation(event, raw.get("session_id") if isinstance(raw.get("session_id"), str) else None, {k: v for k, v in raw.items() if k not in {"type", "session_id"}}, tuple(gaps))
