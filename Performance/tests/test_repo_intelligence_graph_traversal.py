"""Repo Intelligent graph traversal: budgets, cycle safety, evidence-citing paths."""

import unittest
from datetime import datetime, timezone

from midnight_performance.contracts import ClaimKind, deterministic_identity, EntityKind
from midnight_performance.repo_intelligence.contracts import (
    EdgeClass,
    GraphLink,
    GraphRelation,
)
from midnight_performance.repo_intelligence.entity_resolution import (
    bootstrap_entity_refs,
)
from midnight_performance.repo_intelligence.identities import (
    RepoIntelligenceKind,
    deterministic_repo_identity,
)
from midnight_performance.repo_intelligence.graph_traversal import (
    communities,
    explain_path,
    neighbors,
    traverse,
)
from midnight_performance.repo_intelligence.project_graph import (
    ConceptRole,
    build_project_graph,
    concept_identity,
)
from midnight_performance.repository_capture import RepositorySnapshot

PROJECT_ALPHA = deterministic_identity(EntityKind.PROJECT, "alpha")
NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def fixture_graph():
    snapshot = RepositorySnapshot(
        files={
            "src/auth/__init__.py": "a" * 64,
            "src/auth/session.py": "b" * 64,
            "src/auth/token.py": "d" * 64,
            "tests/test_session.py": "c" * 64,
        }
    )
    refs = bootstrap_entity_refs(PROJECT_ALPHA, "alpha", snapshot, now=NOW)
    graph = build_project_graph(
        PROJECT_ALPHA,
        "alpha",
        entity_refs=refs.values(),
        concept_specs=(("auth session", ConceptRole.TOPIC),),
        now=NOW,
    )
    labels = {node.label: node.identity for node in graph.nodes}
    return graph, labels


class NeighborTests(unittest.TestCase):
    def test_neighbors_cover_both_directions_with_filters(self):
        graph, labels = fixture_state_labels()
        module = labels["src/auth/session.py"]
        outgoing = neighbors(graph, module, direction="outgoing")
        incoming = neighbors(graph, module, direction="incoming")
        self.assertTrue(outgoing)
        self.assertTrue(incoming)
        for neighbor in outgoing:
            self.assertEqual(neighbor.direction, "outgoing")
            self.assertEqual(neighbor.via.source, module)
        contains_only = neighbors(graph, module, relations=frozenset({GraphRelation.CONTAINS}))
        self.assertTrue(all(n.via.relation is GraphRelation.CONTAINS for n in contains_only))

    def test_invalid_direction_is_rejected(self):
        graph, labels = fixture_state_labels()
        with self.assertRaises(ValueError):
            neighbors(graph, labels["src/auth/session.py"], direction="sideways")


class TraversalTests(unittest.TestCase):
    def test_bounded_hops_and_deterministic_order(self):
        graph, labels = fixture_state_labels()
        start = labels["alpha"]
        first = traverse(graph, start, max_hops=2, max_nodes=500)
        second = traverse(graph, start, max_hops=2, max_nodes=500)
        self.assertEqual(first.visited, second.visited)
        self.assertIn(start, first.visited)
        self.assertGreaterEqual(first.hops_used, 1)

        one_hop = traverse(graph, start, max_hops=1, max_nodes=500)
        two_hop = traverse(graph, start, max_hops=2, max_nodes=500)
        self.assertTrue(set(one_hop.visited) <= set(two_hop.visited))
        self.assertGreater(len(two_hop.visited), len(one_hop.visited))

    def test_node_budget_truncates_with_flag(self):
        graph, labels = fixture_state_labels()
        start = labels["alpha"]
        result = traverse(graph, start, max_hops=4, max_nodes=3)
        self.assertEqual(len(result.visited), 3)
        self.assertTrue(result.truncated)

    def test_cycle_safety_terminates(self):
        graph, labels = fixture_state_labels()
        a = labels["src/auth/session.py"]
        b = labels["src/auth/token.py"]

        def bidirectional(relation, method):
            for source, target in ((a, b), (b, a)):
                yield GraphLink(
                    identity=deterministic_repo_identity(
                        RepoIntelligenceKind.GRAPH_LINK,
                        f"cycle|{relation.value}|{source[-8:]}|{target[-8:]}|{method}",
                    ),
                    project=PROJECT_ALPHA,
                    source=source,
                    target=target,
                    relation=relation,
                    edge_class=EdgeClass.SEMANTIC,
                    claim_kind=ClaimKind.INFERRED,
                    method=method,
                    method_version="1",
                    uncertainty="cycle fixture",
                    evidence_ids=(source,),
                    first_seen=NOW,
                    last_seen=NOW,
                    confidence=0.5,
                )

        cycled = build_project_graph(
            PROJECT_ALPHA,
            "alpha",
            entity_refs=bootstrap_entity_refs(
                PROJECT_ALPHA,
                "alpha",
                RepositorySnapshot(
                    files={
                        "src/auth/session.py": "b" * 64,
                        "src/auth/token.py": "d" * 64,
                    }
                ),
                now=NOW,
            ).values(),
            extra_links=tuple(bidirectional(GraphRelation.RELATED_TO, "fixture-model")),
            now=NOW,
        )
        result = traverse(cycled, a, max_hops=8, max_nodes=500)
        self.assertEqual(len(result.visited), len(set(result.visited)))
        self.assertGreaterEqual(result.hops_used, 1)

    def test_start_must_be_a_graph_node(self):
        graph, _ = fixture_state_labels()
        with self.assertRaises(ValueError):
            traverse(graph, "mp:v1:prompt_run:00000000-0000-0000-0000-000000000009")

    def test_budget_bounds_are_validated(self):
        graph, labels = fixture_state_labels()
        with self.assertRaises(ValueError):
            traverse(graph, labels["alpha"], max_hops=0)
        with self.assertRaises(ValueError):
            traverse(graph, labels["alpha"], max_nodes=100000)


class PathExplanationTests(unittest.TestCase):
    def test_path_hops_cite_underlying_evidence(self):
        graph, labels = fixture_state_labels()
        package = labels["src/auth"]
        module = labels["src/auth/session.py"]
        explanation = explain_path(graph, package, module, max_hops=2)
        self.assertTrue(explanation.found)
        self.assertEqual(len(explanation.hops), 1)
        hop = explanation.hops[0]
        self.assertEqual(hop.from_identity, package)
        self.assertEqual(hop.to_identity, module)
        self.assertTrue(hop.evidence_ids)
        self.assertEqual(hop.link.relation, GraphRelation.CONTAINS)

    def test_unreachable_target_reports_not_found(self):
        graph, labels = fixture_state_labels()
        repo = labels["alpha"]
        concept = concept_identity(PROJECT_ALPHA, "auth session", ConceptRole.TOPIC).canonical
        explanation = explain_path(graph, repo, concept, max_hops=2)
        self.assertFalse(explanation.found)
        self.assertEqual(explanation.hops, ())

    def test_longer_paths_are_found_within_hop_budget(self):
        graph, labels = fixture_state_labels()
        repo = labels["alpha"]
        module = labels["src/auth/session.py"]
        explanation = explain_path(graph, repo, module, max_hops=3)
        self.assertTrue(explanation.found)
        self.assertLessEqual(len(explanation.hops), 3)


class CommunityTests(unittest.TestCase):
    def test_components_are_deterministic_and_cover_the_graph(self):
        graph, _ = fixture_state_labels()
        first = communities(graph)
        second = communities(graph)
        self.assertEqual(
            [c.members for c in first], [c.members for c in second]
        )
        all_members = {m for c in first for m in c.members}
        self.assertEqual(all_members, {node.identity for node in graph.nodes})
        self.assertTrue(all(c.members for c in first))

    def test_relation_subset_changes_grouping(self):
        graph, _ = fixture_state_labels()
        contains_only = communities(graph, relations=frozenset({GraphRelation.CONTAINS}))
        everything = communities(graph)
        self.assertTrue(contains_only)
        self.assertTrue(everything)

    def test_max_communities_bounds_output(self):
        graph, _ = fixture_state_labels()
        bounded = communities(graph, max_communities=1)
        self.assertLessEqual(len(bounded), 1)


def fixture_state_labels():
    graph, labels = fixture_graph()
    return graph, labels


if __name__ == "__main__":
    unittest.main()
