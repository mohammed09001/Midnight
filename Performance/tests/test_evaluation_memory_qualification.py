from datetime import datetime, timezone
from pathlib import Path

from midnight_performance import (
    AIAnalysisAttempt, ClaimKind, EvaluationResult, EvaluatorKind,
    MemoryDomain, MemoryEvidence, ReviewLabel,
    qualify_evaluators, qualify_memory_integration,
)
from midnight_performance.memory_bridge import build_propose_envelope

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)
_MEMORY_REPO_PATH = Path(__file__).resolve().parents[2] / "Memory"


def test_evaluator_qualification_requires_non_llm_reproducible_evidence():
    deterministic = EvaluationResult("run", "coverage", "1", EvaluatorKind.DETERMINISTIC, .9, (), "ok", 1, ClaimKind.DERIVED)
    judge = EvaluationResult("run", "judge", "1", EvaluatorKind.MODEL_JUDGE, .8, (), "ok", .5, ClaimKind.INFERRED)
    label = ReviewLabel("run", "user", "pass", .8, (), (), NOW)
    result = qualify_evaluators("run", (deterministic, judge), (label,), True, (AIAnalysisAttempt("local", "1", "m", 1, None, True),), reproducible=True)
    assert result.qualified and result.variance is not None
    only_judge = qualify_evaluators("run", (judge,), (), True, (), reproducible=True)
    assert "llm_judge_is_sole_evidence" in only_judge.failures


def test_memory_evidence_remains_a_local_non_durable_shape():
    # MemoryDomain/MemoryEvidence are kept (Execution 04 migration map):
    # Performance-local, non-durable evidence-candidate shapes only.
    good = MemoryEvidence("a", MemoryDomain.KNOWLEDGE, ("raw:1",), "tests pass", ClaimKind.OBSERVED)
    assert good.statement == "tests pass"


def test_memory_integration_structural_check_always_passes_with_no_envelope():
    result = qualify_memory_integration()
    assert result.no_local_duplicate_authority is True
    assert result.delivery is None
    assert result.degraded_mode_truthful is True
    assert result.qualified is True
    assert result.failures == ()


def test_memory_integration_degraded_mode_is_truthful_when_memory_is_unreachable():
    envelope = build_propose_envelope("proj", [])
    result = qualify_memory_integration(
        envelope=envelope,
        memory_repo_path=_MEMORY_REPO_PATH,
        node_executable="definitely-not-a-real-binary-xyz",
    )
    assert result.no_local_duplicate_authority is True
    assert result.delivery is not None
    assert result.delivery.delivered is False
    assert result.delivery.degraded_reason is not None
    # A truthful degraded report still qualifies the gate — it is honest
    # reporting, not a fabricated success or a swallowed exception.
    assert result.degraded_mode_truthful is True
    assert result.qualified is True
