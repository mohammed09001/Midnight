"""Versioned reference-only sibling outcome contracts and correlation windows."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class OutcomeProvider(str, Enum): RUNTIME="watch_runtime"; DATA="watch_data"; SECURITY="security"
@dataclass(frozen=True, slots=True)
class OutcomeReference:
    provider:OutcomeProvider; kind:str; external_id:str; contract_version:int=1; occurred_at:datetime|None=None
    def __post_init__(self):
        if not self.kind or not self.external_id or self.contract_version<1: raise ValueError("outcome reference requires kind, id, and version")
@dataclass(frozen=True, slots=True)
class OutcomeWindow:
    anchor_id:str; starts_at:datetime; ends_at:datetime; environment:str|None; release_id:str|None
    confounders:tuple[str,...]=(); incomplete_domains:tuple[OutcomeProvider,...]=()
    def __post_init__(self):
        if self.ends_at<self.starts_at: raise ValueError("window end precedes start")
    def contains(self, reference:OutcomeReference)->bool:
        return reference.occurred_at is not None and self.starts_at<=reference.occurred_at<=self.ends_at
