from datetime import datetime, timezone
from midnight_performance import ActionCategory, EventKind, TrajectoryEvent, build_trajectory, detect_antipatterns, segment_trajectory
def e(id,kind,detail="",success=None,at=1,parent=None): return TrajectoryEvent(id,kind,datetime(2026,1,1,0,0,at,tzinfo=timezone.utc) if at else None,parent,"run",f"e:{id}","codex",detail,success)
def test_trajectory_is_deterministic_and_keeps_missing_order_and_parent_uncertainty():
    events=(e("tool",EventKind.TOOL,"search",at=2,parent="turn"),e("turn",EventKind.AGENT_TURN,at=1),e("unknown",EventKind.TOOL,at=0))
    trajectory=build_trajectory("run",events)
    assert tuple(x.id for x in trajectory.events)==("turn","tool","unknown")
    assert set(trajectory.ordering_uncertainty)=={"unknown:timestamp_unavailable"}
    assert segment_trajectory(trajectory)[0].category is ActionCategory.INSPECT
def test_phases_and_antipatterns_use_observable_events_only():
    events=(e("a",EventKind.TOOL,"cmd",False),e("b",EventKind.TOOL,"cmd",False,2),e("c",EventKind.CHANGE,"x",None,3),e("d",EventKind.VERIFY,"",False,4),e("f",EventKind.TOOL,"error",False,5))
    findings={x.kind for x in detect_antipatterns(build_trajectory("r",events))}
    assert {"repeated_failed_action","verification_fix_loop"}<=findings
