import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from midnight_performance import (
    ClaimKind, EdgeKind, EntityKind, ExternalReference, FeedbackRecord, FeedbackReason,
    GraphEdge, Judgment, PerformanceGraph, PromptRevision, build_experience_neighborhood_visualization,
    build_graph, build_lineage, build_neighborhood, build_performance_visual_map,
    build_prompt_lineage_visualization, as_query_projection, analyze_prompt, classify_taxonomy,
    deterministic_identity, Experience, PromptRun, Neighborhood, NeighborhoodMember, SimilarityMatch,
    ChangeEvidence, VerificationEvidence, VerificationSource, VisualNodeMetadata,
    build_performance_visual_map_from_inputs, EvidenceLedger, PrivacyGuard, PrivacyPolicy,
    PerformanceQueryAPI, QueryAuthorization,
)


class VisualIntelligenceTests(unittest.TestCase):
    def _experience(self, ident, judgment=Judgment.ACHIEVED, reasons=()):
        text = "Fix the auth token issue and verify login."
        features, _ = analyze_prompt(text)
        return Experience(ident, text, features, classify_taxonomy(ident, text), feedback=(FeedbackRecord(f"feedback-{ident}", ident, "user", judgment, reasons, submitted_at=datetime(2026, 8, 28, tzinfo=timezone.utc)),))

    def test_performance_map_is_deterministic_and_only_reifies_graph_evidence(self):
        run = PromptRun("run", "v1", agent_run_ids=("agent",), change_set_ids=("change",), verification_ids=("verify",), feedback_ids=("feedback",), outcome_references=("watch:outcome",), analysis_ids=("analysis",), episode_id="episode", gaps=("unresolved:repository_entity",))
        graph = build_graph(run, memory_references=(ExternalReference("memory", "record", "m1"),))
        dataset, experiment = deterministic_identity(EntityKind.DATASET_ITEM, "data"), deterministic_identity(EntityKind.EXPERIMENT_RUN, "experiment")
        graph = PerformanceGraph(graph.edges + (GraphEdge(deterministic_identity(EntityKind.PROMPT_RUN, "run"), dataset, EdgeKind.REFERENCE, ClaimKind.DERIVED, None, ("data",), "test", "1", "typed dataset reference"), GraphEdge(deterministic_identity(EntityKind.PROMPT_RUN, "run"), experiment, EdgeKind.REFERENCE, ClaimKind.DERIVED, None, ("experiment",), "test", "1", "typed experiment reference")), graph.gaps)
        view = build_performance_visual_map(graph, project_context="project-a", external_nodes=frozenset({next(n for n in graph.nodes if n.kind is EntityKind.OUTCOME_OBSERVATION)}))
        self.assertEqual(view, build_performance_visual_map(graph, project_context="project-a", external_nodes=frozenset({next(n for n in graph.nodes if n.kind is EntityKind.OUTCOME_OBSERVATION)})))
        self.assertEqual({node.entity_kind for node in view.nodes} >= {EntityKind.PROMPT_RUN, EntityKind.AGENT_RUN, EntityKind.CHANGE_SET, EntityKind.VERIFICATION_RUN, EntityKind.FEEDBACK_RECORD, EntityKind.EPISODE, EntityKind.MEMORY_RECORD, EntityKind.DATASET_ITEM, EntityKind.EXPERIMENT_RUN}, True)
        self.assertIn("unresolved:repository_entity", view.gaps)
        self.assertTrue(next(node.externally_referenced for node in view.nodes if node.entity_kind is EntityKind.OUTCOME_OBSERVATION))
        self.assertEqual(len(view.edges), len(graph.edges))
        self.assertEqual(as_query_projection("visual-map", view).claim_kind, ClaimKind.DERIVED)

    def test_lineage_visualization_preserves_declared_identity_and_gaps(self):
        parent_features, _ = analyze_prompt("Must authenticate.\nVerify login.\nDone when tests pass.")
        child_features, _ = analyze_prompt("Must authenticate.\nMust not log passwords.\nVerify session expiry.\nDone when tests pass.")
        parent = PromptRevision("v1", None, parent_features, datetime(2026, 8, 28, tzinfo=timezone.utc))
        child = PromptRevision("v2", "v1", child_features, datetime(2026, 8, 29, tzinfo=timezone.utc))
        view = build_prompt_lineage_visualization((parent, child), build_lineage((parent, child)), change_sets={"v2": ("change-2",)}, feedback_ids={"v2": ("feedback-2",)}, runtime_references={"v2": (ExternalReference("watch-runtime", "outcome", "r2"),)})
        self.assertEqual(view.edges[0].parent_version_id, "v1")
        self.assertIn("Must not log passwords.", view.edges[0].added_constraints)
        self.assertIn("v1:unavailable:runtime_outcomes", view.gaps)
        self.assertIn("unknown, not zero", view.edges[0].uncertainty)
        with self.assertRaises(ValueError):
            build_prompt_lineage_visualization((parent, child), ())

    def test_lineage_serializes_semantic_outcomes_without_repr(self):
        features, _ = analyze_prompt("Must authenticate.\nVerify login.")
        parent = PromptRevision("v1", None, features, datetime(2026, 8, 28, tzinfo=timezone.utc))
        child = PromptRevision("v2", "v1", features, datetime(2026, 8, 29, tzinfo=timezone.utc))
        view = build_prompt_lineage_visualization(
            (parent, child), build_lineage((parent, child), {"v1": (1, 5), "v2": (3, 5)}),
            change_evidence={"v2": ChangeEvidence(("new.py",), ("edited.py",), ("old.py",))},
            verifications={"v2": (VerificationEvidence("check", VerificationSource.EXECUTED, "passed", 10, 0, "ok"),)},
        )
        record = view.as_records()[0]
        self.assertEqual(record["schema_version"], "2")
        self.assertEqual(record["revisions"][1]["repository_outcome"]["deleted"], ("old.py",))
        self.assertEqual(record["revisions"][1]["verification_outcome"][0]["status"], "passed")
        self.assertIsInstance(record["edges"][0]["outcome_shift"], dict)
        self.assertNotIn("ComparisonResult(", str(record))

    def test_composition_builds_real_typed_map_and_rejects_foreign_metadata(self):
        run = PromptRun("run", "v1", agent_run_ids=("agent",), change_set_ids=("change",), gaps=())
        file_entity = deterministic_identity(EntityKind.FILE_CHANGE, "src/auth.py")
        view = build_performance_visual_map_from_inputs(
            (run,), resolved_entities={"change": (file_entity,)}, dataset_ids={"run": ("dataset",)},
            experiment_ids={"run": ("experiment",)}, memory_references={"run": (ExternalReference("memory", "record", "m1"),)}, agent_session_ids={"agent": ("session",)}, agent_turn_ids={"agent": ("turn",)},
        )
        self.assertTrue({EntityKind.FILE_CHANGE, EntityKind.DATASET_ITEM, EntityKind.EXPERIMENT_RUN, EntityKind.MEMORY_RECORD, EntityKind.AGENT_SESSION, EntityKind.AGENT_TURN} <= {n.entity_kind for n in view.nodes})
        self.assertEqual(view, build_performance_visual_map_from_inputs((run,), resolved_entities={"change": (file_entity,)}, dataset_ids={"run": ("dataset",)}, experiment_ids={"run": ("experiment",)}, memory_references={"run": (ExternalReference("memory", "record", "m1"),)}, agent_session_ids={"agent": ("session",)}, agent_turn_ids={"agent": ("turn",)}))
        foreign = deterministic_identity(EntityKind.FILE_CHANGE, "foreign")
        with self.assertRaises(ValueError):
            build_performance_visual_map(PerformanceGraph(()), node_metadata={foreign: VisualNodeMetadata()})
        unresolved = build_performance_visual_map_from_inputs((run,))
        self.assertIn("change:unavailable:repository_entity_resolution", unresolved.gaps)
        self.assertIn("run:unavailable:memory_references", unresolved.gaps)

    def test_visual_node_metadata_is_projected_and_serialized(self):
        run = PromptRun("run", "v1")
        graph = build_graph(run)
        node = next(item for item in graph.nodes if item.kind is EntityKind.PROMPT_RUN)
        metadata = VisualNodeMetadata("run label", ClaimKind.DERIVED, ("ledger:event-1",), datetime(2026, 8, 28, tzinfo=timezone.utc), "project-a", gaps=("partial:label",))
        view = build_performance_visual_map(graph, node_metadata={node: metadata})
        record = next(item for item in view.as_records()[0]["nodes"] if item["id"] == node.canonical)
        self.assertEqual((record["label"], record["provenance"], record["project_context"]), ("run label", ("ledger:event-1",), "project-a"))
        with self.assertRaises(ValueError):
            VisualNodeMetadata(claim_kind=ClaimKind.OBSERVED)

    def test_visual_projection_uses_existing_query_authorization(self):
        project = deterministic_identity(EntityKind.PROJECT, "one")
        with TemporaryDirectory() as temporary:
            ledger = EvidenceLedger(Path(temporary) / "evidence.jsonl", project, PrivacyGuard(PrivacyPolicy()))
            view = build_performance_visual_map(PerformanceGraph(()))
            api = PerformanceQueryAPI(ledger, projections={"visual": as_query_projection("visual", view)})
            authorization = QueryAuthorization(project)
            self.assertEqual(api.projection(authorization, "visual").version, "1")
            self.assertEqual(api.list_projections(authorization), (("visual", "1"),))
            with self.assertRaises(PermissionError):
                api.projection(QueryAuthorization(deterministic_identity(EntityKind.PROJECT, "other")), "visual")

    def test_neighborhood_visualization_preserves_buckets_explanations_and_self_gap(self):
        query = self._experience("query")
        candidates = (query, self._experience("successful"), self._experience("partial", Judgment.PARTIAL), self._experience("failed", Judgment.NOT_ACHIEVED), self._experience("regressed", Judgment.ACHIEVED, (FeedbackReason.REGRESSION,)), self._experience("uncertain", Judgment.UNCERTAIN))
        neighborhood = build_neighborhood(query, candidates, top_k_per_bucket=1)
        view = build_experience_neighborhood_visualization(neighborhood, query, {item.prompt_run_id: item for item in candidates})
        self.assertIn("excluded:self_candidate:query", view.gaps)
        self.assertEqual(set(view.buckets), {"successful", "partial", "failed", "regressed", "uncertain"})
        self.assertEqual(view.buckets["regressed"][0].bucket, "regressed")
        self.assertTrue(view.buckets["successful"][0].signals)
        self.assertEqual(view.claim_kind, ClaimKind.DERIVED)
        self.assertIn("not a similarity result", view.center.uncertainty)

    def test_neighborhood_view_keeps_unavailable_similarity_unknown(self):
        query, candidate = self._experience("query"), self._experience("candidate", Judgment.UNCERTAIN)
        unavailable = SimilarityMatch("candidate", None, (), ("no comparable signals",), "retrieval", "1", ClaimKind.UNKNOWN, "unavailable similarity is unknown, not zero")
        neighborhood = Neighborhood("query", (NeighborhoodMember(unavailable, "uncertain"),), "retrieval", "1", ClaimKind.DERIVED, "bucketed retrieval is not recommendation")
        view = build_experience_neighborhood_visualization(neighborhood, query, {"candidate": candidate})
        self.assertIsNone(view.buckets["uncertain"][0].score)
        self.assertEqual(view.buckets["uncertain"][0].claim_kind, ClaimKind.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
