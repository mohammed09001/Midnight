"""Tests for midnight_performance.memory_temporal_lineage (Execution 09:
Memory Temporal Lineage Overlay). Split into pure-logic unit tests here
(`pinned_state`/`refresh_state` against fake `read_performance_context`
results, no subprocess) and real end-to-end tests against a live Memory CLI
in `test_memory_lineage_bridge.py`.
"""
import unittest
from unittest import mock

from midnight_performance import ExternalReference, MalformedMemoryRecordError
from midnight_performance.memory_bridge import MemoryReadResult
from midnight_performance.memory_temporal_lineage import MemoryCitationState, pinned_state, refresh_state


def _citation(record_id: str = "rec-1", revision: int = 1) -> ExternalReference:
    return ExternalReference(provider="memory", kind="record", value=f"{record_id}#rev{revision}")


class PinnedStateTests(unittest.TestCase):
    """`pinned_state` is pure parsing — no Memory contact, ever."""

    def test_parses_record_id_and_revision(self):
        state = pinned_state(_citation("rec-42", 3))
        self.assertEqual(state.record_id, "rec-42")
        self.assertEqual(state.pinned_revision, 3)
        self.assertEqual(state.provider, "memory")

    def test_current_status_unknown_until_refreshed(self):
        state = pinned_state(_citation())
        self.assertFalse(state.current_status_known)
        self.assertIsNone(state.current_revision)
        self.assertIsNone(state.superseded)
        self.assertIsNone(state.contradiction_group_id)
        self.assertIsNone(state.newer_revision_available)
        self.assertIsNone(state.refreshed_at)
        self.assertEqual(state.gaps, ())

    def test_rejects_non_memory_provider(self):
        with self.assertRaises(MalformedMemoryRecordError):
            pinned_state(ExternalReference(provider="other", kind="record", value="rec-1#rev1"))

    def test_rejects_non_record_kind(self):
        with self.assertRaises(MalformedMemoryRecordError):
            pinned_state(ExternalReference(provider="memory", kind="candidate", value="rec-1#rev1"))

    def test_rejects_malformed_value(self):
        with self.assertRaises(MalformedMemoryRecordError):
            pinned_state(ExternalReference(provider="memory", kind="record", value="not-pinned"))

    def test_to_record_is_json_shaped(self):
        record = pinned_state(_citation("rec-1", 2)).to_record()
        self.assertEqual(record["recordId"], "rec-1")
        self.assertEqual(record["pinnedRevision"], 2)
        self.assertFalse(record["currentStatusKnown"])
        self.assertEqual(record["gaps"], [])


def _context_record(record: dict, contradiction: dict | None = None) -> dict:
    return {"record": record, "contradiction": contradiction or {"groupId": None, "status": None, "groupSize": None}}


class RefreshStateTests(unittest.TestCase):
    """`refresh_state` never mutates its input and never raises — every
    branch returns a brand-new, typed `MemoryCitationState`."""

    def setUp(self):
        self.pinned = pinned_state(_citation("rec-1", 1))

    def test_never_mutates_the_pinned_state_object(self):
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=False, error_code="MEMORY_UNAVAILABLE", error_message="down"),
        ):
            refresh_state(self.pinned, "proj.key")
        self.assertFalse(self.pinned.current_status_known)
        self.assertEqual(self.pinned.gaps, ())

    def test_memory_unavailable_is_a_truthful_gap_not_an_exception(self):
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=False, error_code="MEMORY_UNAVAILABLE", error_message="no node"),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertFalse(result.current_status_known)
        self.assertIsNotNone(result.refreshed_at)
        self.assertTrue(any("memory_unreachable" in gap for gap in result.gaps))

    def test_record_missing_from_bounded_window_is_a_gap_not_a_negative_claim(self):
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=True, records=(_context_record({"recordId": "other-rec", "revision": 1, "status": "active"}),)),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertFalse(result.current_status_known)
        self.assertIn("unavailable:current_read:record_not_in_window", result.gaps)
        # Never fabricates supersession/newer-revision from an absent read.
        self.assertIsNone(result.superseded)
        self.assertIsNone(result.newer_revision_available)

    def test_pinned_revision_is_current_when_nothing_changed(self):
        record = {"recordId": "rec-1", "revision": 1, "status": "active", "contradictionGroupId": None}
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=True, records=(_context_record(record),)),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertTrue(result.current_status_known)
        self.assertEqual(result.current_revision, 1)
        self.assertFalse(result.newer_revision_available)
        self.assertFalse(result.superseded)

    def test_newer_revision_is_evidence_backed_not_time_based(self):
        record = {"recordId": "rec-1", "revision": 3, "status": "active", "contradictionGroupId": None}
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=True, records=(_context_record(record),)),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertTrue(result.newer_revision_available)
        self.assertEqual(result.current_revision, 3)

    def test_superseded_record_is_reported(self):
        record = {
            "recordId": "rec-1", "revision": 1, "status": "superseded",
            "supersededById": "rec-2", "contradictionGroupId": None,
        }
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=True, records=(_context_record(record),)),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertTrue(result.superseded)
        self.assertEqual(result.superseded_by_record_id, "rec-2")
        self.assertEqual(result.current_status, "superseded")

    def test_open_contradiction_is_reported(self):
        record = {"recordId": "rec-1", "revision": 1, "status": "active", "contradictionGroupId": "grp-1"}
        contradiction = {"groupId": "grp-1", "status": "open", "groupSize": 2}
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=True, records=(_context_record(record, contradiction),)),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertEqual(result.contradiction_group_id, "grp-1")
        self.assertEqual(result.contradiction_status, "open")
        self.assertEqual(result.contradiction_group_size, 2)

    def test_resolved_contradiction_is_reported(self):
        record = {"recordId": "rec-1", "revision": 1, "status": "active", "contradictionGroupId": "grp-1"}
        contradiction = {"groupId": "grp-1", "status": "resolved", "groupSize": 2}
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=True, records=(_context_record(record, contradiction),)),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertEqual(result.contradiction_status, "resolved")

    def test_contract_mismatch_is_a_truthful_gap_not_an_exception(self):
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=False, error_code="MEMORY_CONTRACT_MISMATCH", error_message="version drift"),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertFalse(result.current_status_known)
        self.assertTrue(any("MEMORY_CONTRACT_MISMATCH" in gap for gap in result.gaps))

    def test_malformed_memory_response_is_a_truthful_gap_not_an_exception(self):
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=False, error_code="MEMORY_UNAVAILABLE", error_message="non-JSON stdout"),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertFalse(result.current_status_known)
        self.assertTrue(any("MEMORY_UNAVAILABLE" in gap for gap in result.gaps))

    def test_expired_record_is_reported_as_its_own_status_not_superseded(self):
        record = {"recordId": "rec-1", "revision": 1, "status": "expired", "contradictionGroupId": None}
        with mock.patch(
            "midnight_performance.memory_temporal_lineage.read_performance_context",
            return_value=MemoryReadResult(available=True, records=(_context_record(record),)),
        ):
            result = refresh_state(self.pinned, "proj.key")
        self.assertTrue(result.current_status_known)
        self.assertEqual(result.current_status, "expired")
        self.assertFalse(result.superseded)
        self.assertIsNone(result.superseded_by_record_id)

    def test_does_not_call_read_performance_context_from_pinned_state(self):
        # pinned_state must never touch Memory at all -- proven by the
        # absence of any patched call being required to construct it.
        with mock.patch("midnight_performance.memory_temporal_lineage.read_performance_context") as mocked:
            pinned_state(_citation())
            mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
