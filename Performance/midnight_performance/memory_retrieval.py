"""Rebuildable Memory retrieval and retention views.

Execution 04 (Task 11): `retrieve_memory`/`retain` operate ONLY on a
caller-supplied, in-process, ephemeral `MemoryEvidence` tuple — never a
store, never a ledger read, never canonical Midnight Memory. Despite the
name, this is not a query path into Memory; it is a local relevance/
provenance filter over evidence the caller already holds. Reading durable
knowledge back from canonical Memory goes through
`memory_bridge.read_memory_context_or_none`.
"""
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
