"""Privacy-scoped descriptive profiles, matched histories, and advisory suggestions."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .contracts import ClaimKind
PERSONAL_LEARNING_VERSION="1"
@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    id:str; user_id:str|None; project_id:str; component:str|None; task_type:str; provider:str|None; observed_at:datetime; measures:dict[str,float]; evidence:tuple[str,...]
@dataclass(frozen=True, slots=True)
class PerformanceProfile:
    scope:tuple[str,...]; sample_size:int; time_range:tuple[datetime,datetime]|None; facts:dict[str,float]; missing:tuple[str,...]; claim_kind:ClaimKind; privacy_restricted:bool
@dataclass(frozen=True, slots=True)
class MatchedExperience:
    record_id:str; matched_dimensions:tuple[str,...]; differences:tuple[str,...]; comparability:float; evidence:tuple[str,...]
@dataclass(frozen=True, slots=True)
class NextTimeSuggestion:
    kind:str; text:str; context:tuple[str,...]; evidence:tuple[str,...]; confidence:float; accepted:bool|None=None; later_outcome:str|None=None; uncertainty:str="advisory association, not causal advice"
def profile(records:tuple[ExperienceRecord,...], *, project_id:str, user_id:str|None=None, raw_allowed:bool=False)->PerformanceProfile:
    rows=tuple(r for r in records if r.project_id==project_id and (user_id is None or r.user_id==user_id)); values={key:[r.measures[key] for r in rows if key in r.measures] for key in {k for r in rows for k in r.measures}}
    facts={key:round(sum(v)/len(v),3) for key,v in values.items() if v}; dates=tuple(sorted(r.observed_at for r in rows)); missing=tuple(sorted({"no_records"} if not rows else {key for key in ("verification","rework") if key not in values}))
    return PerformanceProfile((f"project:{project_id}",)+( (f"user:{user_id}",) if user_id and raw_allowed else ()),len(rows),(dates[0],dates[-1]) if dates else None,facts,missing,ClaimKind.STATISTICAL,not raw_allowed)
def match_history(query:ExperienceRecord, history:tuple[ExperienceRecord,...], *, minimum:float=.5)->tuple[MatchedExperience,...]:
    result=[]
    for item in history:
        dimensions=("project" if item.project_id==query.project_id else "","component" if item.component and item.component==query.component else "","task_type" if item.task_type==query.task_type else "","provider" if item.provider and item.provider==query.provider else "")
        matched=tuple(x for x in dimensions if x); score=len(matched)/4
        if score>=minimum: result.append(MatchedExperience(item.id,matched,tuple(name for name in ("project","component","task_type","provider") if name not in matched),score,item.evidence))
    return tuple(sorted(result,key=lambda x:(-x.comparability,x.record_id)))
def suggest_next_time(kind:str,text:str,context:tuple[str,...],matches:tuple[MatchedExperience,...],*, contradictory_evidence:tuple[str,...]=(),minimum_matches:int=2)->NextTimeSuggestion|None:
    if contradictory_evidence or len(matches)<minimum_matches: return None
    evidence=tuple(e for match in matches for e in match.evidence)
    return NextTimeSuggestion(kind,text,context,evidence,min(1,len(matches)/5))
