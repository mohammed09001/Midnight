"""Execution 12: the ``repo_intelligence_bridge`` CLI the Desktop Host spawns.

Mirrors ``desktop_bridge.py``'s/``graph_bridge.py``'s own test style: a real
ledger on disk, a real subprocess invocation of ``python -m
midnight_performance.repo_intelligence_bridge``, and schema-shape assertions
on stdout -- the same contract ``desktop/host/operations/getTerminalCard.ts``
and ``recordInsightFeedback.ts`` already depend on.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from midnight_performance.contract_schema import validate_project_insight_feedback_response, validate_project_insight_response
from midnight_performance.contracts import ClaimKind, EntityKind, Observation, deterministic_identity
from midnight_performance.ledger import EvidenceLedger
from midnight_performance.observation_model import ObservationEnvelope, ObservationLayer, ObservationType
from midnight_performance.privacy import ContentCategory, PrivacyGuard, PrivacyPolicy
from midnight_performance.repo_intelligence_bridge import EXIT_INVALID_REQUEST, EXIT_NOT_FOUND, get_terminal_card, record_insight_feedback

PROJECT_KEY = "bravo"
PROJECT = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _change_envelope(i, at, files):
    identity = deterministic_identity(EntityKind.CHANGE_SET, f"{PROJECT_KEY}|change|{i}")
    observation = Observation(
        identity=identity, claim_kind=ClaimKind.OBSERVED,
        subject=deterministic_identity(EntityKind.REPOSITORY_SNAPSHOT, f"{PROJECT_KEY}|snap|{i}"),
        payload={"files": files}, observed_at=at, episode=None, source="test",
    )
    return ObservationEnvelope(
        observation=observation, project=PROJECT, observation_type=ObservationType.REPOSITORY_CHANGE,
        layer=ObservationLayer.RAW, provider="test-observer", provider_event_id=str(i),
    )


def _verification_envelope(i, at, files, passed):
    observation = Observation(
        identity=deterministic_identity(EntityKind.VERIFICATION_RUN, f"{PROJECT_KEY}|verify|{i}"),
        claim_kind=ClaimKind.OBSERVED,
        subject=deterministic_identity(EntityKind.CHANGE_SET, f"{PROJECT_KEY}|verify-subject|{i}"),
        payload={"files": files, "passed": passed}, observed_at=at, episode=None, source="test",
    )
    return ObservationEnvelope(
        observation=observation, project=PROJECT, observation_type=ObservationType.VERIFICATION,
        layer=ObservationLayer.NORMALIZED, provider="test-runner", provider_event_id=str(i),
    )


def _build_fixture_ledger(data_dir: Path, *, reference_now: datetime = NOW) -> None:
    write_policy = PrivacyPolicy(allowed_categories=frozenset({ContentCategory.METADATA, ContentCategory.REPOSITORY_METADATA}))
    write_guard = PrivacyGuard(
        write_policy, field_categories={"files": ContentCategory.REPOSITORY_METADATA, "passed": ContentCategory.METADATA}
    )
    ledger = EvidenceLedger(data_dir / "evidence.jsonl", PROJECT, write_guard)
    for i in range(3):
        ledger.append(_change_envelope(i, reference_now - timedelta(days=5, hours=-i), ["src/foo.py"]))
        ledger.append(_verification_envelope(i, reference_now - timedelta(days=4, hours=-i), ["src/foo.py"], False))


class BridgeInProcessTests(unittest.TestCase):
    """Exercises the bridge's Python functions directly (fast, in-process)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.data_dir.mkdir()
        self.repo_root = Path(self._tmp.name) / "repo"
        (self.repo_root / "src").mkdir(parents=True)
        (self.repo_root / "src" / "foo.py").write_text("print('hi')\n")
        _build_fixture_ledger(self.data_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_terminal_card_returns_schema_valid_single_candidate_document(self):
        document = get_terminal_card(self.data_dir, PROJECT_KEY, self.repo_root, user_pull=True, now=NOW)
        validate_project_insight_response(document)
        self.assertEqual(document["version"], 1)
        self.assertIsNotNone(document["insight"])
        self.assertEqual(document["insight"]["outcome"], "offered")

    def test_record_feedback_round_trip_updates_outcome(self):
        document = get_terminal_card(self.data_dir, PROJECT_KEY, self.repo_root, user_pull=True, now=NOW)
        exposure_id = document["insight"]["exposureId"]
        feedback_document = record_insight_feedback(self.data_dir, PROJECT_KEY, exposure_id, "saved", now=NOW)
        validate_project_insight_feedback_response(feedback_document)
        self.assertEqual(feedback_document["recorded"], True)
        self.assertEqual(feedback_document["outcome"], "saved")

        refreshed = get_terminal_card(self.data_dir, PROJECT_KEY, self.repo_root, user_pull=True, now=NOW)
        if refreshed["insight"] is not None and refreshed["insight"]["exposureId"] == exposure_id:
            self.assertEqual(refreshed["insight"]["outcome"], "saved")

    def test_record_feedback_rejects_unknown_exposure(self):
        with self.assertRaises(KeyError):
            record_insight_feedback(self.data_dir, PROJECT_KEY, "ri:v1:exposure:00000000-0000-0000-0000-000000000000", "saved", now=NOW)

    def test_record_feedback_rejects_invalid_outcome(self):
        document = get_terminal_card(self.data_dir, PROJECT_KEY, self.repo_root, user_pull=True, now=NOW)
        exposure_id = document["insight"]["exposureId"]
        with self.assertRaises(ValueError):
            record_insight_feedback(self.data_dir, PROJECT_KEY, exposure_id, "not-a-real-outcome", now=NOW)


class BridgeSubprocessTests(unittest.TestCase):
    """Exercises the exact CLI surface the Desktop Host spawns via execFile."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.data_dir.mkdir()
        self.repo_root = Path(self._tmp.name) / "repo"
        (self.repo_root / "src").mkdir(parents=True)
        (self.repo_root / "src" / "foo.py").write_text("print('hi')\n")
        # The CLI has no --now override, so fixture timestamps must be relative
        # to real wall-clock time to land inside the pipeline's scan window.
        _build_fixture_ledger(self.data_dir, reference_now=datetime.now(timezone.utc))

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra_args):
        args = [
            sys.executable, "-m", "midnight_performance.repo_intelligence_bridge",
            "--data-dir", str(self.data_dir), "--project", PROJECT_KEY, "--repo-root", str(self.repo_root),
            *extra_args,
        ]
        return subprocess.run(args, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))

    def test_get_terminal_card_via_subprocess_matches_schema(self):
        proc = self._run("--user-pull")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        document = json.loads(proc.stdout)
        validate_project_insight_response(document)

    def test_record_feedback_via_subprocess_exits_zero_on_success(self):
        proc = self._run("--user-pull")
        document = json.loads(proc.stdout)
        exposure_id = document["insight"]["exposureId"]
        feedback_proc = self._run("--record-feedback", "--exposure-id", exposure_id, "--outcome", "dismissed")
        self.assertEqual(feedback_proc.returncode, 0, feedback_proc.stderr)
        feedback_document = json.loads(feedback_proc.stdout)
        validate_project_insight_feedback_response(feedback_document)

    def test_record_feedback_via_subprocess_exits_not_found_for_unknown_exposure(self):
        # An unknown exposure id is a "resource doesn't exist" outcome, not a
        # malformed-request one -- distinct from EXIT_INVALID_REQUEST, which is
        # reserved for a structurally invalid outcome value.
        feedback_proc = self._run("--record-feedback", "--exposure-id", "bogus", "--outcome", "saved")
        self.assertEqual(feedback_proc.returncode, EXIT_NOT_FOUND)
        error = json.loads(feedback_proc.stderr.strip().splitlines()[-1])
        self.assertEqual(error["error"], "not_found")

    def test_record_feedback_via_subprocess_exits_invalid_request_for_malformed_outcome(self):
        proc = self._run("--user-pull")
        document = json.loads(proc.stdout)
        exposure_id = document["insight"]["exposureId"]
        feedback_proc = self._run("--record-feedback", "--exposure-id", exposure_id, "--outcome", "not-a-real-outcome")
        self.assertEqual(feedback_proc.returncode, EXIT_INVALID_REQUEST)
        error = json.loads(feedback_proc.stderr.strip().splitlines()[-1])
        self.assertEqual(error["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
