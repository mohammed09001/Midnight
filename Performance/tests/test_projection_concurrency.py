"""Execution 05, Sections F/G/J: real multi-process concurrency qualification
for the projection updater against concurrent ledger appenders, mirroring
`test_ledger_concurrency.py`'s real-`subprocess.Popen` pattern (not threads
— this must exercise actual separate OS processes, matching how the Desktop
Host, built in Execution 03, spawns `desktop_bridge` as a fresh subprocess
per request).
"""

import os
import subprocess
import sys
import time
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
    projection_path,
)

PROJECT_KEY = "concurrency-projection-project"
_PERFORMANCE_DIR = str(Path(__file__).resolve().parent.parent)

_WRITER_SCRIPT = """
import sys
sys.path.insert(0, {performance_dir!r})
from pathlib import Path
from datetime import datetime, timezone
from midnight_performance.prompt_capture import record_prompt_run
record_prompt_run(Path({ledger_path!r}), {project_key!r}, "provider", {event_id!r}, observed_at=datetime.now(timezone.utc))
print("ok")
"""

_UPDATER_SCRIPT = """
import sys
sys.path.insert(0, {performance_dir!r})
from pathlib import Path
from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.ledger import EvidenceLedger
from midnight_performance.privacy import PrivacyGuard, PrivacyPolicy
from midnight_performance import projection_store as ps
project = deterministic_identity(EntityKind.PROJECT, {project_key!r})
ledger = EvidenceLedger(Path({ledger_path!r}), project, PrivacyGuard(PrivacyPolicy()))
path = ps.projection_path(Path({data_dir!r}))
for _ in range(3):
    ps.update(ledger, path)
    ps.query_activity_page(path, project, entity_kind=EntityKind.PROMPT_RUN, limit=100, after=None)
print("ok")
"""


def _spawn(script_template: str, **kwargs) -> subprocess.Popen:
    env = kwargs.pop("env", None)
    script = script_template.format(performance_dir=_PERFORMANCE_DIR, **kwargs)
    return subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, **env} if env else None,
    )


class ProjectionConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"
        self.project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)

    def _run_concurrent_scenario(self, *, writer_count: int, updater_count: int, journal_mode: str | None) -> float:
        env = {"MIDNIGHT_PROJECTION_JOURNAL_MODE": journal_mode} if journal_mode else None
        writers = [
            _spawn(_WRITER_SCRIPT, ledger_path=str(self.ledger_path), project_key=PROJECT_KEY, event_id=f"conc-evt-{i}")
            for i in range(writer_count)
        ]
        updaters = [
            _spawn(_UPDATER_SCRIPT, ledger_path=str(self.ledger_path), project_key=PROJECT_KEY, data_dir=str(self.data_dir), env=env)
            for _ in range(updater_count)
        ]
        start = time.perf_counter()
        for proc in writers + updaters:
            stdout, stderr = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, f"stdout={stdout!r} stderr={stderr!r}")
            self.assertIn("ok", stdout)
        return time.perf_counter() - start

    def test_concurrent_appenders_and_projection_updaters_do_not_crash_or_corrupt(self):
        elapsed = self._run_concurrent_scenario(writer_count=6, updater_count=6, journal_mode=None)
        self.assertGreater(elapsed, 0)  # sanity: the scenario actually ran

        ledger = EvidenceLedger(self.ledger_path, self.project, PrivacyGuard(PrivacyPolicy()))
        path = projection_path(self.data_dir)
        checkpoint = build_projection(ledger, path)
        true_count = len(list(ledger.replay()))
        self.assertEqual(checkpoint.ledger_record_count, true_count)
        self.assertEqual(true_count, 6)  # 6 distinct writer events, none lost, none duplicated

    def test_wal_vs_default_journal_mode_under_concurrent_load(self):
        """Section G's WAL gate: measure, don't assume. This is the decision
        input, not a correctness assertion — both modes must merely complete
        without error; timing informs `PROJECTION_JOURNAL_MODE`'s default in
        `projection_store.py`, recorded in Performance/README.md."""
        delete_elapsed = self._run_concurrent_scenario(writer_count=4, updater_count=8, journal_mode="DELETE")
        # New scratch dir for a clean comparison (a fresh ledger + projection).
        self.data_dir = Path(self._temporary.name) / "wal-scenario"
        self.data_dir.mkdir()
        self.ledger_path = self.data_dir / "evidence.jsonl"
        wal_elapsed = self._run_concurrent_scenario(writer_count=4, updater_count=8, journal_mode="WAL")

        print(f"\n[projection journal mode benchmark] DELETE={delete_elapsed:.3f}s WAL={wal_elapsed:.3f}s")
        # Both must simply complete cleanly (already asserted inside
        # _run_concurrent_scenario via returncode checks) — no hard
        # assertion on which is faster; this is a measurement, not a gate.


if __name__ == "__main__":
    unittest.main()
