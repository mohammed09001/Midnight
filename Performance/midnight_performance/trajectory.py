"""Rebuildable observable development trajectories; never hidden reasoning."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from .contracts import ClaimKind
TRAJECTORY_VERSION="1"
class EventKind(str, Enum): PROMPT="prompt"; STEERING="steering"; AGENT_TURN="agent_turn"; TOOL="tool"; RESULT="result"; CHANGE="change"; VERIFY="verify"; INTERRUPTION="interruption"; RESUMPTION="resumption"; MANUAL_EDIT="manual_edit"; FINAL_REPORT="final_report"; UNKNOWN="unknown"
class ActionCategory(str, Enum): INSPECT="inspect"; SEARCH="search"; EDIT="edit"; VERIFY="verify"; DIAGNOSE="diagnose"; COMMUNICATE="communicate"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class TrajectoryEvent:
    id:str; kind:EventKind; observed_at:datetime|None; parent_id:str|None; correlation_id:str; evidence_id:str; provider:str|None=None; detail:str=""; success:bool|None=None
@dataclass(frozen=True, slots=True)
class Trajectory:
    run_id:str; events:tuple[TrajectoryEvent,...]; ordering_uncertainty:tuple[str,...]; version:str=TRAJECTORY_VERSION
@dataclass(frozen=True, slots=True)
class JourneyPhase:
    category:ActionCategory; event_ids:tuple[str,...]; start_index:int; end_index:int
@dataclass(frozen=True, slots=True)
class JourneyFinding:
    kind:str; event_ids:tuple[str,...]; claim_kind:ClaimKind; uncertainty:str
def build_trajectory(run_id:str, events:tuple[TrajectoryEvent,...]) -> Trajectory:
    if len({e.id for e in events})!=len(events): raise ValueError("trajectory event ids must be unique")
    ids={e.id for e in events}; gaps=tuple(f"{e.id}:parent_unavailable" for e in events if e.parent_id and e.parent_id not in ids)
    # Stable tie-breaker preserves deterministic replay but does not imply causal ordering.
    ordered=tuple(sorted(events,key=lambda e:(e.observed_at is None,e.observed_at or datetime.min,e.id)))
    gaps+=tuple(f"{e.id}:timestamp_unavailable" for e in ordered if e.observed_at is None)
    return Trajectory(run_id,ordered,gaps)
def categorize(event:TrajectoryEvent)->ActionCategory:
    if event.kind in {EventKind.CHANGE,EventKind.MANUAL_EDIT}: return ActionCategory.EDIT
    if event.kind is EventKind.VERIFY: return ActionCategory.VERIFY
    if event.kind is EventKind.STEERING or event.kind is EventKind.PROMPT: return ActionCategory.COMMUNICATE
    low=event.detail.lower()
    if "search" in low or "find" in low: return ActionCategory.SEARCH
    if "error" in low or event.success is False: return ActionCategory.DIAGNOSE
    if event.kind in {EventKind.TOOL,EventKind.AGENT_TURN}: return ActionCategory.INSPECT
    return ActionCategory.UNKNOWN
def segment(trajectory:Trajectory)->tuple[JourneyPhase,...]:
    categories=[categorize(e) for e in trajectory.events]; result=[]; start=0
    for index in range(1,len(categories)+1):
        if index==len(categories) or categories[index]!=categories[start]:
            result.append(JourneyPhase(categories[start],tuple(e.id for e in trajectory.events[start:index]),start,index-1)); start=index
    return tuple(result)
def detect_antipatterns(trajectory:Trajectory, *, task_type:str="development")->tuple[JourneyFinding,...]:
    events=trajectory.events; findings=[]
    for index in range(1,len(events)):
        a,b=events[index-1:index+1]
        if a.kind is b.kind is EventKind.TOOL and a.detail==b.detail and a.success is b.success is False: findings.append(JourneyFinding("repeated_failed_action",(a.id,b.id),ClaimKind.DERIVED,"two identical observable failed actions; may be normal recovery"))
        if a.kind is b.kind is EventKind.CHANGE and a.detail==b.detail: findings.append(JourneyFinding("edit_revert_cycle",(a.id,b.id),ClaimKind.DERIVED,"matching change evidence may not prove a true revert"))
    phases=segment(trajectory)
    for index in range(len(phases)-2):
        if [p.category for p in phases[index:index+3]]==[ActionCategory.EDIT,ActionCategory.VERIFY,ActionCategory.DIAGNOSE]: findings.append(JourneyFinding("verification_fix_loop",sum((p.event_ids for p in phases[index:index+3]),()),ClaimKind.DERIVED,"one loop can be healthy; task context is "+task_type))
    return tuple(findings)
