"""Logical Performance Memory domains; raw evidence remains canonical elsewhere."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ClaimKind
class MemoryDomain(str, Enum):
    PROMPT="prompt"; EXECUTION="execution"; CHANGE="change"; VERIFICATION="verification"; OUTCOME="outcome"; EPISODE="episode"; KNOWLEDGE="knowledge"
@dataclass(frozen=True, slots=True)
class MemoryEvidence:
    evidence_id:str; domain:MemoryDomain; source_refs:tuple[str,...]; statement:str; claim_kind:ClaimKind
    def __post_init__(self):
        if not self.evidence_id.strip() or not self.statement.strip() or not self.source_refs: raise ValueError("memory evidence requires identity, statement, and raw references")
@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    record_id:str; statement:str; evidence_ids:tuple[str,...]; status:str="active"; supersedes:tuple[str,...]=(); contradicts:tuple[str,...]=()
def promote(evidence:tuple[MemoryEvidence,...], *, minimum_sources:int=2)->KnowledgeRecord|None:
    refs=tuple(sorted({r for x in evidence for r in x.source_refs}))
    if len(refs)<minimum_sources or not evidence: return None
    return KnowledgeRecord("knowledge:"+evidence[0].evidence_id,evidence[0].statement,tuple(x.evidence_id for x in evidence))
def supersede(record:KnowledgeRecord, replacement:KnowledgeRecord)->tuple[KnowledgeRecord,KnowledgeRecord]:
    from dataclasses import replace
    return replace(record,status="superseded",supersedes=record.supersedes+(replacement.record_id,)), replacement
