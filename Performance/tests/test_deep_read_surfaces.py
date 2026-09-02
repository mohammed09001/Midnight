from midnight_performance import DeepAnalysisRequest, analyze_deep, assemble_deep_story, build_requirement_matrix
def test_deep_story_and_matrix_are_rebuildable_and_keep_unknowns():
    result=analyze_deep(DeepAnalysisRequest("p","r","Build cache.",after="def cache(): pass",privacy_redacted=True))
    story=assemble_deep_story(result,agent_report=("done",),later_outcomes=("regression:1",))
    matrix=build_requirement_matrix(result.requirements,result.links,result.alignment)
    assert "User request" in story.text() and "Agent report" in story.text()
    assert any(x.requirement_id for x in matrix.entries) and "verification unavailable" in story.gaps
