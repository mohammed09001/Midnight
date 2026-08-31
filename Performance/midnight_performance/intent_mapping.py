"""Many-to-many prompt requirement to repository evidence mapping."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class MappingStatus(str, Enum): MAPPED="mapped"; UNIMPLEMENTED="unimplemented"; UNREQUESTED="changed_but_unrequested"; INSUFFICIENT="insufficient_evidence"
@dataclass(frozen=True, slots=True)
class Requirement:
    id:str; text:str; constraints:tuple[str,...]=()
@dataclass(frozen=True, slots=True)
class EvidenceLink:
    requirement_id:str|None; evidence_id:str; status:MappingStatus; confidence:float; method:str; uncertainty:str
    def __post_init__(self):
        if not 0<=self.confidence<=1: raise ValueError("confidence must be between zero and one")
        if self.status is MappingStatus.UNREQUESTED and self.requirement_id is not None: raise ValueError("unrequested evidence cannot name a requirement")
@dataclass(frozen=True, slots=True)
class IntentMapping:
    requirements:tuple[Requirement,...]; links:tuple[EvidenceLink,...]
    def links_for(self, requirement_id:str)->tuple[EvidenceLink,...]: return tuple(x for x in self.links if x.requirement_id==requirement_id)
    def unimplemented(self)->tuple[Requirement,...]: return tuple(r for r in self.requirements if any(x.status in {MappingStatus.UNIMPLEMENTED,MappingStatus.INSUFFICIENT} for x in self.links_for(r.id)))
