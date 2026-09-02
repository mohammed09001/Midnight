"""Intervention, friction, and journey-quality projections separate from outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ClaimKind
from .trajectory import EventKind, Trajectory
JOURNEY_INTELLIGENCE_VERSION="1"
class InterventionKind(str, Enum): STEERING="steering"; FEEDBACK="feedback"; STOP="stop"; RESUME="resume"; MANUAL_EDIT="manual_edit"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class Intervention:
    id:str; kind:InterventionKind; event_id:str; revised_evidence:tuple[str,...]; in_run:bool; actor:str; privacy_reference:str; uncertainty:str
@dataclass(frozen=True, slots=True)
class FrictionMetrics:
    active_seconds:float|None; wall_seconds:float|None; provider_cost:float|None; provider_tokens:int|None; rework_events:int; intervention_count:int; manual_edit_count:int; gaps:tuple[str,...]
@dataclass(frozen=True, slots=True)
class JourneyQuality:
    task_type:str; evidence_discipline:float|None; verification_responsiveness:float|None; rework_burden:float|None; intervention_burden:float|None; cost_completeness:float|None; result_quality:object|None; uncertainty:tuple[str,...]
def interventions(trajectory:Trajectory, *, revised_by_event:dict[str,tuple[str,...]]|None=None)->tuple[Intervention,...]:
    revised_by_event=revised_by_event or {}; out=[]
    for event in trajectory.events:
        mapping={EventKind.STEERING:(InterventionKind.STEERING,True),EventKind.INTERRUPTION:(InterventionKind.STOP,True),EventKind.RESUMPTION:(InterventionKind.RESUME,True),EventKind.MANUAL_EDIT:(InterventionKind.MANUAL_EDIT,True)}
        if event.kind in mapping:
            kind,in_run=mapping[event.kind]; out.append(Intervention(event.id,kind,event.id,revised_by_event.get(event.id,()),in_run,"user" if kind is not InterventionKind.MANUAL_EDIT else "manual","event:"+event.evidence_id,"manual edits are not attributed to an agent" if kind is InterventionKind.MANUAL_EDIT else "intervention does not establish error"))
    return tuple(out)
def friction(trajectory:Trajectory, items:tuple[Intervention,...], *, provider_cost:float|None=None, provider_tokens:int|None=None)->FrictionMetrics:
    timed=[e.observed_at for e in trajectory.events if e.observed_at]; wall=(timed[-1]-timed[0]).total_seconds() if len(timed)>1 else None
    # Event timestamps support elapsed duration, not proof that all gap time was active work.
    active=None if wall is None else sum(max(0,(timed[i]-timed[i-1]).total_seconds()) for i in range(1,len(timed)) if (timed[i]-timed[i-1]).total_seconds()<300)
    rework=sum(e.kind is EventKind.CHANGE for e in trajectory.events)-len({e.detail for e in trajectory.events if e.kind is EventKind.CHANGE})
    gaps=tuple(name for name,value in (("provider_cost",provider_cost),("provider_tokens",provider_tokens),("timestamps",wall)) if value is None)
    return FrictionMetrics(active,wall,provider_cost,provider_tokens,max(0,rework),len(items),sum(i.kind is InterventionKind.MANUAL_EDIT for i in items),gaps)
def assess_journey(task_type:str, metrics:FrictionMetrics, *, result_quality:object|None=None, verification_events:int=0)->JourneyQuality:
    denom=max(1,metrics.intervention_count+metrics.rework_events+1)
    return JourneyQuality(task_type,1.0 if metrics.active_seconds is not None else None,min(1,verification_events/denom),max(0,1-metrics.rework_events/denom),max(0,1-metrics.intervention_count/denom),None if metrics.provider_cost is None and metrics.provider_tokens is None else 1.0,result_quality,("journey dimensions are derived and not a global grade",))
