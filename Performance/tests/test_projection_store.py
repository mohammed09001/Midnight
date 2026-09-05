import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from midnight_performance import (
    EntityKind,
    EvidenceLedger,
    PrivacyGuard,
    PrivacyPolicy,
    build_projection,
    deterministic_identity,
    discard_projection,
    projection_path,
    query_activity_page,
    rebuild_projection,
    record_prompt_run,
    update_projection,
    verify_projection,
)

PROJECT_KEY = "projection-project"
OTHER_PROJECT_KEY = "other-projection-project"


class ProjectionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"
        self.path = projection_path(self.data_dir)
        self.project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
        self.ledger = EvidenceLedger(self.ledger_path, self.project, PrivacyGuard(PrivacyPolicy()))

    def seed(self, count: int, *, start=datetime(2026, 1, 1, tzinfo=timezone.utc)) -> None:
        for i in range(count):
            record_prompt_run(self.ledger_path, PROJECT_KEY, "provider", f"evt-{i:04d}", observed_at=start + timedelta(minutes=i))

    def query_all(self):
        rows, total, complete = query_activity_page(self.path, self.project, entity_kind=EntityKind.PROMPT_RUN, limit=100, after=None)
        return rows, total, complete

    def test_clean_rebuild_matches_true_ledger_count(self):
        self.seed(12)
        checkpoint = build_projection(self.ledger, self.path)
        self.assertEqual(checkpoint.ledger_record_count, 12)
        true_count = len(list(self.ledger.replay()))
        self.assertEqual(checkpoint.ledger_record_count, true_count)

    def test_incremental_update_catches_up_and_matches_a_fresh_rebuild(self):
        self.seed(5)
        build_projection(self.ledger, self.path)
        self.seed(5, start=datetime(2026, 2, 1, tzinfo=timezone.utc))
        incremental_checkpoint = update_projection(self.ledger, self.path)
        incremental_rows, incremental_total, _ = self.query_all()

        discard_projection(self.path)
        fresh_checkpoint = build_projection(self.ledger, self.path)
        fresh_rows, fresh_total, _ = self.query_all()

        self.assertEqual(incremental_checkpoint.ledger_record_count, fresh_checkpoint.ledger_record_count)
        self.assertEqual(incremental_total, fresh_total)
        self.assertEqual([r.canonical_identity for r in incremental_rows], [r.canonical_identity for r in fresh_rows])

    def test_restart_reuses_a_fresh_connection_against_the_same_file(self):
        self.seed(3)
        build_projection(self.ledger, self.path)
        # A brand-new EvidenceLedger/connection, simulating a process restart.
        restarted_ledger = EvidenceLedger(self.ledger_path, self.project, PrivacyGuard(PrivacyPolicy()))
        checkpoint = update_projection(restarted_ledger, self.path)
        self.assertEqual(checkpoint.ledger_record_count, 3)

    def test_duplicate_provider_event_is_a_single_row(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "provider", "dup-evt", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        record_prompt_run(self.ledger_path, PROJECT_KEY, "provider", "dup-evt", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        build_projection(self.ledger, self.path)
        rows, total, _ = self.query_all()
        self.assertEqual(total, 1)
        self.assertEqual(len(rows), 1)

    def test_malformed_tail_falls_back_to_the_authoritative_replay_error(self):
        self.seed(3)
        build_projection(self.ledger, self.path)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write("{not-json\n")
        with self.assertRaisesRegex(ValueError, "invalid evidence at line 4"):
            update_projection(self.ledger, self.path)

    def test_malformed_middle_falls_back_to_the_authoritative_replay_error(self):
        self.seed(3)
        lines = self.ledger_path.read_text(encoding="utf-8").splitlines()
        lines[1] = "{not-json"
        self.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid evidence at line 2"):
            build_projection(self.ledger, self.path)

    def test_checkpoint_mismatch_fails_closed_and_rebuilds(self):
        self.seed(4)
        build_projection(self.ledger, self.path)
        conn = sqlite3.connect(str(self.path))
        conn.execute("UPDATE checkpoint SET last_line_sha256 = 'deadbeef' WHERE id = 1")
        conn.commit()
        conn.close()
        checkpoint = update_projection(self.ledger, self.path)
        self.assertEqual(checkpoint.ledger_record_count, 4)  # rebuilt correctly despite the tampered checkpoint

    def test_project_mismatch_is_rejected(self):
        self.seed(2)
        build_projection(self.ledger, self.path)
        other_project = deterministic_identity(EntityKind.PROJECT, OTHER_PROJECT_KEY)
        other_data_dir = self.data_dir / "other"
        other_ledger_path = other_data_dir / "evidence.jsonl"
        record_prompt_run(other_ledger_path, OTHER_PROJECT_KEY, "provider", "own-evt", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        other_ledger = EvidenceLedger(other_ledger_path, other_project, PrivacyGuard(PrivacyPolicy()))
        # Point the OTHER project's ledger at THIS project's projection file.
        checkpoint = update_projection(other_ledger, self.path)
        self.assertEqual(checkpoint.project_canonical, other_project.canonical)
        rows, total, _ = query_activity_page(self.path, other_project, entity_kind=EntityKind.PROMPT_RUN, limit=100, after=None)
        self.assertEqual(total, 1)  # rebuilt cleanly for the new project; no leaked cross-project rows
        cross_rows, cross_total, _ = self.query_all()
        self.assertEqual(cross_total, 0)  # original project's rows are gone after the rebuild for a different project

    def test_projection_delete_and_rebuild_reproduces_identical_results(self):
        self.seed(15)
        build_projection(self.ledger, self.path)
        before_rows, before_total, _ = self.query_all()
        discard_projection(self.path)
        self.assertFalse(self.path.exists())
        rebuild_projection(self.ledger, self.path)
        after_rows, after_total, _ = self.query_all()
        self.assertEqual(before_total, after_total)
        self.assertEqual([r.canonical_identity for r in before_rows], [r.canonical_identity for r in after_rows])

    def test_more_than_100_prompt_runs_paginate_correctly(self):
        self.seed(205)
        build_projection(self.ledger, self.path)
        collected = []
        after = None
        pages = 0
        while True:
            rows, total, complete = query_activity_page(self.path, self.project, entity_kind=EntityKind.PROMPT_RUN, limit=100, after=after)
            collected.extend(r.canonical_identity for r in rows)
            pages += 1
            self.assertLess(pages, 10)
            if complete:
                break
            last = rows[-1]
            after = (datetime.fromisoformat(last.observed_at_raw), last.canonical_identity)
        self.assertEqual(len(collected), 205)
        self.assertEqual(len(set(collected)), 205)

    def test_full_history_count_equivalence_with_plain_replay(self):
        self.seed(37)
        build_projection(self.ledger, self.path)
        _rows, total, _complete = self.query_all()
        self.assertEqual(total, len(list(self.ledger.replay())))

    def test_verify_reports_healthy_true_after_a_clean_build(self):
        self.seed(6)
        build_projection(self.ledger, self.path)
        status = verify_projection(self.ledger, self.path)
        self.assertTrue(status.healthy)
        self.assertIsNone(status.reason)
        self.assertEqual(status.record_count, 6)

    def test_verify_reports_missing_when_no_projection_exists(self):
        status = verify_projection(self.ledger, self.path)
        self.assertFalse(status.healthy)
        self.assertEqual(status.reason, "missing")

    def test_verify_reports_corrupt_instead_of_raising_when_file_is_not_a_database(self):
        self.seed(3)
        build_projection(self.ledger, self.path)
        with open(self.path, "r+b") as handle:
            handle.seek(0)
            handle.write(b"not a sqlite database" * 4)
        status = verify_projection(self.ledger, self.path)
        self.assertFalse(status.healthy)
        self.assertEqual(status.reason, "corrupt")
        self.assertEqual(status.record_count, 0)

    def test_no_raw_payload_column_exists_in_the_schema(self):
        self.seed(1)
        build_projection(self.ledger, self.path)
        conn = sqlite3.connect(str(self.path))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(observations)").fetchall()}
        conn.close()
        self.assertNotIn("payload", columns)
        self.assertNotIn("payload_json", columns)
        self.assertNotIn("raw_payload", columns)

    def test_attributes_json_never_contains_observation_payload_content(self):
        self.seed(1)
        build_projection(self.ledger, self.path)
        conn = sqlite3.connect(str(self.path))
        row = conn.execute("SELECT attributes_json FROM observations LIMIT 1").fetchone()
        conn.close()
        attributes = json.loads(row[0])
        self.assertEqual(attributes, {"occurrence_only": True})


if __name__ == "__main__":
    unittest.main()
