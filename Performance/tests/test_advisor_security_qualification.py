from midnight_performance import AdvisorQualificationEvidence, SecurityIsolationEvidence, qualify_advisor, qualify_security_isolation

def test_advisor_requires_user_relevant_benefit_across_all_evidence_stages():
    good = qualify_advisor(AdvisorQualificationEvidence(True, True, True, True, True, 3))
    assert good.qualified
    bad = qualify_advisor(AdvisorQualificationEvidence(True, True, False, False, True, 3))
    assert {"opt_in_real_use_unproven", "user_relevant_outcome_unimproved", "internal_metric_optimization_only"} <= set(bad.failures)

def test_security_isolation_requires_full_matrix_and_siblings_absent_usefulness():
    values = {name: True for name in SecurityIsolationEvidence.__dataclass_fields__}
    assert qualify_security_isolation(SecurityIsolationEvidence(**values)).qualified
    values["siblings_absent_usable"] = False
    assert "siblings_absent_usable" in qualify_security_isolation(SecurityIsolationEvidence(**values)).failures
