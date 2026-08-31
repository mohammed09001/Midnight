"""Versioned, revisable post-run user feedback contracts."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

class Judgment(str, Enum): ACHIEVED="achieved"; PARTIAL="partially_achieved"; NOT_ACHIEVED="not_achieved"; UNCERTAIN="uncertain"
class FeedbackReason(str, Enum): BEHAVIOR="behavior"; CORRECTNESS="correctness"; PERFORMANCE="performance"; UI="ui"; SCOPE="scope"; VERIFICATION="verification"; MAINTAINABILITY="maintainability"; REGRESSION="regression"; INCOMPLETE="incomplete_work"; MISUNDERSTOOD="misunderstood_intent"; OTHER="other"
@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    id:str; prompt_run_id:str; actor:str; judgment:Judgment; reasons:tuple[FeedbackReason,...]=(); free_text:str|None=None
    confidence:float|None=None; uncertainty:str|None=None; submitted_at:datetime=field(default_factory=lambda:datetime.now(timezone.utc)); revises_id:str|None=None
    def __post_init__(self):
        if not self.id or not self.prompt_run_id or not self.actor: raise ValueError("feedback requires id, run, and actor")
        if self.confidence is not None and not 0<=self.confidence<=1: raise ValueError("confidence must be between zero and one")
        if self.submitted_at.tzinfo is None: raise ValueError("feedback time must be timezone-aware")
def should_request_feedback(*, expected_information_gain:float, threshold:float=.5)->bool: return expected_information_gain>=threshold
