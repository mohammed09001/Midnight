"""Execution 09: Memory Temporal Lineage Overlay.

The key distinction this module exists to enforce in code, not just prose
(Memory/docs/CROSS_ENGINE_LINEAGE.md's "citations are pinned; staleness is
discovered, not pushed"):

    A Memory citation inside a historical Performance graph is a pinned
    historical revision. Current Memory state is a separate, explicitly
    refreshed read.

`pinned_state` is pure parsing of an already-issued `ExternalReference` (the
`<recordId>#rev<revision>` format from `memory_bridge.citation_from_memory_record`)
— it never contacts Memory, so calling it while building a `PerformanceGraph`
costs nothing and changes nothing about the existing "graph is a rebuildable
projection over point-in-time citations" contract.

`refresh_state` is the ONLY function here that talks to Memory, and it does
so read-only, through the existing `memory.context` operation
(`memory_bridge.read_performance_context` — Task 14's bounded, typed read;
no new Memory-side contract is introduced, no direct SQLite access). It
never mutates the `MemoryCitationState` it was given: every branch returns a
brand-new instance, so a `PerformanceGraph` built earlier from the pinned
state is never silently rewritten by a later refresh (Section C/D of the
execution spec). Every failure mode (Memory not installed, unreachable,
contract mismatch, record missing/expired, malformed response) becomes a
truthful, explicit gap on the returned state — never an exception, and
never a fabricated "stale" claim: `newer_revision_available` is only ever
set from an actual current-revision comparison, never from elapsed time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .contracts import ExternalReference
from .memory_bridge import MalformedMemoryRecordError, parse_pinned_reference, read_performance_context

MEMORY_LINEAGE_VERSION = 1


@dataclass(frozen=True, slots=True)
class MemoryCitationState:
    """Section D's temporal state, at minimum. `pinned_revision` is always
    known (it's parsed from the citation itself, not read from Memory).
    Every `current_*`/`superseded`/`contradiction_*`/`newer_revision_available`
    field stays `None` until a real `refresh_state` call populates it —
    `current_status_known` is the single authoritative signal for "is any of
    this live," never inferred from whether the other fields happen to be
    non-None."""

    provider: str
    record_id: str
    pinned_revision: int
    current_status_known: bool = False
    current_revision: int | None = None
    current_status: str | None = None
    superseded: bool | None = None
    superseded_by_record_id: str | None = None
    contradiction_group_id: str | None = None
    contradiction_status: str | None = None
    contradiction_group_size: int | None = None
    newer_revision_available: bool | None = None
    refreshed_at: str | None = None
    gaps: tuple[str, ...] = ()

    def to_record(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "recordId": self.record_id,
            "pinnedRevision": self.pinned_revision,
            "currentStatusKnown": self.current_status_known,
            "currentRevision": self.current_revision,
            "currentStatus": self.current_status,
            "superseded": self.superseded,
            "supersededByRecordId": self.superseded_by_record_id,
            "contradictionGroupId": self.contradiction_group_id,
            "contradictionStatus": self.contradiction_status,
            "contradictionGroupSize": self.contradiction_group_size,
            "newerRevisionAvailable": self.newer_revision_available,
            "refreshedAt": self.refreshed_at,
            "gaps": list(self.gaps),
        }


def pinned_state(reference: ExternalReference) -> MemoryCitationState:
    """Build-time-only state (Section B: "historical status available at
    build time"): parses the pinned reference, contacts nothing. Raises
    `MalformedMemoryRecordError` for a reference that isn't a recognizable
    Memory record citation — a caller building a graph from caller-supplied
    `memory_references` gets a typed failure instead of a silently-wrong
    node."""
    if reference.provider != "memory" or reference.kind != "record":
        raise MalformedMemoryRecordError(
            f"'{reference.provider}:{reference.kind}' is not a Memory record citation"
        )
    record_id, revision = parse_pinned_reference(reference.value)
    return MemoryCitationState(provider=reference.provider, record_id=record_id, pinned_revision=revision)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def refresh_state(pinned: MemoryCitationState, project_key: str, *, size: int = 100, **kwargs) -> MemoryCitationState:
    """Section C's explicit refresh: one read-only `memory.context` call
    (via `read_performance_context`), scoped to `project_key` (a Memory
    projectKey — callers pass the already-mapped scope, mirroring every
    other `read_performance_context` caller). ALWAYS returns a NEW
    `MemoryCitationState` derived from `pinned`'s identity fields — never
    mutates `pinned` itself, and never raises: an unreachable/rejecting
    Memory, or a record that doesn't appear within the bounded read window,
    is reported as an honest gap with `current_status_known` left `False`,
    exactly like Section E requires.

    `**kwargs` are forwarded to `read_performance_context` (context filters,
    `memory_repo_path`, `store_path`, `node_executable`, `timeout_seconds`).
    """
    refreshed_at = _utc_now_iso()
    read = read_performance_context(project_key, size=size, **kwargs)
    if not read.available:
        return replace(
            pinned,
            refreshed_at=refreshed_at,
            gaps=pinned.gaps + (f"unavailable:memory_unreachable:{read.error_code}",),
        )
    match = next((entry for entry in read.records if entry.get("record", {}).get("recordId") == pinned.record_id), None)
    if match is None:
        return replace(
            pinned,
            refreshed_at=refreshed_at,
            gaps=pinned.gaps + ("unavailable:current_read:record_not_in_window",),
        )
    record = match["record"]
    contradiction = match.get("contradiction") or {}
    current_revision = record["revision"]
    return MemoryCitationState(
        provider=pinned.provider,
        record_id=pinned.record_id,
        pinned_revision=pinned.pinned_revision,
        current_status_known=True,
        current_revision=current_revision,
        current_status=record.get("status"),
        superseded=record.get("status") == "superseded",
        superseded_by_record_id=record.get("supersededById"),
        contradiction_group_id=record.get("contradictionGroupId"),
        contradiction_status=contradiction.get("status"),
        contradiction_group_size=contradiction.get("groupSize"),
        newer_revision_available=current_revision > pinned.pinned_revision,
        refreshed_at=refreshed_at,
        gaps=pinned.gaps,
    )
