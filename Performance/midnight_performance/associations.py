"""Qualified, non-causal Prompt Run to sibling outcome associations."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .outcomes import OutcomeProvider, OutcomeReference

class AssociationKind(str, Enum): RUNTIME_ISSUE="runtime_issue"; RUNTIME_OPERATION="runtime_operation"; DATA="data"; SECURITY="security"
@dataclass(frozen=True, slots=True)
class OutcomeAssociation:
    prompt_run_id:str; outcome:OutcomeReference; kind:AssociationKind; method:str; version:str; confidence:float
    evidence:tuple[str,...]; intervening_changes:tuple[str,...]=(); uncertainty:str="correlation is not causation"
    def __post_init__(self):
        if not 0<=self.confidence<=1 or not self.method or not self.version: raise ValueError("association requires qualified method and confidence")
        expected={AssociationKind.RUNTIME_ISSUE:OutcomeProvider.RUNTIME,AssociationKind.RUNTIME_OPERATION:OutcomeProvider.RUNTIME,AssociationKind.DATA:OutcomeProvider.DATA,AssociationKind.SECURITY:OutcomeProvider.SECURITY}[self.kind]
        if self.outcome.provider is not expected: raise ValueError("association kind and sibling authority disagree")
