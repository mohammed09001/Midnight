from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import sys
import unittest

from midnight_performance import (
    ClaimKind,
    EntityKind,
    EvidenceLedger,
    InvalidCursorError,
    Observation,
    ObservationEnvelope,
    ObservationLayer,
    ObservationType,
    PrivacyGuard,
    PrivacyPolicy,
    deterministic_identity,
    is_occurrence_only,
    new_identity,
    prompt_run_activity,
    record_prompt_run,
)

PROJECT_KEY = "bridge-project"
OTHER_PROJECT_KEY = "other-project"


def prompt_run_envelope(project_key: str, event_id: str, observed_at: datetime):
    project = deterministic_identity(EntityKind.PROJECT, project_key)
    stable_key = f"provider:{event_id}"
    return ObservationEnvelope(
        observation=Observation(
            identity=deterministic_identity(EntityKind.PROMPT_RUN, stable_key),
            claim_kind=ClaimKind.OBSERVED,
            subject=deterministic_identity(EntityKind.PROMPT_VERSION, stable_key),
            payload={},
            observed_at=observed_at,
        ),
        project=project,
        observation_type=ObservationType.PROMPT,
        layer=ObservationLayer.NORMALIZED,
        provider="provider",
        provider_event_id=event_id,
    )


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"

    def seed_prompt_run(self, event_id: str, observed_at: datetime) -> str:
        appended, canonical = record_prompt_run(
            self.ledger_path, PROJECT_KEY, "provider", event_id, observed_at=observed_at
        )
        self.assertTrue(appended)
        return canonical

    def test_activity_document_reports_recorded_prompt_runs(self):
        first = self.seed_prompt_run("e-1", datetime(2026, 9, 1, 10, 31, 22, tzinfo=timezone.utc))
        second = self.seed_prompt_run("e-2", datetime(2026, 9, 2, 8, 0, 0, tzinfo=timezone(timedelta(hours=4))))
        document = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["project"], deterministic_identity(EntityKind.PROJECT, PROJECT_KEY).canonical)
        self.assertTrue(document["complete"])
        events = document["events"]
        self.assertEqual([event["promptRunId"] for event in events], [first, second])
        self.assertEqual(events[0]["occurredAt"], "2026-09-01T10:31:22+00:00")
        self.assertEqual(events[1]["occurredAt"], "2026-09-02T08:00:00+04:00")

    def test_identity_is_preserved_exactly(self):
        canonical = self.seed_prompt_run("identity", datetime(2026, 9, 1, tzinfo=timezone.utc))
        document = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        self.assertEqual(document["events"][0]["promptRunId"], canonical)
        self.assertTrue(document["events"][0]["promptRunId"].startswith("mp:v1:prompt_run:"))

    def test_non_prompt_run_evidence_is_not_exposed(self):
        self.seed_prompt_run("run", datetime(2026, 9, 1, tzinfo=timezone.utc))
        ledger = EvidenceLedger(self.ledger_path, deterministic_identity(EntityKind.PROJECT, PROJECT_KEY), PrivacyGuard(PrivacyPolicy()))
        ledger.append(
            ObservationEnvelope(
                observation=Observation(
                    identity=new_identity(EntityKind.CHANGE_SET),
                    claim_kind=ClaimKind.OBSERVED,
                    subject=new_identity(EntityKind.REPOSITORY_SNAPSHOT),
                    payload={},
                ),
                project=deterministic_identity(EntityKind.PROJECT, PROJECT_KEY),
                observation_type=ObservationType.REPOSITORY_CHANGE,
                layer=ObservationLayer.RAW,
                provider="git-observer",
                provider_event_id="event-1",
            )
        )
        document = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        self.assertEqual(document["totalMatching"], 1)
        self.assertEqual(len(document["events"]), 1)

    def test_empty_history_is_truthful_not_an_error(self):
        document = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        self.assertEqual(document["events"], [])
        self.assertEqual(document["totalMatching"], 0)
        self.assertTrue(document["complete"])

    def test_bounded_page_reports_incomplete_coverage(self):
        for index in range(3):
            self.seed_prompt_run(f"e-{index}", datetime(2026, 9, 1, index, tzinfo=timezone.utc))
        document = prompt_run_activity(self.ledger_path, PROJECT_KEY, limit=2)
        self.assertEqual(len(document["events"]), 2)
        self.assertEqual(document["totalMatching"], 3)
        self.assertFalse(document["complete"])
        self.assertEqual(document["limit"], 2)

    def test_cross_project_read_fails_closed(self):
        self.seed_prompt_run("secret-project-run", datetime(2026, 9, 1, tzinfo=timezone.utc))
        # The ledger fails closed: foreign-project evidence aborts replay instead
        # of being filtered away, so no cross-project data can ever be returned.
        with self.assertRaisesRegex(ValueError, "line 1"):
            prompt_run_activity(self.ledger_path, OTHER_PROJECT_KEY)

    def test_malformed_ledger_fails_closed(self):
        self.ledger_path.write_text("{not-json}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "line 1"):
            prompt_run_activity(self.ledger_path, PROJECT_KEY)

    def test_recording_is_idempotent_on_provider_event_id(self):
        moment = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
        first_appended, first_id = record_prompt_run(self.ledger_path, PROJECT_KEY, "opencode", "evt-1", observed_at=moment)
        second_appended, second_id = record_prompt_run(self.ledger_path, PROJECT_KEY, "opencode", "evt-1", observed_at=moment)
        self.assertTrue(first_appended)
        self.assertFalse(second_appended)
        self.assertEqual(first_id, second_id)
        document = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        self.assertEqual(document["totalMatching"], 1)

    def test_recorder_rejects_naive_timestamps(self):
        with self.assertRaises(ValueError):
            record_prompt_run(self.ledger_path, PROJECT_KEY, "opencode", "evt", observed_at=datetime(2026, 9, 2, 12, 0))
        self.assertFalse(self.ledger_path.exists())

    def test_recorder_never_stores_content(self):
        _, canonical = record_prompt_run(self.ledger_path, PROJECT_KEY, "opencode", "evt", observed_at=datetime(2026, 9, 2, tzinfo=timezone.utc))
        line = json.loads(self.ledger_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(line["observation"]["payload"], {})
        self.assertEqual(line["observation"]["identity"], canonical)

    def test_recorded_occurrence_is_marked_occurrence_only_not_full_prompt_evidence(self):
        """Execution 04, Section G: the empty payload plus a machine-checked
        `occurrence_only` marker together prove this is a bare correlation
        anchor, never proof that a full PromptVersion was observed."""
        record_prompt_run(self.ledger_path, PROJECT_KEY, "opencode", "evt", observed_at=datetime(2026, 9, 2, tzinfo=timezone.utc))
        ledger = EvidenceLedger(self.ledger_path, deterministic_identity(EntityKind.PROJECT, PROJECT_KEY), PrivacyGuard(PrivacyPolicy()))
        [envelope] = list(ledger.replay())
        self.assertTrue(is_occurrence_only(envelope))
        self.assertEqual(envelope.observation.subject.kind, EntityKind.PROMPT_VERSION)
        # The PROMPT_VERSION subject is a correlation anchor only — it must
        # never be mistaken for evidence that a PromptVersion was observed.
        self.assertEqual(envelope.observation.payload, {})

    def test_repeated_reads_are_stable_and_do_not_mutate_the_ledger(self):
        self.seed_prompt_run("stable", datetime(2026, 9, 1, tzinfo=timezone.utc))
        before = self.ledger_path.read_text(encoding="utf-8")
        first = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        second = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        self.assertEqual(first, second)
        self.assertEqual(self.ledger_path.read_text(encoding="utf-8"), before)


class DesktopBridgeContinuationTests(unittest.TestCase):
    """Execution 03: keyset cursor pagination over >100 Prompt Runs."""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"

    def seed_prompt_run(self, project_key: str, event_id: str, observed_at: datetime) -> str:
        appended, canonical = record_prompt_run(
            self.ledger_path, project_key, "provider", event_id, observed_at=observed_at
        )
        self.assertTrue(appended)
        return canonical

    def test_cursor_pagination_covers_every_run_without_duplicates_or_gaps(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        total_runs = 205
        for index in range(total_runs):
            self.seed_prompt_run(PROJECT_KEY, f"evt-{index:04d}", base + timedelta(minutes=index))

        collected: list[str] = []
        cursor = None
        pages = 0
        while True:
            document = prompt_run_activity(self.ledger_path, PROJECT_KEY, limit=100, cursor=cursor)
            self.assertEqual(document["totalMatching"], total_runs)
            self.assertLessEqual(len(document["events"]), 100)
            collected.extend(event["promptRunId"] for event in document["events"])
            pages += 1
            if document["complete"]:
                self.assertIsNone(document["nextCursor"])
                break
            self.assertIsNotNone(document["nextCursor"])
            cursor = document["nextCursor"]
            self.assertLess(pages, 10, "pagination did not terminate")

        self.assertEqual(len(collected), total_runs)
        self.assertEqual(len(set(collected)), total_runs, "no duplicate Prompt Runs across pages")
        self.assertEqual(pages, 3)

    def test_ordering_is_deterministic_and_independent_of_append_order(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Seed strictly out of chronological order.
        self.seed_prompt_run(PROJECT_KEY, "later", base + timedelta(hours=2))
        self.seed_prompt_run(PROJECT_KEY, "earliest", base)
        self.seed_prompt_run(PROJECT_KEY, "middle", base + timedelta(hours=1))

        document = prompt_run_activity(self.ledger_path, PROJECT_KEY)
        occurred_at = [event["occurredAt"] for event in document["events"]]
        self.assertEqual(occurred_at, sorted(occurred_at))

    def test_invalid_cursor_is_rejected(self):
        self.seed_prompt_run(PROJECT_KEY, "run", datetime(2026, 9, 1, tzinfo=timezone.utc))
        with self.assertRaises(InvalidCursorError):
            prompt_run_activity(self.ledger_path, PROJECT_KEY, cursor="not-a-real-cursor")

    def test_cursor_minted_for_a_different_project_is_rejected(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(3):
            self.seed_prompt_run(PROJECT_KEY, f"evt-{index}", base + timedelta(minutes=index))
        first_page = prompt_run_activity(self.ledger_path, PROJECT_KEY, limit=1)
        foreign_cursor = first_page["nextCursor"]
        self.assertIsNotNone(foreign_cursor)

        # A ledger file is project-isolated (it fails closed on any foreign
        # line), so the other project needs its own ledger file/directory.
        other_ledger_path = self.data_dir / "other" / "evidence.jsonl"
        appended, _ = record_prompt_run(other_ledger_path, OTHER_PROJECT_KEY, "provider", "own-run", observed_at=base)
        self.assertTrue(appended)

        with self.assertRaises(InvalidCursorError):
            prompt_run_activity(other_ledger_path, OTHER_PROJECT_KEY, cursor=foreign_cursor)


class DesktopBridgeSubprocessTests(unittest.TestCase):
    """The exact transport invocation the Desktop host performs."""

    def test_cli_emits_bounded_json_on_stdout(self):
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            record_prompt_run(data_dir / "evidence.jsonl", PROJECT_KEY, "opencode", "cli-evt", observed_at=datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc))
            completed = subprocess.run(
                [sys.executable, "-m", "midnight_performance.desktop_bridge", "--data-dir", str(data_dir), "--project", PROJECT_KEY],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            document = json.loads(completed.stdout)
            self.assertEqual(document["version"], 1)
            self.assertEqual(document["totalMatching"], 1)
            self.assertEqual(len(document["events"]), 1)
            self.assertTrue(document["events"][0]["occurredAt"].endswith("+00:00"))

    def test_capture_cli_is_idempotent_and_reports_identity(self):
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            arguments = [
                sys.executable, "-m", "midnight_performance.prompt_capture",
                "--data-dir", str(data_dir), "--project", PROJECT_KEY,
                "--provider", "opencode", "--event-id", "hook-9",
                "--observed-at", "2026-09-02T14:05:00+04:00",
            ]
            first = subprocess.run(arguments, capture_output=True, text=True, timeout=60, check=False)
            second = subprocess.run(arguments, capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_document = json.loads(first.stdout)
            second_document = json.loads(second.stdout)
            self.assertTrue(first_document["recorded"])
            self.assertFalse(second_document["recorded"])
            self.assertEqual(first_document["promptRunId"], second_document["promptRunId"])


if __name__ == "__main__":
    unittest.main()
