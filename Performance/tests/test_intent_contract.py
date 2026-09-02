from midnight_performance import (
    AmbiguityKind, CapabilityEvidence, CapabilityState, ImprovementCapabilityGap,
    IntentKind, ResolutionStatus, analyze_ambiguity, analyze_prompt,
    establish_improvement_gate, extract_intent_contract,
)

def test_contract_preserves_exact_spans_nested_structure_and_explicit_kinds():
    text = "Build the parser.\n  - Do not send prompt text externally.\n  - Verify with tests.\nAcceptance: all tests pass.\nReference: https://example.test/spec"
    contract = extract_intent_contract(text)
    assert [item.kind for item in contract.elements] == [IntentKind.GOAL, IntentKind.CONSTRAINT, IntentKind.VERIFICATION, IntentKind.ACCEPTANCE, IntentKind.REFERENCE]
    assert contract.elements[1].parent_id == contract.elements[0].id
    for item in contract.elements:
        assert text[item.span.start:item.span.end] == item.text
    features, _ = analyze_prompt(text)
    assert features.version == "2"
    assert features.intent_contract == contract

def test_ambiguity_keeps_competing_constraints_and_oracle_gaps_qualified():
    contract = extract_intent_contract("Must use cache.\nDo not use cache.\nFix it.")
    report = analyze_ambiguity(contract)
    kinds = {item.kind for item in report.findings}
    assert AmbiguityKind.CONFLICT in kinds
    assert AmbiguityKind.UNRESOLVED_REFERENT in kinds
    assert AmbiguityKind.MISSING_VERIFICATION_ORACLE in kinds
    assert all(item.status is ResolutionStatus.OPEN for item in report.findings)

def test_repository_resolution_and_steering_are_recorded_not_assumed():
    contract = extract_intent_contract("Fix it.")
    item = contract.elements[0]
    resolved = analyze_ambiguity(contract, repository_resolutions={item.id: ("src/parser.py:1",)})
    finding = next(item for item in resolved.findings if item.kind is AmbiguityKind.UNRESOLVED_REFERENT)
    assert finding.status is ResolutionStatus.RESOLVED
    assert finding.repository_evidence == ("src/parser.py:1",)
    steered = analyze_ambiguity(contract, steering_resolved=frozenset({item.id}))
    assert next(item for item in steered.findings if item.kind is AmbiguityKind.UNRESOLVED_REFERENT).status is ResolutionStatus.CHANGED_BY_STEERING

def test_capability_gate_requires_evidence_and_preserves_owner_extension():
    gap = ImprovementCapabilityGap("prompt analysis", CapabilityState.PRESENT_SHALLOW, "prompt_analysis.py", ("prompt_analysis.py",), (CapabilityEvidence("prompt_analysis.py", "line-based extraction"),))
    gate = establish_improvement_gate((gap,))
    assert gate.for_capability("prompt analysis") == gap
