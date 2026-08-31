"""Primary development-experience projection; gaps remain explicit."""
from __future__ import annotations
from dataclasses import dataclass, field
@dataclass(frozen=True, slots=True)
class PromptRun:
    prompt_run_id: str; prompt_version_id: str | None; agent_run_ids: tuple[str, ...] = ()
    change_set_ids: tuple[str, ...] = (); verification_ids: tuple[str, ...] = (); feedback_ids: tuple[str, ...] = ()
    outcome_references: tuple[str, ...] = (); analysis_ids: tuple[str, ...] = (); episode_id: str | None = None
    gaps: tuple[str, ...] = field(default_factory=tuple)
    def __post_init__(self):
        if not self.prompt_run_id: raise ValueError("prompt_run_id is required")
        if self.prompt_version_id is None and "unavailable:prompt_version" not in self.gaps: raise ValueError("missing prompt version must be explicit")
