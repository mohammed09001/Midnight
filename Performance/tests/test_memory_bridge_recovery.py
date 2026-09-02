"""Task 21 (Midnight Memory Execution 07): replay/restart/backup/recovery
qualification for the Performance<->Memory bridge boundary specifically.

Memory's own Task 45 recovery qualification (`Memory/src/engine/recovery.ts`,
`qualify recovery` CLI) is thorough but entirely in-process — it instantiates
`MemoryEngine` directly against scratch stores and never goes through the CLI
subprocess boundary this bridge actually uses. This file is the missing
bridge-boundary coverage: proposal delivery interrupted by a torn store,
Performance retrying after an unclear outcome, a backup restored mid-
integration, and evidence-reference expiry visibility — reusing Memory's
existing recovery/backup CLI machinery (`doctor`, `backup create|restore`,
`projections check`) rather than inventing distributed transactions.

Fault injection mirrors `recovery.ts`'s own technique exactly: overwrite the
store file with opaque, non-SQLite bytes via plain file I/O (never SQL,
never Memory's schema). This is deterministic and OS-independent — no POSIX
process-kill semantics anywhere, so it runs the same on Windows as on Linux.
"""
import json
import unittest
from pathlib import Path
from tempfile import mkdtemp

from midnight_performance.memory_bridge import (
    MEMORY_CONTRACT_VERSION,
    MemoryContractError,
    build_propose_envelope,
    call_memory_cli,
    citation_from_memory_record,
    lesson_from_sealed_envelope,
    propose_lesson_or_degrade,
    read_performance_context,
)

from tests.test_memory_bridge import (
    _MEMORY_REPO_PATH,
    _NODE_AVAILABLE,
    _sealed_test_envelope,
    subprocess_run_record_add,
    subprocess_run_scope_create,
)


def _corrupt_store_file(store_path: str) -> None:
    """Mirror `recovery.ts`'s own fault-injection technique (`writeFileSync`
    of a non-SQLite string over the store path): opaque, schema-agnostic,
    write-only. Never SQL, never a query into Memory's store.

    A store that was previously opened in WAL mode leaves `-wal`/`-shm`
    sidecar files behind; SQLite transparently recovers from those on next
    open, which would silently mask corruption of the (tiny) main file
    alone. Removing the sidecars first makes the injected fault genuine
    regardless of whether the store was ever opened before.
    """
    path = Path(store_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    path.write_text("this is not a sqlite database file", encoding="utf-8")


def _run_cli(*args: str, store_path: str):
    import subprocess

    cli_path = str(_MEMORY_REPO_PATH / "src" / "cli" / "cli.ts")
    return subprocess.run(
        ["node", "--experimental-strip-types", cli_path, *args, "--store", store_path],
        capture_output=True, text=True, timeout=30,
    )


@unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
class MemoryBridgeRecoveryTests(unittest.TestCase):
    def test_torn_store_file_is_a_typed_failure_through_the_cli_boundary(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.aa000000-6666-4666-8666-aa0000000000"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)
        lesson = lesson_from_sealed_envelope(_sealed_test_envelope(), subject="Pre-corruption lesson", content="c")

        _corrupt_store_file(store_path)

        doctor = _run_cli("doctor", store_path=store_path)
        self.assertNotEqual(doctor.returncode, 0)
        doctor_payload = json.loads(doctor.stdout)
        self.assertEqual(doctor_payload["error"]["code"], "MEMORY_STORE_UNAVAILABLE")

        with self.assertRaises(MemoryContractError) as ctx:
            call_memory_cli(
                build_propose_envelope(project_key, [lesson]),
                memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
            )
        self.assertEqual(ctx.exception.code, "MEMORY_STORE_UNAVAILABLE")

        result = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertFalse(result.available)
        self.assertEqual(result.error_code, "MEMORY_STORE_UNAVAILABLE")

    def test_retry_after_unclear_delivery_outcome_converges_to_one_candidate(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.bb000000-6666-4666-8666-bb0000000000"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        sealed = _sealed_test_envelope()
        lesson = lesson_from_sealed_envelope(sealed, subject="Retry-safe recovery lesson", content="c")
        envelope = build_propose_envelope(project_key, [lesson])

        # Simulates "Performance retries because the first attempt's
        # response was lost/unclear (e.g. Memory restarted mid-response)" —
        # a blind retry carrying the lesson's own default idempotencyKey.
        first = propose_lesson_or_degrade(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        second = propose_lesson_or_degrade(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(first.delivered and second.delivered)
        self.assertEqual(first.candidate_id, second.candidate_id)

        listed = call_memory_cli(
            {"contractVersion": MEMORY_CONTRACT_VERSION, "operation": "memory.candidates",
             "request": {"scope": project_key, "status": "open"}},
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        matching = [c for c in listed["result"]["candidates"] if c["subject"] == "Retry-safe recovery lesson"]
        self.assertEqual(len(matching), 1, "a retry after an unclear outcome must not create a duplicate candidate")
        self.assertEqual(matching[0]["evidenceRefs"][0]["ref"], sealed.observation.identity.canonical)

    def test_backup_restore_mid_integration_preserves_exactly_one_candidate_and_no_loss(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.cc000000-6666-4666-8666-cc0000000000"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        added_a = subprocess_run_record_add(
            project_key, store_path=store_path, subject="Record A pre-snapshot", content="content A",
        )
        self.assertEqual(added_a.returncode, 0, added_a.stderr)
        record_a_id = json.loads(added_a.stdout)["recordId"]

        backup_dir = mkdtemp()
        snapshot_path = str(Path(backup_dir) / "snapshot.json")
        created_backup = _run_cli("backup", "create", "--path", snapshot_path, store_path=store_path)
        self.assertEqual(created_backup.returncode, 0, created_backup.stderr)

        added_b = subprocess_run_record_add(
            project_key, store_path=store_path, subject="Record B post-snapshot", content="content B",
        )
        self.assertEqual(added_b.returncode, 0, added_b.stderr)

        # Memory "crashes"/is corrupted mid-integration, after B was written
        # but with no snapshot covering it.
        _corrupt_store_file(store_path)

        restored_path = str(Path(mkdtemp()) / "restored.db")
        restored = _run_cli("backup", "restore", "--path", snapshot_path, store_path=restored_path)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        restore_result = json.loads(restored.stdout)
        self.assertEqual(restore_result["records"], 1, "only the pre-snapshot record should be restored")

        result = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=restored_path)
        self.assertTrue(result.available)
        record_ids = [r["record"]["recordId"] for r in result.records]
        self.assertEqual(
            record_ids, [record_a_id],
            "record A survives intact; record B is honestly absent (never backed up) — not fabricated, not duplicated",
        )
        record_a = next(r for r in result.records if r["record"]["recordId"] == record_a_id)
        citation = citation_from_memory_record(record_a)
        self.assertEqual(citation.value, f"{record_a_id}#rev1", "restore must not rewrite historical evidence")

        projections = _run_cli("projections", "check", "--scope", project_key, store_path=restored_path)
        self.assertEqual(projections.returncode, 0, projections.stderr)
        projections_report = json.loads(projections.stdout)
        corrupted = [p for p in projections_report["projections"] if p["status"] == "corrupted"]
        self.assertEqual(corrupted, [], "derived projections must be healthy immediately after restore")

    def test_expired_evidence_reference_is_visible_via_evidence_gaps_after_the_fact(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.dd000000-6666-4666-8666-dd0000000000"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        added = _run_cli(
            "record", "add", "--scope", project_key, "--subject", "Expiring evidence",
            "--content", "content", "--evidence", "external:expired-ref-1",
            "--evidence-expires-at", "2020-01-01T00:00:00.000Z", "--source-kind", "user_note",
            store_path=store_path,
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        # Evidence expiry is purely a Memory-internal, observational fact —
        # nothing on the Performance side ever triggers a sweep; it is only
        # ever discovered by reading it back.
        result = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(result.available)
        self.assertEqual(len(result.records), 1)
        gaps = result.records[0]["evidenceGaps"]
        self.assertTrue(
            any("external:expired-ref-1" in gap and "expired" in gap for gap in gaps),
            f"expected an expiry gap naming the expired ref, got {gaps}",
        )


if __name__ == "__main__":
    unittest.main()
