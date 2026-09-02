"""Requirement-aware verification, divergence, and oracle uncertainty projections."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ClaimKind
from .interaction_policy import InteractionMode

VERIFICATION_INTELLIGENCE_VERSION="1"
class CoverageKind(str, Enum): POSITIVE="positive"; NEGATIVE="negative"; BOUNDARY="boundary"; REGRESSION="regression"; UNRELATED="unrelated"; UNKNOWN="unknown"
class OracleSource(str, Enum): TEST="test"; EXAMPLE="example"; METAMORPHIC="metamorphic"; RUNTIME="runtime"; HUMAN="human"; UNKNOWN="unknown"
class OracleStrength(str, Enum): STRONG="strong"; PARTIAL="partial"; HUMAN_REQUIRED="human_required"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class RequirementVerificationLink:
    requirement_id:str|None; clause_id:str|None; verification_id:str; source:OracleSource; specificity:float; executed:bool; coverage:CoverageKind; uncertainty:str
    def __post_init__(self):
        if not 0 <= self.specificity <= 1: raise ValueError("specificity must be between zero and one")
@dataclass(frozen=True, slots=True)
class BehaviorVerificationEvidence:
    id: str; clause_id: str|None; source: OracleSource; executed: bool; inputs: tuple[str,...]; observed_outputs: tuple[str,...]; expected_relation: str|None; passed: bool|None; provenance: tuple[str,...]; uncertainty: str
@dataclass(frozen=True, slots=True)
class VerificationCoverage:
    clause_id: str; kind: CoverageKind; evidence_ids: tuple[str,...]; executed: bool; uncertainty: str
@dataclass(frozen=True, slots=True)
class BehavioralDivergence:
    clause_id: str; evidence_ids: tuple[str,...]; divergence: str; claim_kind: ClaimKind=ClaimKind.DERIVED
@dataclass(frozen=True, slots=True)
class OracleAssessment:
    clause_id: str; source: OracleSource; strength: OracleStrength; statement: str; uncertainty: str; human_confirmation_suggested: bool

def coverage_for(clause_ids: tuple[str,...], evidence: tuple[BehaviorVerificationEvidence,...], *, changed_clause_ids: tuple[str,...]=()) -> tuple[VerificationCoverage,...]:
    result=[]
    for clause in clause_ids:
        items=tuple(item for item in evidence if item.clause_id==clause)
        executed=tuple(item for item in items if item.executed)
        if not items: kind=CoverageKind.UNKNOWN; note="no defensible requirement-to-verification link"
        elif not executed: kind=CoverageKind.UNKNOWN; note="verification was reported but not executed"
        elif any(item.passed is False for item in executed): kind=CoverageKind.NEGATIVE; note="executed evidence reports failure"
        elif any(item.source is OracleSource.METAMORPHIC for item in executed): kind=CoverageKind.BOUNDARY; note="executed metamorphic relation"
        else: kind=CoverageKind.POSITIVE; note="executed linked verification; does not establish complete coverage"
        result.append(VerificationCoverage(clause,kind,tuple(item.id for item in items),bool(executed),note))
    for clause in changed_clause_ids:
        if clause not in clause_ids: result.append(VerificationCoverage(clause,CoverageKind.UNKNOWN,(),False,"changed behavior surface has no behavior-contract clause"))
    return tuple(result)
def link_verification(requirement_id:str|None, clause_id:str|None, evidence:BehaviorVerificationEvidence, *, specificity:float=1.0, coverage:CoverageKind|None=None)->RequirementVerificationLink:
    """Keep unassigned verification visible by allowing both link targets to be None."""
    if coverage is None:
        coverage=CoverageKind.UNKNOWN if not evidence.executed else (CoverageKind.NEGATIVE if evidence.passed is False else CoverageKind.POSITIVE if evidence.passed is True else CoverageKind.UNKNOWN)
    return RequirementVerificationLink(requirement_id,clause_id,evidence.id,evidence.source,specificity,evidence.executed,coverage,"reported-only verification does not establish execution" if not evidence.executed else "coverage is scoped to this explicit link")
def detect_divergence(evidence: tuple[BehaviorVerificationEvidence,...]) -> tuple[BehavioralDivergence,...]:
    return tuple(BehavioralDivergence(item.clause_id or "unknown",(item.id,),"observed output violates explicit expected relation") for item in evidence if item.executed and item.passed is False and item.expected_relation)
def assess_oracle(clause_id: str, evidence: tuple[BehaviorVerificationEvidence,...], *, interaction_mode: InteractionMode=InteractionMode.PASSIVE, information_gain: float=0) -> OracleAssessment:
    items=tuple(item for item in evidence if item.clause_id==clause_id and item.executed)
    if any(item.source is OracleSource.HUMAN for item in items): source,strength=OracleSource.HUMAN,OracleStrength.HUMAN_REQUIRED
    elif any(item.source in {OracleSource.TEST,OracleSource.METAMORPHIC} and item.passed is True for item in items): source,strength=items[0].source,OracleStrength.STRONG
    elif items: source,strength=items[0].source,OracleStrength.PARTIAL
    else: source,strength=OracleSource.UNKNOWN,OracleStrength.UNKNOWN
    suggest=strength in {OracleStrength.HUMAN_REQUIRED,OracleStrength.UNKNOWN} and interaction_mode is not InteractionMode.PASSIVE and information_gain>=.5
    return OracleAssessment(clause_id,source,strength,f"verified under {source.value} oracle" if items else "no verification oracle evidence", "oracle evidence is scoped and not generic correctness",suggest)
