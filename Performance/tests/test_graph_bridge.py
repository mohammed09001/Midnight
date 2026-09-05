import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from midnight_performance import (
    ChangeEvidence,
    EntityKind,
    ExternalReference,
    FeedbackReason,
    Identity,
    Judgment,
    OutcomeProvider,
    OutcomeReference,
    PromptRun,
    VerificationSource,
    deterministic_identity,
    prompt_run_graph,
)
from midnight_performance.feedback import FeedbackRecord
from midnight_performance.graph_bridge import InvalidGraphCursorError, PromptRunNotFoundError
from midnight_performance.prompt_capture import record_prompt_run
from midnight_performance.verification import VerificationEvidence

PROJECT_KEY = "graph-bridge-project"
OTHER_PROJECT_KEY = "other-graph-bridge-project"


class GraphBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"

    def seed(self, project_key: str, event_id: str, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)) -> tuple[str, str]:
        """Returns (stable_key, canonical). `known_evidence=PromptRun(...)`
        must be built from the STABLE key (what `build_graph` itself hashes
        internally); every real caller of `prompt_run_graph`/the CLI —
        Desktop included — only ever has the CANONICAL id (`ActivityEvent
        .promptRunId`), so every `prompt_run_graph(...)` call site below
        passes the canonical id, exactly mirroring real usage."""
        appended, canonical = record_prompt_run(self.ledger_path, project_key, "provider", event_id, observed_at=observed_at)
        self.assertTrue(appended)
        return f"provider:{event_id}", canonical

    # --- Section K required cases -----------------------------------

    def test_isolated_prompt_run_with_zero_edges(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "isolated")
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        self.assertEqual(len(doc["nodes"]), 1)
        self.assertEqual(doc["edges"], [])
        self.assertEqual(doc["nodes"][0]["id"], run_canonical)
        self.assertTrue(doc["integrity"]["qualifies"])

    def test_prompt_run_plus_prompt_version(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-version")
        known = PromptRun(run_id, "pv-1")
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known)
        version_node = deterministic_identity(EntityKind.PROMPT_VERSION, "pv-1").canonical
        self.assertIn(version_node, [n["id"] for n in doc["nodes"]])
        edge = next(e for e in doc["edges"] if e["target"] == version_node)
        self.assertEqual(edge["semantic_role"], "prompt_version")

    def test_agent_run(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-agent")
        known = PromptRun(run_id, None, agent_run_ids=("agent-1",), gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, tool_observation_ids={"agent-1": ("tool-1",)})
        agent_node = deterministic_identity(EntityKind.AGENT_RUN, "agent-1").canonical
        self.assertIn(agent_node, [n["id"] for n in doc["nodes"]])
        edge = next(e for e in doc["edges"] if e["target"] == agent_node)
        self.assertEqual(edge["semantic_role"], "executed_by")

    def test_change_set_and_file_change(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-change")
        known = PromptRun(run_id, None, change_set_ids=("cs-1",), gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known)
        change_node = deterministic_identity(EntityKind.CHANGE_SET, "cs-1").canonical
        edge = next(e for e in doc["edges"] if e["target"] == change_node)
        self.assertEqual(edge["semantic_role"], "produced_change")

    def test_change_set_file_change_symbol_hierarchy_not_flattened(self):
        # Execution 08, Section B: Symbol/FileChange must NOT both attach
        # directly to the ChangeSet — real two-level containment.
        from midnight_performance.repository_capture import ChangeEvidence as RealChangeEvidence
        from midnight_performance.repository_entity_resolution import resolve_repository_entities

        run_id, run_canonical = self.seed(PROJECT_KEY, "with-hierarchy")
        known = PromptRun(run_id, None, change_set_ids=("cs-1",), gaps=("unavailable:prompt_version",))
        evidence = RealChangeEvidence(created=("src/greet.py",), modified=(), deleted=())
        source = b"def greet():\n    return 'hi'\n"
        entities, _, _ = resolve_repository_entities(
            repository_key="midnight", change_set_id="cs-1", evidence=evidence,
            content_before={}, content_after={"src/greet.py": source},
        )
        doc = prompt_run_graph(
            self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known,
            resolved_entities={"cs-1": entities},
        )
        change_node = deterministic_identity(EntityKind.CHANGE_SET, "cs-1").canonical
        file_entities = [e for e in entities if e.parent is None]
        self.assertEqual(len(file_entities), 1)
        file_node = file_entities[0].entity.canonical
        symbol_entities = [e for e in entities if e.entity.kind is EntityKind.SYMBOL]
        self.assertGreater(len(symbol_entities), 0)
        symbol_node = symbol_entities[0].entity.canonical

        # ChangeSet -> FileChange edge exists.
        self.assertTrue(any(e["source"] == change_node and e["target"] == file_node for e in doc["edges"]))
        # ChangeSet -> Symbol edge does NOT exist (would be the flattened anti-pattern).
        self.assertFalse(any(e["source"] == change_node and e["target"] == symbol_node for e in doc["edges"]))
        # FileChange -> Symbol edge exists instead.
        symbol_edge = next(e for e in doc["edges"] if e["source"] == file_node and e["target"] == symbol_node)
        self.assertEqual(symbol_edge["semantic_role"], "contains_symbol")
        self.assertIn(symbol_node, [n["id"] for n in doc["nodes"]])
        self.assertIn(file_node, [n["id"] for n in doc["nodes"]])

    def test_verification(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-verification")
        known = PromptRun(run_id, None, verification_ids=("ver-1",), gaps=("unavailable:prompt_version",))
        evidence = VerificationEvidence("ver-1", VerificationSource.EXECUTED, "passed", 100, 0, "raw output must not leak", ("a.py",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, verification_evidence={"ver-1": evidence})
        self.assertEqual(len(doc["citations"]), 1)
        self.assertEqual(doc["citations"][0]["evidence_kind"], "verification_run")
        self.assertNotIn("raw output must not leak", json.dumps(doc))
        verification_node = deterministic_identity(EntityKind.VERIFICATION_RUN, "ver-1").canonical
        edge = next(e for e in doc["edges"] if e["target"] == verification_node)
        self.assertEqual(edge["semantic_role"], "verified_by")

    def test_feedback(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-feedback")
        known = PromptRun(run_id, None, feedback_ids=("fb-1",), gaps=("unavailable:prompt_version",))
        record = FeedbackRecord("fb-1", run_id, "user", Judgment.ACHIEVED, (FeedbackReason.CORRECTNESS,), free_text="raw human text must not leak", submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, feedback_records={"fb-1": record})
        self.assertEqual(len(doc["citations"]), 1)
        self.assertNotIn("raw human text must not leak", json.dumps(doc))
        feedback_node = deterministic_identity(EntityKind.FEEDBACK_RECORD, "fb-1").canonical
        edge = next(e for e in doc["edges"] if e["target"] == feedback_node)
        self.assertEqual(edge["semantic_role"], "feedback_for")

    def test_outcome(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-outcome")
        known = PromptRun(run_id, None, outcome_references=("out-1",), gaps=("unavailable:prompt_version",))
        reference = OutcomeReference(OutcomeProvider.SECURITY, "finding", "out-1", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, outcome_evidence={"out-1": reference})
        self.assertEqual(len(doc["citations"]), 1)
        self.assertNotIn("unavailable:sibling_outcomes", doc["gaps"])
        outcome_node = deterministic_identity(EntityKind.OUTCOME_OBSERVATION, "out-1").canonical
        edge = next(e for e in doc["edges"] if e["target"] == outcome_node)
        self.assertEqual(edge["semantic_role"], "outcome_reference")

    def test_episode(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-episode")
        known = PromptRun(run_id, None, episode_id="ep-1", gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known)
        episode_node = deterministic_identity(EntityKind.EPISODE, "ep-1").canonical
        edge = next(e for e in doc["edges"] if e["target"] == episode_node)
        self.assertEqual(edge["semantic_role"], "episode_membership")

    def test_analysis(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-analysis")
        known = PromptRun(run_id, None, analysis_ids=("an-1",), gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known)
        analysis_node = deterministic_identity(EntityKind.ANALYSIS_VERSION, "an-1").canonical
        edge = next(e for e in doc["edges"] if e["target"] == analysis_node)
        self.assertEqual(edge["kind"], "evidence_lineage")
        self.assertEqual(edge["semantic_role"], "analysis_lineage")

    def test_memory_citation(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "with-memory")
        known = PromptRun(run_id, None, gaps=("unavailable:prompt_version",))
        memory_ref = ExternalReference("memory", "note", "note-1")
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, memory_references=(memory_ref,))
        memory_node = deterministic_identity(EntityKind.MEMORY_RECORD, "memory:note:note-1").canonical
        edge = next(e for e in doc["edges"] if e["target"] == memory_node)
        self.assertEqual(edge["semantic_role"], "cites_memory")

    def test_missing_prompt_version_is_an_explicit_gap(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "no-version")
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        self.assertIn("unavailable:prompt_version", doc["gaps"])

    def test_missing_tools_and_commands_is_an_explicit_gap(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "no-tools")
        known = PromptRun(run_id, None, agent_run_ids=("agent-1",), gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known)
        self.assertIn("unavailable:tool_and_command_observations", doc["gaps"])

    def test_unsupported_repository_symbol_resolution_is_a_gap_not_an_error(self):
        # Section G: no source parsing is performed by this bridge; a
        # change set with no caller-supplied entities is an honest gap.
        run_id, run_canonical = self.seed(PROJECT_KEY, "unsupported-symbols")
        known = PromptRun(run_id, None, change_set_ids=("cs-1",), gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known)
        change_node = deterministic_identity(EntityKind.CHANGE_SET, "cs-1").canonical
        self.assertIn(change_node, [n["id"] for n in doc["nodes"]])

    def test_cross_project_request_is_rejected(self):
        # A genuinely separate project's ledger — requesting this run there
        # is an honest "not found," not the ledger's own fail-closed
        # corruption error (which is what asking a mismatched project
        # against the SAME physical ledger file correctly triggers instead;
        # that's a distinct, already-covered invariant in test_ledger_*).
        run_id, run_canonical = self.seed(PROJECT_KEY, "cross-project")
        other_data_dir = self.data_dir / "other-project"
        other_data_dir.mkdir()
        record_prompt_run(other_data_dir / "evidence.jsonl", OTHER_PROJECT_KEY, "provider", "own-evt", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        with self.assertRaises(PromptRunNotFoundError):
            prompt_run_graph(other_data_dir, OTHER_PROJECT_KEY, run_canonical)

    def test_malformed_prompt_run_id_is_not_found_not_a_crash(self):
        # A raw stable key (the OLD, broken calling convention) is not a
        # parseable canonical identity — this must fail closed as an
        # honest PromptRunNotFoundError, never an uncaught traceback.
        with self.assertRaises(PromptRunNotFoundError):
            prompt_run_graph(self.data_dir, PROJECT_KEY, "provider:not-a-canonical-id")

    def test_deterministic_graph_rebuild(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "rebuild")
        known = PromptRun(run_id, "pv-1", agent_run_ids=("agent-1",), gaps=())
        first = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, tool_observation_ids={"agent-1": ("tool-1",)})
        second = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, tool_observation_ids={"agent-1": ("tool-1",)})
        self.assertEqual(first["nodes"], second["nodes"])
        self.assertEqual(first["edges"], second["edges"])

    def test_graph_schema_validation_rejects_a_malformed_document(self):
        from midnight_performance.contract_schema import ContractValidationError, validate_graph_prompt_run_response
        with self.assertRaises(ContractValidationError):
            validate_graph_prompt_run_response({"version": 1})

    def test_safe_evidence_reference_validation(self):
        from midnight_performance import EvidenceCitation
        with self.assertRaises(ValueError):
            EvidenceCitation("", "verification_run", "proj")

    def test_no_raw_prompt_output_code_in_response(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "no-raw-content")
        known = PromptRun(run_id, None, verification_ids=("ver-1",), feedback_ids=("fb-1",), gaps=("unavailable:prompt_version",))
        evidence = {"ver-1": VerificationEvidence("ver-1", VerificationSource.EXECUTED, "passed", 1, 0, "TOP SECRET COMMAND OUTPUT")}
        feedback = {"fb-1": FeedbackRecord("fb-1", run_id, "user", Judgment.ACHIEVED, free_text="TOP SECRET HUMAN COMMENTARY", submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))}
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, verification_evidence=evidence, feedback_records=feedback)
        blob = json.dumps(doc)
        self.assertNotIn("TOP SECRET", blob)

    def test_truncation_and_continuation(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "truncation")
        known = PromptRun(run_id, "pv-1", agent_run_ids=("agent-1",), change_set_ids=("cs-1",), gaps=())
        first = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, max_nodes=1)
        self.assertTrue(first["truncated"])
        self.assertIsNotNone(first["nextCursor"])
        seen_ids = {n["id"] for n in first["nodes"]}
        cursor = first["nextCursor"]
        pages = 1
        while cursor is not None:
            page = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, max_nodes=1, cursor=cursor)
            for n in page["nodes"]:
                self.assertNotIn(n["id"], seen_ids)
                seen_ids.add(n["id"])
            cursor = page["nextCursor"]
            pages += 1
            self.assertLess(pages, 20)
        # root + prompt_version + agent_run + change_set = 4 nodes total
        self.assertEqual(len(seen_ids), 4)

    def test_foreign_cursor_is_rejected(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "foreign-cursor")
        with self.assertRaises(InvalidGraphCursorError):
            prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, cursor="not-a-real-cursor")

    def test_max_depth_bound_limits_reachability(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "depth-bound")
        known = PromptRun(run_id, None, agent_run_ids=("agent-1",), gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, tool_observation_ids={"agent-1": ("tool-1",)}, max_depth=1)
        tool_node = deterministic_identity(EntityKind.TOOL_OBSERVATION, "tool-1").canonical
        self.assertNotIn(tool_node, [n["id"] for n in doc["nodes"]])
        self.assertTrue(doc["truncated"])

    def test_allowed_layers_filters_nodes(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "layer-filter")
        known = PromptRun(run_id, "pv-1", gaps=())
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, allowed_layers=frozenset({"execution"}))
        self.assertEqual(doc["nodes"], [])  # root and prompt_version are both "prompt" layer, filtered out
        self.assertTrue(doc["truncated"])

    def test_cli_produces_the_same_document(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "cli-check")
        completed = subprocess.run(
            [sys.executable, "-m", "midnight_performance.graph_bridge", "--data-dir", str(self.data_dir), "--project", PROJECT_KEY, "--prompt-run-id", run_canonical],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        document = json.loads(completed.stdout)
        self.assertEqual(document["root"], run_canonical)

    def test_cli_reports_not_found_via_exit_code_not_a_traceback(self):
        from midnight_performance.graph_bridge import EXIT_NOT_FOUND

        unknown_canonical = deterministic_identity(EntityKind.PROMPT_RUN, "provider:never-recorded").canonical
        completed = subprocess.run(
            [sys.executable, "-m", "midnight_performance.graph_bridge", "--data-dir", str(self.data_dir), "--project", PROJECT_KEY, "--prompt-run-id", unknown_canonical],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(completed.returncode, EXIT_NOT_FOUND)
        self.assertEqual(completed.stdout, "")
        # The last non-blank stderr line is this bridge's own structured
        # error; a harmless `-m`-invocation RuntimeWarning (Execution 03,
        # cosmetic — see that execution's report) can precede it.
        last_line = [line for line in completed.stderr.splitlines() if line.strip()][-1]
        error = json.loads(last_line)
        self.assertEqual(error["error"], "not_found")


class GraphProjectionIdentityTests(unittest.TestCase):
    """Execution 10, Section B: a graph response must describe project,
    root, graph schema/algorithm version, and evidence checkpoint — a
    fingerprint for cache-key building, never itself treated as canonical
    evidence (Section C: 'do not call a cache hash canonical evidence')."""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"

    def seed(self, project_key: str, event_id: str) -> tuple[str, str]:
        appended, canonical = record_prompt_run(self.ledger_path, project_key, "provider", event_id, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(appended)
        return f"provider:{event_id}", canonical

    def test_projection_identity_describes_project_root_version_and_checkpoint(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "identity-1")
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        identity = doc["projectionIdentity"]
        self.assertEqual(identity["project"], doc["project"])
        self.assertEqual(identity["root"], run_canonical)
        self.assertEqual(identity["graphSchemaVersion"], doc["version"])
        self.assertTrue(identity["graphAlgorithmMethod"])
        self.assertTrue(identity["graphAlgorithmVersion"])
        self.assertTrue(identity["evidenceCheckpoint"])

    def test_evidence_checkpoint_changes_after_new_evidence_is_appended(self):
        # The cache-invalidation precondition Section C relies on: a graph
        # rebuild against a GROWN ledger must report a DIFFERENT checkpoint,
        # even for the exact same Prompt Run/slice — so any cache keyed on
        # this value naturally misses instead of serving stale results.
        run_id, run_canonical = self.seed(PROJECT_KEY, "identity-2")
        before = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        self.seed(PROJECT_KEY, "identity-2-sibling")
        after = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        self.assertNotEqual(
            before["projectionIdentity"]["evidenceCheckpoint"],
            after["projectionIdentity"]["evidenceCheckpoint"],
        )
        # The document's own real content (this Prompt Run's own slice) is
        # unaffected by an unrelated sibling being appended -- only the
        # checkpoint (evidence ledger fingerprint) changed.
        self.assertEqual(before["nodes"], after["nodes"])

    def test_evidence_checkpoint_is_stable_across_rebuilds_with_no_new_evidence(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "identity-3")
        first = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        second = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        self.assertEqual(
            first["projectionIdentity"]["evidenceCheckpoint"],
            second["projectionIdentity"]["evidenceCheckpoint"],
        )


class GraphTruncationReasonTests(unittest.TestCase):
    """Execution 10, Section A: a stable, machine-readable truncation
    reason — never just a bare boolean a client has to guess about."""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"

    def seed(self, project_key: str, event_id: str) -> tuple[str, str]:
        appended, canonical = record_prompt_run(self.ledger_path, project_key, "provider", event_id, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(appended)
        return f"provider:{event_id}", canonical

    def test_untruncated_document_reports_no_reasons(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "reasons-none")
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical)
        self.assertFalse(doc["truncated"])
        self.assertEqual(doc["truncationReasons"], [])

    def test_max_nodes_reports_max_nodes_reason(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "reasons-nodes")
        known = PromptRun(run_id, "pv-1", agent_run_ids=("agent-1",), gaps=())
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, max_nodes=1)
        self.assertIn("max_nodes", doc["truncationReasons"])

    def test_max_depth_reports_max_depth_reason(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "reasons-depth")
        known = PromptRun(run_id, None, agent_run_ids=("agent-1",), gaps=("unavailable:prompt_version",))
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, tool_observation_ids={"agent-1": ("tool-1",)}, max_depth=1)
        self.assertIn("max_depth", doc["truncationReasons"])

    def test_layer_filter_reports_layer_filter_reason(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "reasons-layer")
        known = PromptRun(run_id, "pv-1", gaps=())
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, allowed_layers=frozenset({"execution"}))
        self.assertIn("layer_filter", doc["truncationReasons"])

    def test_max_edges_reports_max_edges_reason(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "reasons-edges")
        known = PromptRun(run_id, "pv-1", agent_run_ids=("agent-1",), change_set_ids=("cs-1",), gaps=())
        doc = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, max_edges=1)
        self.assertIn("max_edges", doc["truncationReasons"])
        self.assertTrue(doc["truncated"])


class GraphNeighborhoodExpansionTests(unittest.TestCase):
    """Execution 10, Section A: `focus_node` expands a maxDepth-bounded
    view around a specific node, without ever changing `root` away from the
    Prompt Run itself."""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.data_dir = Path(self._temporary.name)
        self.ledger_path = self.data_dir / "evidence.jsonl"

    def seed(self, project_key: str, event_id: str) -> tuple[str, str]:
        appended, canonical = record_prompt_run(self.ledger_path, project_key, "provider", event_id, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(appended)
        return f"provider:{event_id}", canonical

    def test_focus_node_reveals_neighbors_beyond_the_root_depth_window(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "focus-1")
        known = PromptRun(run_id, None, agent_run_ids=("agent-1",), gaps=("unavailable:prompt_version",))
        agent_node = deterministic_identity(EntityKind.AGENT_RUN, "agent-1").canonical
        tool_node = deterministic_identity(EntityKind.TOOL_OBSERVATION, "tool-1").canonical

        without_focus = prompt_run_graph(
            self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known,
            tool_observation_ids={"agent-1": ("tool-1",)}, max_depth=1,
        )
        self.assertNotIn(tool_node, [n["id"] for n in without_focus["nodes"]])

        with_focus = prompt_run_graph(
            self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known,
            tool_observation_ids={"agent-1": ("tool-1",)}, max_depth=1, focus_node=agent_node,
        )
        node_ids = [n["id"] for n in with_focus["nodes"]]
        self.assertIn(tool_node, node_ids)
        # Expansion is additive: root's own window is still present too.
        self.assertIn(run_canonical, node_ids)
        self.assertEqual(with_focus["root"], run_canonical)  # focus_node never changes root
        self.assertEqual(with_focus["bounds"]["focusNode"], agent_node)

    def test_unknown_focus_node_is_rejected(self):
        from midnight_performance.graph_bridge import InvalidGraphFocusError

        run_id, run_canonical = self.seed(PROJECT_KEY, "focus-2")
        bogus_node = deterministic_identity(EntityKind.AGENT_RUN, "never-existed").canonical
        with self.assertRaises(InvalidGraphFocusError):
            prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, focus_node=bogus_node)

    def test_malformed_focus_node_is_rejected(self):
        from midnight_performance.graph_bridge import InvalidGraphFocusError

        run_id, run_canonical = self.seed(PROJECT_KEY, "focus-3")
        with self.assertRaises(InvalidGraphFocusError):
            prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, focus_node="not-a-real-identity")

    def test_focus_node_is_inert_without_max_depth(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "focus-4")
        known = PromptRun(run_id, None, agent_run_ids=("agent-1",), gaps=("unavailable:prompt_version",))
        agent_node = deterministic_identity(EntityKind.AGENT_RUN, "agent-1").canonical
        without = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known)
        withit = prompt_run_graph(self.data_dir, PROJECT_KEY, run_canonical, known_evidence=known, focus_node=agent_node)
        self.assertEqual(without["nodes"], withit["nodes"])

    def test_cli_focus_node_flag_reaches_the_bridge(self):
        run_id, run_canonical = self.seed(PROJECT_KEY, "focus-cli")
        known_agent_node = deterministic_identity(EntityKind.AGENT_RUN, "agent-1").canonical
        completed = subprocess.run(
            [sys.executable, "-m", "midnight_performance.graph_bridge", "--data-dir", str(self.data_dir),
             "--project", PROJECT_KEY, "--prompt-run-id", run_canonical, "--focus-node", known_agent_node],
            capture_output=True, text=True, timeout=60,
        )
        from midnight_performance.graph_bridge import EXIT_INVALID_FOCUS
        # agent-1 was never actually wired into this run's real graph here,
        # so the CLI must reject it the same way the function does --
        # proving the flag really reaches prompt_run_graph, not silently
        # ignored.
        self.assertEqual(completed.returncode, EXIT_INVALID_FOCUS)


if __name__ == "__main__":
    unittest.main()
