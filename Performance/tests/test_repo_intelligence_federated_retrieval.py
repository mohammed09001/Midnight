"""Federated query routing, bounded local/global retrieval, and evidence paths."""

import unittest
from datetime import datetime, timezone

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import EdgeClass, GraphLink, GraphRelation
from midnight_performance.repo_intelligence.federated_retrieval import QueryClass, RetrievalControls, RetrievalQuery, classify_query, retrieve
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence.project_graph import ConceptRole, GraphNode, NodeFamily, ProjectKnowledgeGraph

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "federated-alpha")
OTHER = deterministic_identity(EntityKind.PROJECT, "federated-beta")
FILE = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_ENTITY_REF, "auth-file").canonical
PERF = deterministic_identity(EntityKind.VERIFICATION_RUN, "auth-failure").canonical
CONCEPT = deterministic_repo_identity(RepoIntelligenceKind.CONCEPT, "retry-concept").canonical

def graph(project=PROJECT, file_label="src/auth/session.py"):
    nodes = (
        GraphNode(FILE, project.canonical, NodeFamily.REPOSITORY_STRUCTURE, file_label, ClaimKind.DERIVED, T0, T0, ("repository snapshot",)),
        GraphNode(PERF, project.canonical, NodeFamily.PERFORMANCE_EVIDENCE, "failed verification cluster", ClaimKind.DERIVED, T0, T0, (PERF,)),
        GraphNode(CONCEPT, project.canonical, NodeFamily.CONCEPT, "authentication retry pattern", ClaimKind.INFERRED, T0, T0, (PERF,), ConceptRole.PATTERN),
    )
    links = (
        GraphLink(deterministic_repo_identity(RepoIntelligenceKind.GRAPH_LINK, "file-perf"), project, FILE, PERF, GraphRelation.FAILED_IN, EdgeClass.STRUCTURAL, ClaimKind.DERIVED, "fixture", "1", "exact typed reference", (PERF,), T0, T0),
        GraphLink(deterministic_repo_identity(RepoIntelligenceKind.GRAPH_LINK, "perf-concept"), project, PERF, CONCEPT, GraphRelation.ABOUT, EdgeClass.SEMANTIC, ClaimKind.INFERRED, "fixture", "1", "semantic classification may be wrong", (PERF,), T0, T0, .7),
    )
    return ProjectKnowledgeGraph(project.canonical, "alpha", nodes, links, "generation", T0)

class FederatedRetrievalTests(unittest.TestCase):
    def test_routes_local_global_external_learning_and_provenance_queries(self):
        cases = {
            "explain auth session": QueryClass.ENTITY_LOCAL,
            "what happened around this hotspot": QueryClass.ACTIVITY_LOCAL,
            "catch me up project-wide": QueryClass.PROJECT_GLOBAL,
            "find an external analogue": QueryClass.EXTERNAL_ANALOGUE,
            "what should I understand next": QueryClass.LEARNING_PATH,
            "where did this insight come from": QueryClass.PROVENANCE_PATH,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_query(RetrievalQuery(text)), expected)

    def test_cycle_safe_bounded_retrieval_is_deterministic(self):
        query = RetrievalQuery("authentication retry", anchor_identity=FILE)
        controls = RetrievalControls(maximum_hops=3, maximum_nodes=3)
        first = retrieve(graph(), query, RepoIntelligenceAuthorization(PROJECT), now=T0, controls=controls)
        second = retrieve(graph(), query, RepoIntelligenceAuthorization(PROJECT), now=T0, controls=controls)
        self.assertEqual(first.hits, second.hits)
        self.assertLessEqual(len(first.hits), 3)
        self.assertEqual(len({hit.identity for hit in first.hits}), len(first.hits))

    def test_path_distinguishes_exact_and_probabilistic_edges_with_lineage(self):
        result = retrieve(graph(), RetrievalQuery("why believe this", anchor_identity=FILE, exact_identities=(CONCEPT,)), RepoIntelligenceAuthorization(PROJECT), now=T0)
        self.assertTrue(result.path and result.path.found)
        self.assertEqual([hop.edge_type for hop in result.path.hops], ["exact", "probabilistic"])
        self.assertTrue(all(hop.evidence_ids for hop in result.path.hops))
        self.assertIn("semantic", result.path.hops[-1].uncertainty)

    def test_global_community_and_followups_are_lazy_bounded(self):
        result = retrieve(graph(), RetrievalQuery("catch me up project-wide authentication"), RepoIntelligenceAuthorization(PROJECT), now=T0, controls=RetrievalControls(maximum_communities=1, maximum_follow_up_questions=1), information_gain=.8)
        self.assertLessEqual(len(result.selected_communities), 1)
        self.assertEqual(len(result.follow_up_questions), 1)

    def test_external_stage_is_planned_but_no_network_is_called(self):
        denied = retrieve(graph(), RetrievalQuery("external analogue", allow_external=True), RepoIntelligenceAuthorization(PROJECT), now=T0, information_gain=.8)
        self.assertFalse(denied.external_lookup_required)
        self.assertIn("denies network", " ".join(denied.gaps))
        allowed = retrieve(graph(), RetrievalQuery("external analogue", allow_external=True), RepoIntelligenceAuthorization(PROJECT, external_access=True), now=T0, information_gain=.8)
        self.assertTrue(allowed.external_lookup_required)

    def test_missing_memory_is_an_honest_gap_and_rename_updates_labels(self):
        missing = retrieve(graph(), RetrievalQuery("what should I understand next"), RepoIntelligenceAuthorization(PROJECT), now=T0, memory_available=False)
        self.assertIn("does not reconstruct", " ".join(missing.gaps))
        renamed = retrieve(graph(file_label="src/auth/renamed_session.py"), RetrievalQuery("renamed session"), RepoIntelligenceAuthorization(PROJECT), now=T0)
        self.assertEqual(renamed.hits[0].label, "src/auth/renamed_session.py")

    def test_cross_project_graph_fails_closed(self):
        with self.assertRaises(PermissionError):
            retrieve(graph(OTHER), RetrievalQuery("auth"), RepoIntelligenceAuthorization(PROJECT), now=T0)

if __name__ == "__main__": unittest.main()
