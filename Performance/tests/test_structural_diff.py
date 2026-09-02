from midnight_performance import (
    ClaimKind, SemanticLabel, StructuralEditKind, SurfaceKind, blast_radius,
    changed_surfaces, classify_semantic_change, structural_diff,
)

def test_python_structural_diff_reports_rename_move_update_and_raw_provenance():
    rename = structural_diff("src/a.py", "def old():\n return 1\n", "def new():\n return 1\n", raw_evidence=("change:1",))
    assert rename.edits[0].kind is StructuralEditKind.RENAME
    assert rename.edits[0].raw_evidence == ("change:1",)
    move = structural_diff("src/a.py", "def a():\n return 1\n\ndef b():\n return 2\n", "def b():\n return 2\n\ndef a():\n return 1\n")
    assert {item.kind for item in move.edits} == {StructuralEditKind.MOVE}
    update = structural_diff("src/a.py", "def a():\n return 1\n", "def a():\n return 2\n")
    assert update.edits[0].kind is StructuralEditKind.UPDATE

def test_unsupported_and_multi_symbol_surface_are_explicit_and_deterministic():
    unsupported = structural_diff("src/a.go", "func A() {}", "func A() { }")
    assert unsupported.supported is False and unsupported.edits[0].kind is StructuralEditKind.UNRESOLVED
    diff = structural_diff("src/a.py", "def a():\n return 1\n", "def a():\n return 2\n\ndef b():\n return 3\n")
    surfaces = changed_surfaces(diff)
    assert all(item.surface is SurfaceKind.SOURCE for item in surfaces)
    radius = blast_radius(surfaces, neighborhoods=("callers:a",))
    assert radius.files == ("src/a.py",) and radius.neighborhoods == ("callers:a",)

def test_semantic_events_keep_structural_facts_and_ai_parity():
    diff = structural_diff("src/a.py", "def a():\n return 1\n", "def a():\n return 2\n")
    surfaces = changed_surfaces(diff)
    disabled = classify_semantic_change(surfaces)
    enabled = classify_semantic_change(surfaces, ai_evidence=("optional:analysis-1",))
    assert disabled.structural_evidence == enabled.structural_evidence
    assert SemanticLabel.BEHAVIOR_AFFECTING in disabled.labels
    assert disabled.claim_kind is ClaimKind.INFERRED
    test_event = classify_semantic_change(changed_surfaces(structural_diff("tests/test_a.py", "def test_a():\n assert 1\n", "def test_a():\n assert 2\n")))
    assert SemanticLabel.TEST in test_event.labels
