from midnight_performance import (
    BehaviorVerificationEvidence, IntegrityMode, IntegritySeverity, OracleSource,
    TraceState, behavior_contract, build_requirement_units, extract_intent_contract,
    infer_specification, link_from_candidate, resolve_code_elements, retrieve_candidates,
    validate_link_integrity,
)

def _chain():
    intent = extract_intent_contract("Build cache.")
    units = build_requirement_units("run-1", intent)
    elements = resolve_code_elements("cache.py", "def cache(): pass")
    link = link_from_candidate(retrieve_candidates(units, intent, elements)[0], support_evidence=("change:cache",))
    behavior = behavior_contract("project-a", infer_specification("project-a", intent), requirement_units=units, intent_contract_version=intent.version)
    return units, elements, link, behavior

def test_clean_production_chain_has_no_material_integrity_finding():
    units, elements, link, behavior = _chain()
    evidence = BehaviorVerificationEvidence("verify-1", behavior.clauses[0].id, OracleSource.TEST, True, (), (), "passes", True, ("test:cache",), "scoped")
    report = validate_link_integrity(project_id="project-a", run_id="run-1", requirement_units=units, code_elements=elements, trace_links=(link,), behavior=behavior, verification=(evidence,))
    assert report.qualifies and not report.findings

def test_validator_detects_dangling_and_cross_project_references():
    units, elements, link, behavior = _chain()
    dangling = link_from_candidate(type("Candidate", (), {"requirement_id":"requirement:gone", "code_element_id":link.code_element_id, "score":.5, "evidence":(), "uncertainty":"test"})(), support_evidence=("change",))
    report = validate_link_integrity(project_id="project-a", run_id="run-1", requirement_units=units, code_elements=elements, trace_links=(dangling,), behavior=behavior, reference_projects={"requirement:gone":"project-b"})
    assert {item.kind for item in report.findings} >= {"dangling_requirement", "cross_project_reference"}
    assert not report.qualifies

def test_stale_historical_requirement_is_qualified_but_strict_mode_excludes_it():
    units, elements, link, behavior = _chain()
    stale = type(link)("requirement:old", link.code_element_id, TraceState.STALE, "2", link.evidence, link.candidate_score, link.method, link.method_version, link.claim_kind, link.uncertainty)
    diagnostic = validate_link_integrity(project_id="project-a", run_id="run-1", requirement_units=units, code_elements=elements, trace_links=(stale,), behavior=behavior, historical_requirement_ids=frozenset({"requirement:old"}))
    strict = validate_link_integrity(project_id="project-a", run_id="run-1", requirement_units=units, code_elements=elements, trace_links=(stale,), behavior=behavior, historical_requirement_ids=frozenset({"requirement:old"}), mode=IntegrityMode.STRICT)
    assert diagnostic.qualifies and diagnostic.findings[0].qualified_historical
    assert strict.qualifies and not strict.findings
