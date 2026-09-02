from midnight_performance import (
    ClaimKind, CodeElementKind, TraceState, build_requirement_units, extract_intent_contract,
    link_from_candidate, reprocess_links, resolve_code_elements, retrieve_candidates, unrequested_code_links,
    requirement_identity_map,
)

def _fixture():
    contract = extract_intent_contract("Build cache support.\n  - Verify cache behavior.")
    units = build_requirement_units("run-1", contract)
    elements = resolve_code_elements("src/engine.py", "def configure_cache():\n    return True\n\ndef ignored():\n    return False\n")
    candidates = retrieve_candidates(units, contract, elements)
    return contract, units, elements, candidates

def test_requirement_units_are_stable_and_many_to_many_candidates_are_rebuildable():
    contract, units, elements, candidates = _fixture()
    assert units == build_requirement_units("run-1", contract)
    assert units[1].parent_id == units[0].id
    assert elements[0].kind is CodeElementKind.FUNCTION
    assert candidates == retrieve_candidates(units, contract, elements)
    assert candidates and candidates[0].code_element_id == elements[0].id
    mapping = requirement_identity_map(units, contract_version=contract.version)
    assert mapping.requirement_id_for_intent(units[0].intent_element_id) == units[0].id
    assert not mapping.is_canonical_requirement_id(units[0].intent_element_id)

def test_structural_retrieval_is_symbol_aware_and_privacy_or_language_fallback_is_explicit():
    _, _, elements, _ = _fixture()
    assert elements[0].qualified_name == "configure_cache"
    unsupported = resolve_code_elements("src/engine.go", "func Cache() {}")
    denied = resolve_code_elements("src/engine.py", "def cache(): pass", source_permitted=False)
    assert unsupported[0].kind is CodeElementKind.UNKNOWN
    assert "unsupported" in unsupported[0].uncertainty
    assert denied[0].source_available is False

def test_link_lifecycle_needs_support_and_preserves_history_for_move_or_deletion():
    _, _, elements, candidates = _fixture()
    candidate = link_from_candidate(candidates[0])
    assert candidate.state is TraceState.CANDIDATE and candidate.claim_kind is ClaimKind.INFERRED
    supported = link_from_candidate(candidates[0], support_evidence=("change-set:42:symbol-edit",))
    assert supported.state is TraceState.SUPPORTED
    moved = reprocess_links((supported,), live_code_element_ids=frozenset({"code:new"}), analysis_version="2", moved_elements={supported.code_element_id: "code:new"})
    assert moved[0].code_element_id == "code:new" and moved[0].previous_version_id == "link-1"
    assert moved[0].requirement_id == supported.requirement_id
    stale = reprocess_links((supported,), live_code_element_ids=frozenset(), analysis_version="2")
    assert stale[0].state is TraceState.STALE
    unrequested = unrequested_code_links(elements, (supported,))
    assert all(item.requirement_id is None and item.state is TraceState.INSUFFICIENT_EVIDENCE for item in unrequested)
