"""Rebuildable canonical requirement-to-evidence matrix."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
from .behavior_analysis import BehaviorAlignment
from .traceability import RequirementUnit, TraceLink, TraceState
MATRIX_VERSION="1"
@dataclass(frozen=True, slots=True)
class MatrixEntry:
    requirement_id:str|None; intent_element_id:str|None; evidence_id:str; relation:str; claim_kind:ClaimKind; redacted:bool=False; uncertainty:str="derived relationship"
@dataclass(frozen=True, slots=True)
class RequirementEvidenceMatrix:
    entries:tuple[MatrixEntry,...]; version:str=MATRIX_VERSION
def build_requirement_matrix(units:tuple[RequirementUnit,...], links:tuple[TraceLink,...], alignment:tuple[BehaviorAlignment,...], *, redacted_evidence:frozenset[str]=frozenset())->RequirementEvidenceMatrix:
    entries=[]
    for unit in units: entries.append(MatrixEntry(unit.id,unit.intent_element_id,f"intent:{unit.intent_element_id}","provenance",ClaimKind.OBSERVED))
    for link in links: entries.append(MatrixEntry(link.requirement_id,None,link.code_element_id,link.state.value,link.claim_kind,link.code_element_id in redacted_evidence,link.uncertainty))
    for item in alignment: entries.append(MatrixEntry(None,None,item.clause_id,item.status.value,ClaimKind.DERIVED,False,item.uncertainty))
    return RequirementEvidenceMatrix(tuple(entries))
