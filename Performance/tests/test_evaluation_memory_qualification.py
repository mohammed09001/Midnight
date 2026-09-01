from datetime import datetime, timezone
from midnight_performance import (AIAnalysisAttempt, ClaimKind, EvaluationResult, EvaluatorKind, MemoryDomain, MemoryEvidence, ReviewLabel, qualify_evaluators, qualify_memory)

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)

def test_evaluator_qualification_requires_non_llm_reproducible_evidence():
    deterministic = EvaluationResult("run", "coverage", "1", EvaluatorKind.DETERMINISTIC, .9, (), "ok", 1, ClaimKind.DERIVED)
    judge = EvaluationResult("run", "judge", "1", EvaluatorKind.MODEL_JUDGE, .8, (), "ok", .5, ClaimKind.INFERRED)
    label = ReviewLabel("run", "user", "pass", .8, (), (), NOW)
    result = qualify_evaluators("run", (deterministic, judge), (label,), True, (AIAnalysisAttempt("local", "1", "m", 1, None, True),), reproducible=True)
    assert result.qualified and result.variance is not None
    only_judge = qualify_evaluators("run", (judge,), (), True, (), reproducible=True)
    assert "llm_judge_is_sole_evidence" in only_judge.failures

def test_memory_qualification_blocks_ai_only_noise_and_requires_restore():
    good = (MemoryEvidence("a", MemoryDomain.KNOWLEDGE, ("raw:1",), "tests pass", ClaimKind.OBSERVED), MemoryEvidence("b", MemoryDomain.KNOWLEDGE, ("raw:2",), "tests pass", ClaimKind.DERIVED))
    result = qualify_memory(good, query="tests", allowed_refs=frozenset({"raw:1", "raw:2"}), backup_restored=True, contradictions_resolved=True, supersession_checked=True, historical_valid=True)
    assert result.qualified and result.promoted is not None and result.hits
    noisy = qualify_memory((MemoryEvidence("ai", MemoryDomain.KNOWLEDGE, ("raw:1",), "guess", ClaimKind.INFERRED),), query="guess", allowed_refs=frozenset({"raw:1"}), backup_restored=False, contradictions_resolved=False, supersession_checked=False, historical_valid=False)
    assert "insufficient_grounded_provenance_for_promotion" in noisy.failures
    assert {"contradictions_unresolved", "supersession_unchecked", "historical_validity_unverified"} <= set(noisy.failures)
