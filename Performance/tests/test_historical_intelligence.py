from midnight_performance import ReworkKind, lesson_candidate, recurring_surface, rework_link
def test_rework_requires_more_than_shared_file_and_preserves_alternatives():
    unknown=rework_link("r1","r2")
    assert unknown.kind is ReworkKind.UNKNOWN
    repair=rework_link("r1","r2",surface_evidence=("symbol:x",),feedback_evidence=("feedback:bug",),alternatives=("maintenance",))
    assert repair.kind is ReworkKind.REPAIR and repair.alternatives==("maintenance",)
def test_recurrence_and_lesson_candidates_gate_low_samples_and_counterexamples():
    links=(rework_link("r1","r2",revert_evidence=("git:revert",)),rework_link("r2","r3",revert_evidence=("git:revert2",)))
    recurrence=recurring_surface("symbol:x",links,verification_gaps=("v1",))
    candidate=lesson_candidate("revert pattern",("project:p","symbol:x"),recurrence,links)
    assert recurrence.sufficient and candidate.eligible_for_memory_promotion
    contradicted=lesson_candidate("revert pattern",("project:p",),recurrence,links,contradicting_runs=("r4",))
    assert not contradicted.eligible_for_memory_promotion
