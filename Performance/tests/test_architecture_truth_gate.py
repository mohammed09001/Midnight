from midnight_performance import ArchitectureTruthEvidence, audit_architecture_truth

def test_final_architecture_truth_gate_requires_every_product_boundary():
    values = {name: True for name in ArchitectureTruthEvidence.__dataclass_fields__}
    assert audit_architecture_truth(ArchitectureTruthEvidence(**values)).passed
    values["repository_evidence_over_prose"] = False
    values["independently_useful_without_siblings_ai_graphrag"] = False
    gate = audit_architecture_truth(ArchitectureTruthEvidence(**values))
    assert set(gate.failures) == {"repository_evidence_over_prose", "independently_useful_without_siblings_ai_graphrag"}
