"""Rebuildable Memory retrieval and retention views."""
from __future__ import annotations
from dataclasses import dataclass
from .memory import MemoryEvidence
@dataclass(frozen=True, slots=True)
class MemoryHit:
    evidence: MemoryEvidence; score:float; provenance:tuple[str,...]; valid:bool; contradicted:bool; method:str="lexical-relational"
def retrieve_memory(query:str, evidence:tuple[MemoryEvidence,...], *, domain=None)->tuple[MemoryHit,...]:
    terms=set(query.lower().split()); hits=[]
    for item in evidence:
        if domain and item.domain is not domain: continue
        shared=terms & set(item.statement.lower().split()); score=len(shared)/len(terms) if terms else 0
        if score: hits.append(MemoryHit(item,round(score,3),item.source_refs,True,False))
    return tuple(sorted(hits,key=lambda x:(-x.score,x.evidence.evidence_id)))
def retain(evidence:tuple[MemoryEvidence,...], *, allowed_refs:frozenset[str])->tuple[MemoryEvidence,...]:
    return tuple(item for item in evidence if set(item.source_refs)<=allowed_refs)
