"""Execution 04, Section F: a real multi-process race qualification for
`EvidenceLedger.append`. Spawns actual `subprocess.Popen` writers (not
threads — threads share one interpreter's GIL and in-process lock and would
never exercise the cross-process race this is meant to prove safe against),
matching the confirmed real-world scenario: Claude Code runs multiple hook
processes for the same event in parallel.
"""

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from midnight_performance import EntityKind, EvidenceLedger, deterministic_identity

PROJECT_KEY = "concurrency-project"

_WRITER_SCRIPT = """
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, {performance_dir!r})
from midnight_performance.prompt_capture import record_prompt_run

appended, canonical = record_prompt_run(
    Path({ledger_path!r}), {project_key!r}, "provider", {event_id!r},
    observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
)
print(f"{{appended}}\\t{{canonical}}")
"""

_PERFORMANCE_DIR = str(Path(__file__).resolve().parent.parent)


def _spawn_writer(ledger_path: Path, event_id: str) -> subprocess.Popen:
    script = _WRITER_SCRIPT.format(
        performance_dir=_PERFORMANCE_DIR, ledger_path=str(ledger_path), project_key=PROJECT_KEY, event_id=event_id,
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


class LedgerConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.ledger_path = Path(self._temporary.name) / "evidence.jsonl"

    def test_same_event_concurrent_writers_produce_exactly_one_surviving_record(self):
        writers = [_spawn_writer(self.ledger_path, "shared-evt") for _ in range(8)]
        results = []
        for proc in writers:
            stdout, stderr = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, stderr)
            appended, canonical = stdout.strip().split("\t")
            results.append((appended == "True", canonical))

        canonical_ids = {canonical for _, canonical in results}
        self.assertEqual(len(canonical_ids), 1, "all writers must agree on the same canonical identity")
        appended_count = sum(1 for appended, _ in results if appended)
        self.assertEqual(appended_count, 1, "exactly one concurrent writer must durably append the shared event")

        ledger = EvidenceLedger(self.ledger_path, deterministic_identity(EntityKind.PROJECT, PROJECT_KEY), _guard())
        records = list(ledger.replay())
        self.assertEqual(len(records), 1, "no silent duplicate canonical identity in the durable ledger")

    def test_distinct_event_concurrent_writers_all_survive(self):
        writer_count = 8
        writers = [_spawn_writer(self.ledger_path, f"distinct-evt-{index}") for index in range(writer_count)]
        canonical_ids = set()
        for proc in writers:
            stdout, stderr = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, stderr)
            appended, canonical = stdout.strip().split("\t")
            self.assertEqual(appended, "True")
            canonical_ids.add(canonical)

        self.assertEqual(len(canonical_ids), writer_count, "every distinct event must get its own identity")

        ledger = EvidenceLedger(self.ledger_path, deterministic_identity(EntityKind.PROJECT, PROJECT_KEY), _guard())
        # A successful, exception-free full replay is itself proof of no
        # interleaved/torn JSON records across the concurrent writers.
        records = list(ledger.replay())
        self.assertEqual(len(records), writer_count)
        self.assertEqual({r.observation.identity.canonical for r in records}, canonical_ids)

    def test_crash_mid_write_never_silently_accepts_a_torn_record(self):
        """A process killed mid-write may leave a torn line. `replay` must
        fail closed (raise) on it rather than silently accepting corrupt
        evidence or silently truncating history — the honestly-provable
        property from Section F, distinct from full crash-atomicity."""
        script = _WRITER_SCRIPT.format(
            performance_dir=_PERFORMANCE_DIR, ledger_path=str(self.ledger_path), project_key=PROJECT_KEY, event_id="crash-evt",
        )
        env = dict(os.environ, MIDNIGHT_TEST_WRITE_DELAY_MS="2000")
        proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        # Poll for the first half to actually land on disk (flushed +
        # fsynced) before killing — a fixed sleep guess is fragile against
        # subprocess/import startup variance (e.g. package import time
        # growing as more modules are added over time); polling for the
        # real, observable effect is robust regardless.
        import time as _time
        deadline = _time.monotonic() + 1.8  # stay well inside the 2000ms write-delay window
        while _time.monotonic() < deadline:
            if self.ledger_path.exists() and self.ledger_path.stat().st_size > 0:
                break
            _time.sleep(0.02)
        else:
            self.fail("writer never reached the mid-write checkpoint within the poll window")
        proc.kill()
        proc.wait(timeout=10)

        self.assertTrue(self.ledger_path.exists())
        raw = self.ledger_path.read_text(encoding="utf-8")
        self.assertGreater(len(raw), 0, "the killed writer should have left a partial line on disk")

        ledger = EvidenceLedger(self.ledger_path, deterministic_identity(EntityKind.PROJECT, PROJECT_KEY), _guard())
        # The line is deliberately torn (missing its second half / trailing
        # newline+brace); replay must raise rather than silently succeed.
        with self.assertRaisesRegex(ValueError, "invalid evidence at line 1"):
            list(ledger.replay())

    def test_lock_is_released_after_a_killed_holder_so_the_next_writer_is_not_deadlocked(self):
        """The advisory lock must never survive a process crash indefinitely
        — both `msvcrt` and `fcntl` release locks automatically on process
        exit (including a hard kill), so the next writer must proceed. This
        holds the lock WITHOUT ever touching `evidence.jsonl` (unlike the
        crash-mid-write test above), isolating "was the lock released" from
        "did this crash also leave a torn ledger line" — a killed holder
        that never wrote anything must not poison the ledger for anyone."""
        lock_holder_script = (
            f"import sys, time\n"
            f"sys.path.insert(0, {_PERFORMANCE_DIR!r})\n"
            f"from pathlib import Path\n"
            f"from midnight_performance.ledger import _cross_process_lock\n"
            f"lock_path = Path({str(self.ledger_path)!r}).with_name(Path({str(self.ledger_path)!r}).name + '.lock')\n"
            f"with _cross_process_lock(lock_path):\n"
            f"    print('acquired', flush=True)\n"
            f"    time.sleep(30)\n"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", lock_holder_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        acquired_line = holder.stdout.readline()
        self.assertEqual(acquired_line.strip(), "acquired", holder.stderr.read())
        holder.kill()
        holder.wait(timeout=10)

        # A fresh writer must not hang waiting on a lock the dead process
        # never released, and the ledger (never touched by the holder) is
        # untouched and readable.
        follower = _spawn_writer(self.ledger_path, "after-crash-evt")
        stdout, stderr = follower.communicate(timeout=35)
        self.assertEqual(follower.returncode, 0, stderr)
        appended, _canonical = stdout.strip().split("\t")
        self.assertEqual(appended, "True")


def _guard():
    from midnight_performance import PrivacyGuard, PrivacyPolicy

    return PrivacyGuard(PrivacyPolicy())


if __name__ == "__main__":
    unittest.main()
