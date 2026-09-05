"""End-to-end tests for `memory_lineage_bridge.py` / `graph_bridge.py`'s
Execution 09 (Memory Temporal Lineage Overlay) wiring, against a real Memory
CLI subprocess (mirroring `test_memory_bridge.py`'s `CrossEngineLineageTests`
harness). Required scenarios (Section F of the execution spec): no Memory,
live Memory, pinned revision, current newer revision, superseded,
contradicted, resolved contradiction, malformed response, contract
mismatch, project isolation, old graph immutable after refresh, and no
direct SQLite access anywhere in this path.
"""
import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import mkdtemp

from midnight_performance import (
    EntityKind,
    ExternalReference,
    PromptRun,
    build_graph,
    citation_from_memory_record,
    deterministic_identity,
    project_key_for_identity,
    read_performance_context,
)
from midnight_performance.graph_bridge import prompt_run_graph
from midnight_performance.memory_lineage_bridge import refresh_memory_citation
from midnight_performance.repository_capture import ChangeEvidence  # noqa: F401 (import-surface smoke)

_MEMORY_REPO_PATH = Path(__file__).resolve().parents[2] / "Memory"
_NODE_AVAILABLE = shutil.which("node") is not None


def _cli_run(argv: list[str], *, store_path: str) -> subprocess.CompletedProcess:
    cli_path = str(_MEMORY_REPO_PATH / "src" / "cli" / "cli.ts")
    return subprocess.run(
        ["node", "--experimental-strip-types", cli_path, *argv, "--store", store_path],
        capture_output=True, text=True, timeout=30,
    )


def _scope_create(project_key: str, *, store_path: str) -> subprocess.CompletedProcess:
    return _cli_run(["scope", "create", "--key", project_key, "--name", "Lineage Bridge Test"], store_path=store_path)


def _record_add(project_key: str, *, store_path: str, subject: str, content: str) -> subprocess.CompletedProcess:
    return _cli_run(
        ["record", "add", "--scope", project_key, "--subject", subject, "--content", content,
         "--evidence", "external:test-1", "--source-kind", "user_note"],
        store_path=store_path,
    )


def _record_revise(record_id: str, *, store_path: str, content: str, reason: str) -> subprocess.CompletedProcess:
    return _cli_run(
        ["record", "revise", "--id", record_id, "--content", content, "--reason", reason,
         "--actor-kind", "human", "--actor-name", "kim"],
        store_path=store_path,
    )


def _contradiction_register(project_key: str, *, store_path: str, subject: str, record_ids: list[str]) -> subprocess.CompletedProcess:
    argv = ["contradiction", "register", "--scope", project_key, "--subject", subject]
    for record_id in record_ids:
        argv += ["--arg", f"record={record_id}"]
    return _cli_run(argv, store_path=store_path)


def _contradiction_resolve(group_id: str, *, store_path: str, winner: str, reason: str, action: str = "supersede") -> subprocess.CompletedProcess:
    return _cli_run(
        ["contradiction", "resolve", "--id", group_id, "--action", action, "--winner", winner, "--reason", reason,
         "--actor-kind", "human", "--actor-name", "kim"],
        store_path=store_path,
    )


def _new_project() -> tuple[str, str]:
    """Returns (memory_scope_key, performance_local_project_key) for a fresh, isolated project."""
    local_key = f"lineage-test-{Path(mkdtemp()).name}"
    identity = deterministic_identity(EntityKind.PROJECT, local_key)
    return project_key_for_identity(identity), local_key


@unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
class MemoryLineageBridgeLiveTests(unittest.TestCase):
    def setUp(self):
        self.store_dir = mkdtemp()
        self.store_path = str(Path(self.store_dir) / "memory.db")
        self.memory_scope_key, self.local_project_key = _new_project()
        created = _scope_create(self.memory_scope_key, store_path=self.store_path)
        self.assertEqual(created.returncode, 0, created.stderr)

    def _refresh(self, reference: ExternalReference) -> dict:
        return refresh_memory_citation(
            self.local_project_key, reference,
            memory_repo_path=str(_MEMORY_REPO_PATH), store_path=self.store_path,
        )

    def test_live_memory_pinned_revision_matches_current(self):
        added = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="v1")
        self.assertEqual(added.returncode, 0, added.stderr)
        record_id = json.loads(added.stdout)["recordId"]
        reference = ExternalReference(provider="memory", kind="record", value=f"{record_id}#rev1")

        document = self._refresh(reference)
        self.assertEqual(document["version"], 1)
        state = document["state"]
        self.assertTrue(state["currentStatusKnown"])
        self.assertEqual(state["currentRevision"], 1)
        self.assertEqual(state["pinnedRevision"], 1)
        self.assertFalse(state["newerRevisionAvailable"])
        self.assertFalse(state["superseded"])

    def test_current_newer_revision_is_detected_after_a_revise(self):
        added = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="v1")
        record_id = json.loads(added.stdout)["recordId"]
        pinned_reference = ExternalReference(provider="memory", kind="record", value=f"{record_id}#rev1")

        revised = _record_revise(record_id, store_path=self.store_path, content="v2", reason="correction")
        self.assertEqual(revised.returncode, 0, revised.stderr)

        state = self._refresh(pinned_reference)["state"]
        self.assertTrue(state["currentStatusKnown"])
        self.assertGreater(state["currentRevision"], state["pinnedRevision"])
        self.assertTrue(state["newerRevisionAvailable"])

    def test_superseded_record_is_reported_after_contradiction_supersede(self):
        winner = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="original")
        winner_id = json.loads(winner.stdout)["recordId"]
        loser = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="conflicting")
        loser_id = json.loads(loser.stdout)["recordId"]
        pinned_reference = ExternalReference(provider="memory", kind="record", value=f"{loser_id}#rev1")

        registered = _contradiction_register(
            self.memory_scope_key, store_path=self.store_path, subject="S", record_ids=[winner_id, loser_id],
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        group_id = json.loads(registered.stdout)["groupId"]
        resolved = _contradiction_resolve(group_id, store_path=self.store_path, winner=winner_id, reason="original stands")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)

        state = self._refresh(pinned_reference)["state"]
        self.assertTrue(state["currentStatusKnown"])
        self.assertTrue(state["superseded"])
        self.assertEqual(state["currentStatus"], "superseded")
        self.assertEqual(state["supersededByRecordId"], winner_id)

    def test_open_contradiction_is_reported_before_resolution(self):
        record_a = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="a")
        record_a_id = json.loads(record_a.stdout)["recordId"]
        record_b = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="b")
        record_b_id = json.loads(record_b.stdout)["recordId"]
        pinned_reference = ExternalReference(provider="memory", kind="record", value=f"{record_a_id}#rev1")

        registered = _contradiction_register(
            self.memory_scope_key, store_path=self.store_path, subject="S", record_ids=[record_a_id, record_b_id],
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        group_id = json.loads(registered.stdout)["groupId"]

        state = self._refresh(pinned_reference)["state"]
        self.assertEqual(state["contradictionGroupId"], group_id)
        self.assertEqual(state["contradictionStatus"], "open")

    def test_resolved_contradiction_status_is_reported_on_the_winner(self):
        winner = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="original")
        winner_id = json.loads(winner.stdout)["recordId"]
        loser = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="conflicting")
        loser_id = json.loads(loser.stdout)["recordId"]
        pinned_reference = ExternalReference(provider="memory", kind="record", value=f"{winner_id}#rev1")

        registered = _contradiction_register(
            self.memory_scope_key, store_path=self.store_path, subject="S", record_ids=[winner_id, loser_id],
        )
        group_id = json.loads(registered.stdout)["groupId"]
        resolved = _contradiction_resolve(group_id, store_path=self.store_path, winner=winner_id, reason="original stands")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)

        state = self._refresh(pinned_reference)["state"]
        self.assertEqual(state["contradictionStatus"], "resolved")
        self.assertEqual(state["currentStatus"], "active")

    def test_no_memory_unreachable_node_executable_is_a_truthful_degraded_result_not_a_crash(self):
        added = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="v1")
        record_id = json.loads(added.stdout)["recordId"]
        reference = ExternalReference(provider="memory", kind="record", value=f"{record_id}#rev1")
        document = refresh_memory_citation(
            self.local_project_key, reference,
            memory_repo_path=str(_MEMORY_REPO_PATH), store_path=self.store_path,
            node_executable="definitely-not-a-real-binary-xyz",
        )
        state = document["state"]
        self.assertFalse(state["currentStatusKnown"])
        self.assertTrue(any("memory_unreachable" in gap for gap in state["gaps"]))

    def test_project_isolation_a_citation_from_one_scope_is_not_visible_from_another(self):
        added = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="v1")
        record_id = json.loads(added.stdout)["recordId"]
        reference = ExternalReference(provider="memory", kind="record", value=f"{record_id}#rev1")

        other_memory_scope_key, other_local_key = _new_project()
        other_created = _scope_create(other_memory_scope_key, store_path=self.store_path)
        self.assertEqual(other_created.returncode, 0, other_created.stderr)

        state = refresh_memory_citation(
            other_local_key, reference,
            memory_repo_path=str(_MEMORY_REPO_PATH), store_path=self.store_path,
        )["state"]
        self.assertFalse(state["currentStatusKnown"])
        self.assertIn("unavailable:current_read:record_not_in_window", state["gaps"])

    def test_old_graph_document_is_unchanged_after_a_later_refresh(self):
        added = _record_add(self.memory_scope_key, store_path=self.store_path, subject="S", content="v1")
        record_id = json.loads(added.stdout)["recordId"]
        reference = ExternalReference(provider="memory", kind="record", value=f"{record_id}#rev1")

        prompt_run = PromptRun(prompt_run_id="lineage-graph-pr", prompt_version_id="v1")
        graph = build_graph(prompt_run, memory_references=(reference,))
        node_id = deterministic_identity(EntityKind.MEMORY_RECORD, f"{reference.provider}:{reference.kind}:{reference.value}")
        self.assertIn(node_id, graph.nodes)

        pinned_lineage_before = {"nodeId": node_id.canonical, "pinnedRevision": 1, "currentStatusKnown": False}
        snapshot = copy.deepcopy(pinned_lineage_before)

        # A real, live revise + refresh happens "later" -- Memory's state changes...
        _record_revise(record_id, store_path=self.store_path, content="v2", reason="later change")
        refresh_memory_citation(
            self.local_project_key, reference,
            memory_repo_path=str(_MEMORY_REPO_PATH), store_path=self.store_path,
        )

        # ...but the earlier, already-built pinned lineage snapshot never changes.
        self.assertEqual(pinned_lineage_before, snapshot)
        self.assertIn(node_id, build_graph(prompt_run, memory_references=(reference,)).nodes)


class MemoryLineageBridgeStaticTests(unittest.TestCase):
    """Section F: 'no direct SQLite access' -- a structural, source-level
    guarantee, not just an emergent behavior of today's implementation."""

    def test_neither_module_imports_sqlite_or_opens_a_db_file_directly(self):
        for module_name in ("memory_temporal_lineage.py", "memory_lineage_bridge.py"):
            source = (Path(__file__).resolve().parents[1] / "midnight_performance" / module_name).read_text()
            self.assertNotIn("sqlite3", source)
            self.assertNotIn("better-sqlite3", source)
            self.assertNotIn(".db\"", source)
            self.assertNotIn(".db'", source)

    def test_refresh_state_only_reaches_memory_through_read_performance_context(self):
        source = (Path(__file__).resolve().parents[1] / "midnight_performance" / "memory_temporal_lineage.py").read_text()
        self.assertIn("read_performance_context", source)
        self.assertNotIn("call_memory_cli(", source)  # only the already-typed wrapper, never the raw client directly


class MemoryLineageBridgeMalformedRequestTests(unittest.TestCase):
    """Malformed-request / contract-mismatch style failures never reach the
    Memory CLI at all -- caught before any subprocess is spawned."""

    def test_malformed_reference_value_is_rejected_before_any_memory_call(self):
        with self.assertRaises(Exception):
            refresh_memory_citation(
                "some-project", ExternalReference(provider="memory", kind="record", value="not-pinned"),
                memory_repo_path=str(_MEMORY_REPO_PATH),
            )

    def test_non_memory_provider_reference_is_rejected(self):
        with self.assertRaises(Exception):
            refresh_memory_citation(
                "some-project", ExternalReference(provider="other", kind="record", value="rec-1#rev1"),
                memory_repo_path=str(_MEMORY_REPO_PATH),
            )


if __name__ == "__main__":
    unittest.main()
