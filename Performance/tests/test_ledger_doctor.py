import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from midnight_performance import (
    EntityKind,
    EvidenceLedger,
    Observation,
    ObservationEnvelope,
    ObservationLayer,
    ObservationType,
    PrivacyGuard,
    PrivacyPolicy,
    ClaimKind,
    build_projection,
    deterministic_identity,
    projection_path,
    record_prompt_run,
    run_doctor,
)
from midnight_performance.provenance import seal

PROJECT_KEY = "doctor-project"


class LedgerDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"

    def test_healthy_ledger_has_no_findings(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e2", observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        report = run_doctor(self.ledger_path, PROJECT_KEY)
        self.assertTrue(report.healthy)
        self.assertEqual(report.findings, ())
        self.assertEqual(report.valid_records, 2)

    def test_missing_ledger_is_healthy_empty_history(self):
        report = run_doctor(self.ledger_path, PROJECT_KEY)
        self.assertTrue(report.healthy)
        self.assertEqual(report.total_lines, 0)

    def test_invalid_json_line_is_a_finding(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write("{this is not json\n")
        report = run_doctor(self.ledger_path, PROJECT_KEY)
        self.assertFalse(report.healthy)
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].kind, "invalid_json")
        self.assertEqual(report.findings[0].line_number, 2)

    def test_truncated_final_record_is_a_finding(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        raw = self.ledger_path.read_text(encoding="utf-8")
        # Drop the trailing newline to simulate a write that never completed.
        self.ledger_path.write_text(raw.rstrip("\n"), encoding="utf-8")
        report = run_doctor(self.ledger_path, PROJECT_KEY)
        self.assertFalse(report.healthy)
        self.assertEqual(report.findings[0].kind, "truncated_final_record")

    def test_checksum_mismatch_is_a_finding(self):
        project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
        stable_key = "provider:evt-checksum"
        observation = Observation(
            identity=deterministic_identity(EntityKind.PROMPT_RUN, stable_key),
            claim_kind=ClaimKind.OBSERVED,
            subject=deterministic_identity(EntityKind.PROMPT_VERSION, stable_key),
            payload={}, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source="provider",
        )
        envelope = seal(ObservationEnvelope(
            observation=observation, project=project, observation_type=ObservationType.PROMPT,
            layer=ObservationLayer.NORMALIZED, provider="provider", provider_event_id="evt-checksum",
        ))
        ledger = EvidenceLedger(self.ledger_path, project, PrivacyGuard(PrivacyPolicy()))
        ledger.append(envelope)

        # Tamper with the checksum in place (simulating post-hoc corruption).
        raw = json.loads(self.ledger_path.read_text(encoding="utf-8").strip())
        raw["integrity_checksum"] = "0" * 64
        self.ledger_path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")

        report = run_doctor(self.ledger_path, PROJECT_KEY)
        self.assertFalse(report.healthy)
        self.assertEqual(report.findings[0].kind, "checksum_mismatch")

    def test_unexpected_project_is_a_finding(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        report = run_doctor(self.ledger_path, "a-completely-different-project")
        self.assertFalse(report.healthy)
        self.assertEqual(report.findings[0].kind, "unexpected_project")

    def test_duplicate_canonical_identity_is_a_finding(self):
        project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        line = self.ledger_path.read_text(encoding="utf-8")
        # Directly duplicate the line to simulate a torn-lock edge case that
        # let two identical canonical identities land in the file.
        self.ledger_path.write_text(line + line, encoding="utf-8")
        report = run_doctor(self.ledger_path, PROJECT_KEY)
        self.assertFalse(report.healthy)
        self.assertEqual(report.findings[0].kind, "duplicate_identity")

    def test_report_includes_projection_status_when_a_path_is_given(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
        ledger = EvidenceLedger(self.ledger_path, project, PrivacyGuard(PrivacyPolicy()))
        path = projection_path(self.data_dir)
        build_projection(ledger, path)
        report = run_doctor(self.ledger_path, PROJECT_KEY, projection_path=path)
        self.assertIsNotNone(report.projection_status)
        self.assertTrue(report.projection_status.healthy)

    def test_corrupt_projection_file_is_reported_not_raised(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
        ledger = EvidenceLedger(self.ledger_path, project, PrivacyGuard(PrivacyPolicy()))
        path = projection_path(self.data_dir)
        build_projection(ledger, path)
        with open(path, "r+b") as handle:
            handle.seek(0)
            handle.write(b"not a sqlite database" * 4)
        report = run_doctor(self.ledger_path, PROJECT_KEY, projection_path=path)
        self.assertFalse(report.healthy)
        self.assertIsNotNone(report.projection_status)
        self.assertFalse(report.projection_status.healthy)
        self.assertEqual(report.projection_status.reason, "corrupt")

    def test_cli_reports_healthy_ledger_and_exits_zero(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
        ledger = EvidenceLedger(self.ledger_path, project, PrivacyGuard(PrivacyPolicy()))
        build_projection(ledger, projection_path(self.data_dir))  # the CLI also reports projection health
        completed = subprocess.run(
            [sys.executable, "-m", "midnight_performance.ledger_doctor", "--data-dir", str(self.data_dir), "--project", PROJECT_KEY],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        document = json.loads(completed.stdout)
        self.assertTrue(document["healthy"])
        self.assertEqual(document["validRecords"], 1)
        self.assertIn("projection", document)

    def test_cli_exits_nonzero_and_reports_findings_for_a_corrupt_ledger(self):
        record_prompt_run(self.ledger_path, PROJECT_KEY, "p", "e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write("{broken\n")
        completed = subprocess.run(
            [sys.executable, "-m", "midnight_performance.ledger_doctor", "--data-dir", str(self.data_dir), "--project", PROJECT_KEY],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 1)
        document = json.loads(completed.stdout)
        self.assertFalse(document["healthy"])
        self.assertEqual(len(document["findings"]), 1)


if __name__ == "__main__":
    unittest.main()
