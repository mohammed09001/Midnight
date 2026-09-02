"""Qualified specification hypotheses, behavior contracts, and alignment."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ClaimKind
from .intent_contract import IntentContract, IntentKind
from .traceability import TraceLink, TraceState

BEHAVIOR_ANALYSIS_VERSION="1"
class OracleKind(str, Enum): TEST="test"; CONTRACT="contract"; RUNTIME="runtime"; HUMAN="human"; UNKNOWN="unknown"
class BehaviorStatus(str, Enum): SATISFIED="satisfied"; PARTIALLY_SATISFIED="partially_satisfied"; NOT_SATISFIED="not_satisfied"; CONTRADICTED="contradicted"; INSUFFICIENT_EVIDENCE="insufficient_evidence"
@dataclass(frozen=True, slots=True)
class SpecificationHypothesis:
    id: str; project_id: str; statement: str; scope: tuple[str,...]; source_evidence: tuple[str,...]; contradictions: tuple[str,...]; unknowns: tuple[str,...]; confidence: float; claim_kind: ClaimKind; analysis_version: str; previous_id: str|None=None
    def __post_init__(self):
        if not self.project_id.strip() or not self.id.strip(): raise ValueError("hypothesis requires project-scoped identity")
        if not 0<=self.confidence<=1: raise ValueError("hypothesis confidence must be between zero and one")
@dataclass(frozen=True, slots=True)
class BehaviorClause:
    id: str; project_id: str; text: str; claim_kind: ClaimKind; intent_element_id: str|None; evidence: tuple[str,...]; examples: tuple[str,...]; counterexamples: tuple[str,...]; oracle: OracleKind; version: str=BEHAVIOR_ANALYSIS_VERSION
    def __post_init__(self):
        if not self.project_id.strip() or not self.id.strip() or not self.text.strip(): raise ValueError("behavior clause requires project identity and text")
@dataclass(frozen=True, slots=True)
class BehaviorContract:
    project_id: str; version: str; clauses: tuple[BehaviorClause,...]
    def __post_init__(self):
        if any(item.project_id != self.project_id for item in self.clauses): raise ValueError("behavior contract cannot cross projects")
@dataclass(frozen=True, slots=True)
class BehaviorAlignment:
    clause_id: str; status: BehaviorStatus; evidence: tuple[str,...]; contradictions: tuple[str,...]; confidence: float|None; analysis_version: str; changed_because: str; uncertainty: str

def infer_specification(project_id: str, contract: IntentContract, *, repository_evidence: tuple[str,...]=(), test_evidence: tuple[str,...]=(), analysis_version: str=BEHAVIOR_ANALYSIS_VERSION, previous: SpecificationHypothesis|None=None) -> tuple[SpecificationHypothesis,...]:
    """Deterministic evidence collection works without an AI provider.

    Explicit prompt clauses are observed user intent; repository-derived
    expectations are separate inferred hypotheses with their own uncertainty.
    """
    result=[]
    for item in contract.elements:
        if item.kind in {IntentKind.GOAL, IntentKind.ACCEPTANCE, IntentKind.CONSTRAINT, IntentKind.VERIFICATION}:
            evidence=(f"intent:{item.id}:{item.span.start}-{item.span.end}",)+repository_evidence+test_evidence
            result.append(SpecificationHypothesis(f"spec:{project_id}:{item.id}:{analysis_version}",project_id,item.text,(item.id,),evidence,(),("repository evidence describes current behavior, not normative truth",) if repository_evidence else ("no repository behavior evidence",),.8 if item.claim_kind is ClaimKind.OBSERVED else .4,item.claim_kind,analysis_version,previous.id if previous else None))
    return tuple(result)
def refine_hypothesis(previous: SpecificationHypothesis, *, repository_evidence: tuple[str,...]=(), contradictions: tuple[str,...]=(), analysis_version: str) -> SpecificationHypothesis:
    evidence=previous.source_evidence+tuple(item for item in repository_evidence if item not in previous.source_evidence)
    return SpecificationHypothesis(f"{previous.id}:v:{analysis_version}",previous.project_id,previous.statement,previous.scope,evidence,previous.contradictions+contradictions,previous.unknowns, max(0, previous.confidence-.2) if contradictions else previous.confidence,previous.claim_kind,analysis_version,previous.id)
def behavior_contract(project_id: str, hypotheses: tuple[SpecificationHypothesis,...]) -> BehaviorContract:
    clauses=[]
    for hypothesis in hypotheses:
        intent_id=hypothesis.scope[0] if hypothesis.scope else None
        oracle=OracleKind.TEST if any("test" in item.lower() for item in hypothesis.source_evidence) else OracleKind.UNKNOWN
        clauses.append(BehaviorClause(f"behavior:{hypothesis.id}",project_id,hypothesis.statement,hypothesis.claim_kind,intent_id,hypothesis.source_evidence,(),(),oracle,hypothesis.analysis_version))
    return BehaviorContract(project_id,BEHAVIOR_ANALYSIS_VERSION,tuple(clauses))
def align_behavior(contract: BehaviorContract, links: tuple[TraceLink,...], *, executed_oracles: tuple[str,...]=(), contradictory_evidence: tuple[str,...]=(), analysis_version: str=BEHAVIOR_ANALYSIS_VERSION) -> tuple[BehaviorAlignment,...]:
    supported={link.requirement_id for link in links if link.state is TraceState.SUPPORTED}; candidates={link.requirement_id for link in links if link.state is TraceState.CANDIDATE}
    result=[]
    for clause in contract.clauses:
        requirement_id=clause.id.removeprefix("behavior:spec:").split(":",2)[1] if clause.id.startswith("behavior:spec:") else None
        evidence=tuple(link.code_element_id for link in links if link.state is TraceState.SUPPORTED)
        if contradictory_evidence: status=BehaviorStatus.CONTRADICTED; confidence=.8; reason="concrete contradictory evidence supplied"
        elif requirement_id in supported and executed_oracles: status=BehaviorStatus.SATISFIED; confidence=.7; reason="structural support plus executed oracle evidence"
        elif requirement_id in supported or candidates: status=BehaviorStatus.PARTIALLY_SATISFIED; confidence=.4; reason="implementation trace exists but runtime/oracle evidence is incomplete"
        else: status=BehaviorStatus.INSUFFICIENT_EVIDENCE; confidence=None; reason="no supported trace and no executed oracle"
        result.append(BehaviorAlignment(clause.id,status,evidence+executed_oracles,contradictory_evidence,confidence,analysis_version,reason,"structural traces and passing tests are not complete behavior proof"))
    return tuple(result)
