"""Qualified cross-run rework, recurrence, and Memory lesson candidates."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ClaimKind
HISTORICAL_INTELLIGENCE_VERSION="1"
class ReworkKind(str, Enum): DIRECT_REVERT="direct_revert"; REPAIR="repair"; CONCEPTUAL_REWORK="conceptual_rework"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class ReworkLink:
    earlier_run:str; later_run:str; kind:ReworkKind; evidence:tuple[str,...]; confidence:float; alternatives:tuple[str,...]; user_corrected:bool=False
@dataclass(frozen=True, slots=True)
class RecurringSurface:
    surface_id:str; run_ids:tuple[str,...]; symptom_ids:tuple[str,...]; root_cause_ids:tuple[str,...]; verification_gaps:tuple[str,...]; sufficient:bool; uncertainty:str
@dataclass(frozen=True, slots=True)
class LessonCandidate:
    statement:str; scope:tuple[str,...]; supporting_runs:tuple[str,...]; contradicting_runs:tuple[str,...]; evidence:tuple[str,...]; eligible_for_memory_promotion:bool; expiration_condition:str; uncertainty:str
def rework_link(earlier_run:str,later_run:str,*,revert_evidence:tuple[str,...]=(),surface_evidence:tuple[str,...]=(),feedback_evidence:tuple[str,...]=(),alternatives:tuple[str,...]=())->ReworkLink:
    evidence=revert_evidence+surface_evidence+feedback_evidence
    kind=ReworkKind.DIRECT_REVERT if revert_evidence else ReworkKind.REPAIR if surface_evidence and feedback_evidence else ReworkKind.CONCEPTUAL_REWORK if surface_evidence else ReworkKind.UNKNOWN
    return ReworkLink(earlier_run,later_run,kind,evidence,.9 if revert_evidence else (.5 if evidence else 0),alternatives)
def recurring_surface(surface_id:str, links:tuple[ReworkLink,...], *, symptoms:tuple[str,...]=(), root_causes:tuple[str,...]=(), verification_gaps:tuple[str,...]=(), minimum_runs:int=2)->RecurringSurface:
    runs=tuple(sorted({x for link in links for x in (link.earlier_run,link.later_run)})); sufficient=len(runs)>=minimum_runs
    return RecurringSurface(surface_id,runs,symptoms,root_causes,verification_gaps,sufficient,"same surface/symptom/root cause are distinct; low samples are suppressed")
def lesson_candidate(statement:str,scope:tuple[str,...],recurrence:RecurringSurface,links:tuple[ReworkLink,...],*,contradicting_runs:tuple[str,...]=(),minimum_runs:int=3)->LessonCandidate:
    supporting=recurrence.run_ids; evidence=tuple(item for link in links for item in link.evidence)
    eligible=len(supporting)>=minimum_runs and bool(evidence) and not contradicting_runs and recurrence.sufficient
    return LessonCandidate(statement,scope,supporting,contradicting_runs,evidence,eligible,"supersede when later scoped evidence contradicts or component/provider changes", "candidate only; requires existing Memory promotion path and never establishes causation")
