"""Local, rebuildable composition of Performance's derived analyzers."""
from __future__ import annotations
from dataclasses import dataclass
from dataclasses import replace
from .contracts import ClaimKind
from .ambiguity_analysis import AMBIGUITY_ANALYSIS_VERSION, AmbiguityReport, analyze_ambiguity
from .behavior_analysis import BEHAVIOR_ANALYSIS_VERSION, BehaviorAlignment, BehaviorContract, align_behavior, behavior_contract, infer_specification
from .decision_story import DecisionStory, RequirementEvidence, build_story
from .intent_contract import INTENT_CONTRACT_VERSION, IntentContract, extract_intent_contract
from .link_integrity import LinkIntegrityReport, validate_link_integrity
from .semantic_change import SEMANTIC_CHANGE_VERSION, SemanticChangeEvent, classify_semantic_change
from .structural_diff import STRUCTURAL_DIFF_VERSION, StructuralDiff, changed_surfaces, structural_diff
from .traceability import TRACEABILITY_VERSION, CodeElement, RequirementUnit, TraceLink, build_requirement_units, link_from_candidate, resolve_code_elements, retrieve_candidates
from .trajectory import TRAJECTORY_VERSION, Trajectory, TrajectoryEvent, build_trajectory
from .verification_intelligence import BehaviorVerificationEvidence

DEEP_ANALYSIS_VERSION="1"
@dataclass(frozen=True, slots=True)
class DeepAnalysisRequest:
    project_id:str; run_id:str; prompt:str; path:str="change.py"; before:str|None=None; after:str|None=None
    support_evidence:tuple[str,...]=(); verification:tuple[BehaviorVerificationEvidence,...]=(); trajectory_events:tuple[TrajectoryEvent,...]=()
    privacy_redacted:bool=False; optional_ai_enabled:bool=False
    corrupt_requirement_identity:bool=False
@dataclass(frozen=True, slots=True)
class DeepAnalysisResult:
    request:DeepAnalysisRequest; intent:IntentContract; ambiguity:AmbiguityReport; requirements:tuple[RequirementUnit,...]; structural:StructuralDiff; semantic:SemanticChangeEvent; elements:tuple[CodeElement,...]; links:tuple[TraceLink,...]; behavior:BehaviorContract; alignment:tuple[BehaviorAlignment,...]; trajectory:Trajectory|None; integrity:LinkIntegrityReport; story:DecisionStory|None; gaps:tuple[str,...]; versions:tuple[tuple[str,str],...]; version:str=DEEP_ANALYSIS_VERSION

def analyze_deep(request:DeepAnalysisRequest)->DeepAnalysisResult:
    if not request.project_id.strip() or not request.run_id.strip(): raise ValueError("project and run ids are required")
    intent=extract_intent_contract(request.prompt); ambiguity=analyze_ambiguity(intent)
    requirements=build_requirement_units(request.run_id,intent); structural=structural_diff(request.path,request.before,request.after,raw_evidence=request.support_evidence)
    elements=resolve_code_elements(request.path,request.after); candidates=retrieve_candidates(requirements,intent,elements)
    links=tuple(link_from_candidate(item,support_evidence=request.support_evidence) for item in candidates)
    if request.corrupt_requirement_identity and links:
        links=(replace(links[0],requirement_id="requirement:corrupt"),)+links[1:]
    behavior=behavior_contract(request.project_id,infer_specification(request.project_id,intent),requirement_units=requirements,intent_contract_version=intent.version)
    executed=tuple(item.id for item in request.verification if item.executed and item.passed is True)
    alignment=align_behavior(behavior,links,executed_oracles=executed)
    trajectory=build_trajectory(request.run_id,request.trajectory_events) if request.trajectory_events else None
    semantic=classify_semantic_change(changed_surfaces(structural),prompt_evidence=("intent-contract",))
    integrity=validate_link_integrity(project_id=request.project_id,run_id=request.run_id,requirement_units=requirements,code_elements=elements,trace_links=links,behavior=behavior,verification=request.verification,trajectory=trajectory)
    gaps=[]
    if not request.verification: gaps.append("verification unavailable")
    if trajectory is None: gaps.append("trajectory unavailable")
    if not request.privacy_redacted: gaps.append("privacy handling not evidenced")
    if not integrity.qualifies: gaps.append("link integrity failed")
    matrix=tuple(RequirementEvidence(clause.requirement_id,item.clause_id,item.status.value,ClaimKind.DERIVED) for clause,item in zip(behavior.clauses,alignment))
    story=build_story(request.run_id,findings=(),matrix=matrix,trajectory=trajectory) if integrity.qualifies else None
    versions=(("deep",DEEP_ANALYSIS_VERSION),("intent",INTENT_CONTRACT_VERSION),("trace",TRACEABILITY_VERSION),("structural",STRUCTURAL_DIFF_VERSION),("semantic",SEMANTIC_CHANGE_VERSION),("behavior",BEHAVIOR_ANALYSIS_VERSION),("trajectory",TRAJECTORY_VERSION))
    return DeepAnalysisResult(request,intent,ambiguity,requirements,structural,semantic,elements,links,behavior,alignment,trajectory,integrity,story,tuple(gaps),versions)
