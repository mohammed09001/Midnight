"""Competing explanations and completeness quality for sibling outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from .outcomes import OutcomeProvider

@dataclass(frozen=True, slots=True)
class AttributionAlternatives:
    target_id:str; alternatives:tuple[str,...]; base_confidence:float
    @property
    def adjusted_confidence(self)->float: return round(self.base_confidence/(1+len(self.alternatives)),3)
@dataclass(frozen=True, slots=True)
class OutcomeQuality:
    provider:OutcomeProvider; coverage:float; linkage:float; comparability:float; version_evidence:str|None; gaps:tuple[str,...]=()
    def __post_init__(self):
        if any(not 0<=x<=1 for x in (self.coverage,self.linkage,self.comparability)): raise ValueError("quality dimensions must be between zero and one")
    @property
    def sufficient(self)->bool: return not self.gaps and min(self.coverage,self.linkage,self.comparability)>=.8
