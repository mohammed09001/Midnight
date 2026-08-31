"""Deterministic execution/turn windows that retain ambiguity."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ExecutionWindow:
    agent_run_id: str | None; session_id: str | None; turn_id: str | None
    prompt_run_id: str | None; state: str; ambiguity: tuple[str, ...] = ()

def window_from_lifecycle(event: dict[str, object]) -> ExecutionWindow:
    state = str(event.get("state", "unknown"))
    gaps = []
    for field in ("agent_run_id", "session_id", "turn_id", "prompt_run_id"):
        if not event.get(field): gaps.append(f"unavailable:{field}")
    if state not in {"started", "resumed", "completed", "failed", "interrupted", "unknown"}: gaps.append("ambiguous:state")
    return ExecutionWindow(*(event.get(k) if isinstance(event.get(k), str) else None for k in ("agent_run_id", "session_id", "turn_id", "prompt_run_id")), state, tuple(gaps))
