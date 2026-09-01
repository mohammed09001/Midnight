from midnight_performance import EcosystemEvidence, ScaleRecoveryEvidence, qualify_ecosystem, qualify_scale_recovery

def test_scale_recovery_requires_measurement_and_all_recovery_boundaries():
    good = ScaleRecoveryEvidence(("ingestion", "retrieval", "memory"), True, True, True, True, True, True, True, True, True)
    assert qualify_scale_recovery(good).qualified
    bad = ScaleRecoveryEvidence((), False, False, False, False, False, False, False, False, False)
    assert "no_benchmarked_workloads" in qualify_scale_recovery(bad).failures

def test_ecosystem_requires_reference_only_end_to_end_loop_and_isolation():
    values = {name: True for name in EcosystemEvidence.__dataclass_fields__}
    assert qualify_ecosystem(EcosystemEvidence(**values)).qualified
    values["no_direct_sibling_database_reads"] = False
    assert "no_direct_sibling_database_reads" in qualify_ecosystem(EcosystemEvidence(**values)).failures
