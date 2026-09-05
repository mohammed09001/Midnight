"""Pure, passive normalizer for approved Codex App Server lifecycle events.

It consumes supplied native app-server/SDK event dictionaries only. It does
not launch Codex, acquire credentials, wrap a terminal, or infer missing
lifecycle fields. Codex's app-server is Codex's own engine process — a
client attaches to a connection some other host (an IDE extension, the
Codex CLI, an SDK) already holds for its own purposes; this module never
opens that connection itself.

Execution 04, Section C (protocol correction): the current, live
`openai/codex` App Server protocol (``codex-rs/app-server/README.md``,
researched 2026-09) uses SLASH-separated JSON-RPC notification names
(``thread/started``, ``turn/started``, ``turn/completed``, ...), not the
dot-separated names this module previously assumed (``thread.started``,
``item.diff_updated``, ``turn.usage``, ``item.verification``). Items are
delivered under ``item/started``/``item/completed`` and carry a ``type``
discriminator (``commandExecution``, ``fileChange``, ``userMessage``, ...)
rather than one event name per item kind — the capability mapping below is
keyed on ``(event_type, item_type)`` for those two events.

``Capability.VERIFICATION`` and ``Capability.NATIVE_DIFF`` were removed from
``CODEX_ADAPTER``: research found no confirmed first-class "verification"
item type (test/verification results surface via a ``commandExecution``
item's output or an ``agentMessage``, not a distinct item kind) and no
confirmed distinct diff-delivery event in the current protocol. Claiming a
capability with no real backing event would itself be an invisible-capture
bug — an honest gap is preferable to an unproven positive claim.

``Capability.PROMPT`` was added: ``turn/started`` carries an ``input``
array, and completed turns surface a ``userMessage`` item with a native
``item.id`` plus an optional client-supplied ``clientUserMessageId``
(echoed back as ``clientId``) — sufficient for deterministic Prompt Run
correlation without needing full prompt text (see
``codex_prompt_run_identity``).

This is adapter schema version 2 (bumped from 1): the event vocabulary
change above is a real, breaking rename, not an additive extension.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .harness import Capability, ObservationAdapter


CODEX_ADAPTER = ObservationAdapter(
    name="codex", version="2",
    capabilities=frozenset({
        Capability.SESSION_LIFECYCLE, Capability.TURN_LIFECYCLE, Capability.TOOL_CALL,
        Capability.COMMAND, Capability.FILE_CHANGE, Capability.COMPLETION,
        Capability.USAGE, Capability.PROMPT,
    }),
    integration_modes=frozenset({"approved-native-hook", "app-server-events", "sdk-events"}),
)


@dataclass(frozen=True, slots=True)
class CodexObservation:
    event_type: str
    session_id: str | None
    turn_id: str | None
    item_id: str | None
    item_type: str | None
    client_user_message_id: str | None
    payload: Mapping[str, Any]
    gaps: tuple[str, ...] = ()
    adapter_version: str = CODEX_ADAPTER.version


# Event types not carrying a `type`-discriminated item.
_EVENT_CAPABILITY: dict[str, Capability] = {
    "thread/started": Capability.SESSION_LIFECYCLE,
    "turn/started": Capability.TURN_LIFECYCLE,
    "turn/completed": Capability.COMPLETION,
    "thread/tokenUsage/updated": Capability.USAGE,
}

# `item/started` and `item/completed` carry a `type` discriminator instead
# of a distinct event name per item kind.
_ITEM_TYPE_CAPABILITY: dict[str, Capability] = {
    "commandExecution": Capability.COMMAND,
    "fileChange": Capability.FILE_CHANGE,
    "userMessage": Capability.PROMPT,
    "mcpToolCall": Capability.TOOL_CALL,
    "agentMessage": Capability.COMPLETION,
}

_ITEM_EVENTS = frozenset({"item/started", "item/completed"})


def _resolve_capability(event_type: str, item_type: str | None) -> tuple[Capability | None, list[str]]:
    if event_type in _ITEM_EVENTS:
        if item_type is None:
            return None, ["unavailable:item-type"]
        capability = _ITEM_TYPE_CAPABILITY.get(item_type)
        if capability is None:
            return None, [f"unavailable:unrecognized-item-type:{item_type}"]
        return capability, []
    capability = _EVENT_CAPABILITY.get(event_type)
    if capability is None:
        return None, [f"unavailable:unrecognized-event:{event_type}"]
    return capability, []


def codex_prompt_run_identity(raw: Mapping[str, Any]) -> str | None:
    """A deterministic Prompt Run correlation key from native Codex IDs only.

    Never derived from prompt text. Prefers the client-supplied
    ``clientUserMessageId`` (echoed as ``clientId`` on the resulting
    ``userMessage`` item) when present; otherwise falls back to the
    server-assigned ``thread.id:turn.id:item.id`` triple for a
    ``userMessage``-typed item. Returns ``None`` — never a guess — when
    neither is available or the event is not a user-message item.
    """
    item_type = raw.get("item", {}).get("type") if isinstance(raw.get("item"), Mapping) else raw.get("item_type")
    if item_type != "userMessage":
        return None
    client_id = raw.get("clientId") or raw.get("clientUserMessageId")
    if isinstance(client_id, str) and client_id.strip():
        return client_id
    thread_id, turn_id, item_id = raw.get("thread_id"), raw.get("turn_id"), raw.get("item_id")
    if isinstance(thread_id, str) and isinstance(turn_id, str) and isinstance(item_id, str):
        return f"{thread_id}:{turn_id}:{item_id}"
    return None


def normalize_codex_event(raw: Mapping[str, Any]) -> CodexObservation:
    """Normalize one supplied event, preserving unknown fields as explicit gaps."""
    event_type = raw.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("Codex event requires a string type")
    item = raw.get("item") if isinstance(raw.get("item"), Mapping) else None
    item_type = item.get("type") if item is not None else raw.get("item_type")
    item_type = item_type if isinstance(item_type, str) else None

    _capability, capability_gaps = _resolve_capability(event_type, item_type)
    gaps: list[str] = list(capability_gaps)
    if raw.get("session_id") is None and raw.get("thread_id") is None:
        gaps.append("unavailable:session_id")
    if event_type.startswith("turn/") and raw.get("turn_id") is None:
        gaps.append("unavailable:turn_id")

    client_user_message_id = raw.get("clientId") or raw.get("clientUserMessageId")
    return CodexObservation(
        event_type=event_type,
        session_id=_first_str(raw.get("session_id"), raw.get("thread_id")),
        turn_id=raw.get("turn_id") if isinstance(raw.get("turn_id"), str) else None,
        item_id=raw.get("item_id") if isinstance(raw.get("item_id"), str) else None,
        item_type=item_type,
        client_user_message_id=client_user_message_id if isinstance(client_user_message_id, str) else None,
        # `item` is preserved verbatim (not stripped) — its nested fields
        # (e.g. a fileChange item's path, a commandExecution item's command)
        # are provider-shaped and not guessed at by this normalizer; callers
        # needing them read `payload["item"]` directly.
        payload={key: value for key, value in raw.items() if key not in {"type", "session_id", "thread_id", "turn_id", "item_id"}},
        gaps=tuple(gaps),
    )


def _first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            return value
    return None
