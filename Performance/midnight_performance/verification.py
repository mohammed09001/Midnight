"""Structured command/tool/check evidence, separate from repository change evidence."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class VerificationSource(str, Enum): EXECUTED = "executed"; AGENT_REPORTED = "agent_reported"; INFERRED_TEXT = "inferred_text"; EXTERNAL = "external"
@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    identity: str; source: VerificationSource; status: str; duration_ms: int | None
    exit_code: int | None; output: str; changed_files: tuple[str, ...] = (); uncertainty: str | None = None
    def __post_init__(self):
        if self.source is VerificationSource.EXECUTED and self.exit_code is None: raise ValueError("executed command requires exit code")
        if len(self.output) > 4096: raise ValueError("output must be bounded")
