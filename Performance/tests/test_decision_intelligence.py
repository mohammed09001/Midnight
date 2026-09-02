from midnight_performance import ClaimKind, ExternalReference, assess_decision, decision_episode, surface_lineage
def test_open_decision_episode_uses_bounded_sibling_reference_and_manual_changes():
    ref=ExternalReference("watch","outcome","o1")
    episode=decision_episode("d","p",prompt_runs=("r1",),implementation_evidence=("change:1",),manual_change_evidence=("manual:1",),sibling_outcomes=(ref,))
    assert episode.state.value=="open" and episode.sibling_outcomes==(ref,)
def test_lineage_and_quality_keep_intervening_changes_and_causality_uncertain():
    episode=decision_episode("d","p",prompt_runs=("r1","r2"),implementation_evidence=("change:1",))
    lineage=surface_lineage("symbol:x",("r1","r2"),continuity=.9,intervening_changes=("change:other",))
    quality=assess_decision(episode,(lineage,),achieved_intent=1,verification_strength=.8,later_regression=True,alternatives=("unrelated deployment",))
    assert lineage.ambiguous and quality.durability is None and quality.conclusion is ClaimKind.DERIVED
    incomplete=assess_decision(episode,(),achieved_intent=None,verification_strength=None,later_regression=None)
    assert incomplete.conclusion is ClaimKind.UNKNOWN
