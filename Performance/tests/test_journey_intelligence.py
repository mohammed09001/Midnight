from datetime import datetime,timezone
from midnight_performance import EventKind, TrajectoryEvent, assess_journey, build_trajectory, friction, interventions
def event(id,kind,second,detail=""): return TrajectoryEvent(id,kind,datetime(2026,1,1,0,0,second,tzinfo=timezone.utc),None,"r",id,"codex",detail)
def test_interventions_and_friction_do_not_assign_manual_edits_to_agent_or_failure():
    t=build_trajectory("r",(event("a",EventKind.CHANGE,1,"one"),event("m",EventKind.MANUAL_EDIT,2),event("s",EventKind.STEERING,3),event("b",EventKind.CHANGE,4,"one")))
    items=interventions(t,revised_by_event={"s":("intent-1",)})
    assert items[0].actor=="manual" and items[1].revised_evidence==("intent-1",)
    m=friction(t,items)
    assert m.rework_events==1 and m.manual_edit_count==1 and "provider_cost" in m.gaps
def test_journey_quality_stays_separate_from_result_quality():
    t=build_trajectory("r",(event("a",EventKind.CHANGE,1),event("v",EventKind.VERIFY,2)))
    quality=assess_journey("bugfix",friction(t,()),result_quality="achieved",verification_events=1)
    assert quality.result_quality=="achieved" and quality.rework_burden is not None
