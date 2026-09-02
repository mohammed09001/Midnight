from midnight_performance import BehaviorVerificationEvidence, CoverageKind, OracleSource, OracleStrength, assess_oracle, coverage_for, detect_divergence
from midnight_performance.interaction_policy import InteractionMode

def test_coverage_needs_executed_link_and_keeps_uncovered_changed_surface_unknown():
    reported=BehaviorVerificationEvidence("r","b",OracleSource.TEST,False,(),(),"example",True,("agent-report",),"not executed")
    executed=BehaviorVerificationEvidence("e","a",OracleSource.TEST,True,("input",),("ok",),"expected",True,("run:1",),"scoped")
    coverage={item.clause_id:item for item in coverage_for(("a","b"),(reported,executed),changed_clause_ids=("c",))}
    assert coverage["a"].kind is CoverageKind.POSITIVE
    assert coverage["b"].executed is False and coverage["c"].kind is CoverageKind.UNKNOWN

def test_divergence_and_oracle_gate_are_qualified_and_passive_is_silent():
    failed=BehaviorVerificationEvidence("f","a",OracleSource.METAMORPHIC,True,("x",),("bad",),"invariant",False,("run:2",),"failure")
    assert detect_divergence((failed,))[0].clause_id=="a"
    strong=assess_oracle("a",(BehaviorVerificationEvidence("p","a",OracleSource.TEST,True,(),(),"expected",True,("run",),"scoped"),))
    assert strong.strength is OracleStrength.STRONG
    passive=assess_oracle("missing",(),interaction_mode=InteractionMode.PASSIVE,information_gain=1)
    active=assess_oracle("missing",(),interaction_mode=InteractionMode.ACTIVE,information_gain=1)
    assert not passive.human_confirmation_suggested and active.human_confirmation_suggested
