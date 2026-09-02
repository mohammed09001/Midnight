"""Longitudinal decision projections with qualified, non-causal outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ClaimKind, ExternalReference
DECISION_INTELLIGENCE_VERSION="1"
class DecisionState(str, Enum): OPEN="open"; REMEDIATED="remediated"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class DecisionEpisode:
    id:str; project_id:str; prompt_runs:tuple[str,...]; implementation_evidence:tuple[str,...]; manual_change_evidence:tuple[str,...]; sibling_outcomes:tuple[ExternalReference,...]; state:DecisionState; competing_decision_ids:tuple[str,...]; uncertainty:str
@dataclass(frozen=True, slots=True)
class SurfaceLineage:
    surface_id:str; run_ids:tuple[str,...]; continuity:float|None; intervening_changes:tuple[str,...]; ambiguous:bool; outcome_window_refs:tuple[ExternalReference,...]; uncertainty:str
@dataclass(frozen=True, slots=True)
class DecisionQuality:
    decision_id:str; achieved_intent:float|None; durability:float|None; regression_rework:float|None; verification_strength:float|None; later_outcomes:tuple[ExternalReference,...]; alternatives:tuple[str,...]; conclusion:ClaimKind; uncertainty:str
def decision_episode(id:str, project_id:str, *, prompt_runs:tuple[str,...], implementation_evidence:tuple[str,...], manual_change_evidence:tuple[str,...]=(), sibling_outcomes:tuple[ExternalReference,...]=(), competing_decision_ids:tuple[str,...]=(), remediated:bool=False)->DecisionEpisode:
    return DecisionEpisode(id,project_id,prompt_runs,implementation_evidence,manual_change_evidence,sibling_outcomes,DecisionState.REMEDIATED if remediated else DecisionState.OPEN,competing_decision_ids,"derived historical association; external outcomes remain sibling-authoritative references")
def surface_lineage(surface_id:str, run_ids:tuple[str,...], *, continuity:float|None, intervening_changes:tuple[str,...]=(), outcome_window_refs:tuple[ExternalReference,...]=())->SurfaceLineage:
    if continuity is not None and not 0<=continuity<=1: raise ValueError("continuity must be between zero and one")
    ambiguous=continuity is None or continuity<.5 or bool(intervening_changes)
    return SurfaceLineage(surface_id,run_ids,continuity,intervening_changes,ambiguous,outcome_window_refs,"lineage is structural continuity, not proof an outcome was caused by this decision")
def assess_decision(episode:DecisionEpisode, lineages:tuple[SurfaceLineage,...], *, achieved_intent:float|None, verification_strength:float|None, later_regression:bool|None, alternatives:tuple[str,...]=())->DecisionQuality:
    evidence_ok=bool(episode.implementation_evidence) and achieved_intent is not None and verification_strength is not None
    ambiguity=any(item.ambiguous for item in lineages)
    durability=None if later_regression is None or ambiguity else (0.0 if later_regression else 1.0)
    rework=None if not episode.manual_change_evidence else 0.0
    conclusion=ClaimKind.DERIVED if evidence_ok else ClaimKind.UNKNOWN
    return DecisionQuality(episode.id,achieved_intent,durability,rework,verification_strength,episode.sibling_outcomes,alternatives,conclusion,"association only; intervening changes and alternatives prevent causal attribution" if ambiguity or alternatives else "outcome window remains incomplete")
