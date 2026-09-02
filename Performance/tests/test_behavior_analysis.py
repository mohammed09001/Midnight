from midnight_performance import (
    BehaviorStatus, ClaimKind, TraceState, align_behavior, behavior_contract, build_requirement_units,
    extract_intent_contract, infer_specification, link_from_candidate, refine_hypothesis, retrieve_candidates,
    resolve_code_elements, TraceCandidate,
)

def test_hypotheses_separate_explicit_intent_and_repository_evidence_and_preserve_versions():
    hypotheses = infer_specification("project-a", extract_intent_contract("Acceptance: cache responses.\nVerify cache behavior."), repository_evidence=("repo:cache.py",), test_evidence=("test:cache",))
    assert hypotheses[0].claim_kind is ClaimKind.OBSERVED
    refined = refine_hypothesis(hypotheses[0], contradictions=("runtime:wrong-result",), analysis_version="2")
    assert refined.previous_id == hypotheses[0].id and refined.contradictions
    serialized = behavior_contract("project-a", hypotheses)
    assert serialized.version and serialized.clauses[0].project_id == "project-a"

def test_behavior_alignment_requires_oracle_not_path_or_trace_alone():
    contract = extract_intent_contract("Build cache.")
    units = build_requirement_units("run-cache", contract)
    hypothesis = infer_specification("p", contract)[0]
    behavior = behavior_contract("p", (hypothesis,), requirement_units=units, intent_contract_version=contract.version)
    candidate = retrieve_candidates(units, contract, resolve_code_elements("cache.py", "def cache(): pass"))[0]
    link = link_from_candidate(candidate, support_evidence=("change:symbol",))
    partial = align_behavior(behavior, (link,))
    assert partial[0].status is BehaviorStatus.PARTIALLY_SATISFIED
    satisfied = align_behavior(behavior, (link,), executed_oracles=("verification:executed",))
    assert satisfied[0].status is BehaviorStatus.SATISFIED
    contradicted = align_behavior(behavior, (link,), contradictory_evidence=("runtime:counterexample",))
    assert contradicted[0].status is BehaviorStatus.CONTRADICTED

def test_behavior_alignment_rejects_source_provenance_as_canonical_identity():
    intent = extract_intent_contract("Build cache.")
    units = build_requirement_units("run-cache", intent)
    behavior = behavior_contract("p", infer_specification("p", intent), requirement_units=units, intent_contract_version=intent.version)
    # This old test-shaped identity is source provenance, never a production requirement id.
    candidate = TraceCandidate("intent-1", "code:cache", .8, ("identifier:cache",), "test", "1", ClaimKind.INFERRED, "candidate")
    alignment = align_behavior(behavior, (link_from_candidate(candidate, support_evidence=("change:cache",)),), executed_oracles=("verification:executed",))
    assert alignment[0].status is BehaviorStatus.INSUFFICIENT_EVIDENCE

def test_behavior_alignment_keeps_candidate_contradicted_and_stale_links_non_satisfying():
    intent = extract_intent_contract("Build cache.")
    units = build_requirement_units("run-cache", intent)
    behavior = behavior_contract("p", infer_specification("p", intent), requirement_units=units, intent_contract_version=intent.version)
    candidate = retrieve_candidates(units, intent, resolve_code_elements("cache.py", "def cache(): pass"))[0]
    candidate_link = link_from_candidate(candidate)
    contradicted = link_from_candidate(candidate, contradictory_evidence=("runtime:wrong",))
    stale = type(contradicted)(contradicted.requirement_id, contradicted.code_element_id, TraceState.STALE, "2", contradicted.evidence, contradicted.candidate_score, contradicted.method, contradicted.method_version, contradicted.claim_kind, contradicted.uncertainty)
    assert align_behavior(behavior, (candidate_link,), executed_oracles=("verification:executed",))[0].status is BehaviorStatus.PARTIALLY_SATISFIED
    assert align_behavior(behavior, (contradicted,), executed_oracles=("verification:executed",))[0].status is BehaviorStatus.INSUFFICIENT_EVIDENCE
    assert align_behavior(behavior, (stale,), executed_oracles=("verification:executed",))[0].status is BehaviorStatus.INSUFFICIENT_EVIDENCE
