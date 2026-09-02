"""Logical Performance Memory domains; raw evidence remains canonical elsewhere.

Execution 04 (Task 11): this module intentionally holds NO durable-knowledge
lifecycle. `MemoryEvidence` is a Performance-local, non-durable
evidence-candidate shape — no status field, no persistence, no store — and
structurally cannot become canonical knowledge on its own. Turning one into
durable Midnight Memory knowledge requires an explicit proposal through
`memory_bridge.py` (`propose_lesson_or_degrade`), which is the ONLY path to
a real, canonical, promotable record. A prior version of this module defined
`KnowledgeRecord`/`promote()`/`supersede()` — a second record lifecycle
duplicating Memory's own canonical ownership — removed in Execution 04; see
README.md's "Memory ownership migration" section for the audit and
migration map.
"""
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
