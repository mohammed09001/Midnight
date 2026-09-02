from midnight_performance import (
    BehaviorStatus, ClaimKind, TraceState, align_behavior, behavior_contract,
    extract_intent_contract, infer_specification, link_from_candidate, refine_hypothesis,
)
from midnight_performance.traceability import TraceCandidate

def test_hypotheses_separate_explicit_intent_and_repository_evidence_and_preserve_versions():
    hypotheses = infer_specification("project-a", extract_intent_contract("Acceptance: cache responses.\nVerify cache behavior."), repository_evidence=("repo:cache.py",), test_evidence=("test:cache",))
    assert hypotheses[0].claim_kind is ClaimKind.OBSERVED
    refined = refine_hypothesis(hypotheses[0], contradictions=("runtime:wrong-result",), analysis_version="2")
    assert refined.previous_id == hypotheses[0].id and refined.contradictions
    serialized = behavior_contract("project-a", hypotheses)
    assert serialized.version and serialized.clauses[0].project_id == "project-a"

def test_behavior_alignment_requires_oracle_not_path_or_trace_alone():
    contract = extract_intent_contract("Build cache.")
    hypothesis = infer_specification("p", contract)[0]
    behavior = behavior_contract("p", (hypothesis,))
    candidate = TraceCandidate("intent-1", "symbol:cache", .8, ("identifier:cache",), "test", "1", ClaimKind.INFERRED, "candidate")
    link = link_from_candidate(candidate, support_evidence=("change:symbol",))
    partial = align_behavior(behavior, (link,))
    assert partial[0].status is BehaviorStatus.PARTIALLY_SATISFIED
    satisfied = align_behavior(behavior, (link,), executed_oracles=("verification:executed",))
    assert satisfied[0].status is BehaviorStatus.SATISFIED
    contradicted = align_behavior(behavior, (link,), contradictory_evidence=("runtime:counterexample",))
    assert contradicted[0].status is BehaviorStatus.CONTRADICTED
