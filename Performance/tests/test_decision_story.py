from datetime import datetime,timezone
from midnight_performance import ClaimKind,FrictionMetrics,RequirementEvidence,StoryFinding,TrajectoryEvent,build_story,build_trajectory
from midnight_performance.trajectory import EventKind
def test_story_keeps_evidence_matrix_redaction_and_inline_unknowns():
    trajectory=build_trajectory("r",(TrajectoryEvent("a",EventKind.TOOL,datetime(2026,1,1,tzinfo=timezone.utc),None,"r","e"),))
    story=build_story("r",findings=(StoryFinding("verified under test",ClaimKind.DERIVED,("v1",),"scoped"),),matrix=(RequirementEvidence("req","symbol:x","partial",ClaimKind.DERIVED),RequirementEvidence(None,"manual", "unrequested",ClaimKind.OBSERVED,True)),trajectory=trajectory,friction=FrictionMetrics(None,None,None,None,0,0,0,("cost",)))
    assert "What happened" in story.text() and "manual:redacted" in story.gaps and len(story.matrix)==2
