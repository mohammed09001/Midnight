"""Task 23 (Midnight Memory Execution 08): the Memory+Performance
compatibility gate must both pass truthfully on a healthy checkout and fail
with a correctly-named clause on a genuinely broken one — proving it is a
real gate, not a rubber stamp."""
import shutil
from pathlib import Path

import pytest

from midnight_performance import run_compatibility_gate

_MEMORY_REPO_PATH = Path(__file__).resolve().parents[2] / "Memory"
_NODE_AVAILABLE = shutil.which("node") is not None


@pytest.mark.skipif(not _NODE_AVAILABLE, reason="node not available in this environment")
def test_compatibility_gate_passes_on_a_healthy_checkout():
    report = run_compatibility_gate(memory_repo_path=_MEMORY_REPO_PATH, test_suite_timeout_seconds=180)
    failing = [
        (clause.clause, check.name, check.detail)
        for clause in report.clauses
        for check in clause.checks
        if not check.passed
    ]
    assert report.passed, f"expected a healthy checkout to pass; failing checks: {failing}"
    clause_names = {clause.clause for clause in report.clauses}
    assert clause_names == {
        "memory_product_truth",
        "performance_to_memory_propose",
        "memory_to_performance_read",
        "standalone_degraded_operation",
        "no_local_duplicate_authority",
        "cross_language_test_suites",
    }
    # memory_product_truth must genuinely flatten Memory's own 8 gate.ts
    # clauses in, not just report one opaque check.
    memory_clause = next(c for c in report.clauses if c.clause == "memory_product_truth")
    assert len(memory_clause.checks) > 8


def test_compatibility_gate_fails_with_the_correct_named_clause_when_memory_is_unreachable():
    # No node gate here on purpose: this must fail identically whether or
    # not node is installed, since the failure is injected via a bad
    # node_executable regardless.
    report = run_compatibility_gate(
        memory_repo_path=_MEMORY_REPO_PATH,
        node_executable="definitely-not-a-real-binary-xyz",
        timeout_seconds=5,
    )
    assert report.passed is False
    failing_clauses = {clause.clause for clause in report.clauses if not clause.passed}
    # These three clauses call Memory directly and must fail; the other
    # three are Memory-unreachable-agnostic (or specifically test
    # unreachability) and must NOT be swept into a false failure.
    assert failing_clauses == {"memory_product_truth", "performance_to_memory_propose", "memory_to_performance_read"}
    standalone_clause = next(c for c in report.clauses if c.clause == "standalone_degraded_operation")
    assert standalone_clause.passed, "standalone_degraded_operation specifically proves truthful degrade — it must still pass"
    duplicate_authority_clause = next(c for c in report.clauses if c.clause == "no_local_duplicate_authority")
    assert duplicate_authority_clause.passed, "a structural, Memory-independent check must be unaffected by Memory being unreachable"
