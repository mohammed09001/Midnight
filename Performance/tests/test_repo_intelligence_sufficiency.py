"""Repo Intelligent 02/Execution 02: per-question sufficiency qualification."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.memory_bridge import MemoryReadResult
from midnight_performance.repo_intelligence.contracts import InternalAnswerStatus
from midnight_performance.repo_intelligence.sufficiency import evaluate_sufficiency
from tests.test_repo_intelligence_question_compiler import PROJECT, make_signal

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides):
    base = {
        "record": {"recordId": "r1", "revision": 1, "observedAt": NOW.isoformat()},
        "confidence": 0.9,
        "authority": {"tier": "verified_source"},
        "contradiction": {"status": "resolved", "groupId": None, "groupSize": None},
        "evidenceGaps": [],
        "evidenceCount": 2,
    }
    base.update(overrides)
    return base


class FakeMemory:
    def __init__(self, *, available=True, records=(), error_code=None):
        self._available = available
        self._records = records
        self._error_code = error_code
        self.queries = []

    def read_context(self, project_key, *, size=20, query=None):
        self.queries.append(query)
        return MemoryReadResult(available=self._available, records=tuple(self._records), error_code=self._error_code)

    def propose_lesson(self, envelope):
        raise NotImplementedError


class SufficiencyTests(unittest.TestCase):
    def test_no_memory_bridge_is_absent_unavailable(self):
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=None, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.ABSENT)
        self.assertIn("UNAVAILABLE", decision.diagnostic)

    def test_memory_unavailable_result_is_absent_unavailable(self):
        memory = FakeMemory(available=False, error_code="MEMORY_UNREACHABLE")
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.ABSENT)
        self.assertIn("UNAVAILABLE", decision.diagnostic)

    def test_no_matching_records_is_absent(self):
        memory = FakeMemory(records=())
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.ABSENT)
        self.assertEqual(memory.queries, ["token refresh"])

    def test_full_evidence_reaches_sufficient(self):
        memory = FakeMemory(records=(_record(),))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.SUFFICIENT)
        self.assertFalse(decision.expected_information_value)
        self.assertTrue(all(d.passed for d in decision.dimensions))

    def test_missing_evidence_coverage_is_partial(self):
        memory = FakeMemory(records=(_record(evidenceGaps=["missing root cause"]),))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.PARTIAL)
        self.assertTrue(decision.expected_information_value)
        coverage = next(d for d in decision.dimensions if d.name == "coverage")
        self.assertFalse(coverage.passed)

    def test_record_older_than_freshness_window_is_stale(self):
        old_record = _record()
        old_record["record"]["observedAt"] = (NOW - timedelta(days=200)).isoformat()
        memory = FakeMemory(records=(old_record,))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.STALE)
        self.assertTrue(decision.expected_information_value)

    def test_open_contradiction_is_contradicted_never_sufficient(self):
        contradicted = _record(contradiction={"status": "open", "groupId": "g1", "groupSize": 2})
        memory = FakeMemory(records=(contradicted,))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.CONTRADICTED)
        self.assertTrue(decision.expected_information_value)

    def test_resolved_contradiction_does_not_block_sufficiency(self):
        memory = FakeMemory(records=(_record(contradiction={"status": "resolved"}),))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.SUFFICIENT)

    def test_unattributed_authority_fails_provenance_and_downgrades_to_partial(self):
        memory = FakeMemory(records=(_record(authority={"tier": "unattributed"}),))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.PARTIAL)

    def test_verification_signal_with_unresolved_gaps_stays_partial(self):
        signal = make_signal(signal_kind="verification_failure")
        from dataclasses import replace as dc_replace
        gapped_signal = dc_replace(signal, signal=dc_replace(signal.signal, gaps=("still flaky",)))
        memory = FakeMemory(records=(_record(),))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=gapped_signal, memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.PARTIAL)
        verification = next(d for d in decision.dimensions if d.name == "verification_support")
        self.assertFalse(verification.passed)

    def test_non_verification_signal_kind_has_no_verification_dimension(self):
        memory = FakeMemory(records=(_record(),))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="coupling",
            scored=make_signal(signal_kind="coupling"), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertFalse(any(d.name == "verification_support" for d in decision.dimensions))
        self.assertIs(decision.status, InternalAnswerStatus.SUFFICIENT)

    def test_unparseable_freshness_with_otherwise_passing_dimensions_is_unknown(self):
        memory = FakeMemory(records=(_record(record={"recordId": "r1", "revision": 1}),))
        decision = evaluate_sufficiency(
            concept="token refresh", template_kind="verification_failure",
            scored=make_signal(), memory=memory, project_key="alpha", now=NOW,
        )
        self.assertIs(decision.status, InternalAnswerStatus.UNKNOWN)
        self.assertTrue(decision.expected_information_value)


if __name__ == "__main__":
    unittest.main()
