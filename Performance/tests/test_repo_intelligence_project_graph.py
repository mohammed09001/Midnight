"""Repo Intelligent project knowledge graph: determinism, integrity, updates."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import (
    ClaimKind,
    ExternalReference,
    Observation,
    deterministic_identity,
    EntityKind,
)
from midnight_performance.observation_model import (
    ObservationEnvelope,
    ObservationLayer,
    ObservationType,
)
from midnight_performance.repo_intelligence.authorization import CrossProjectAccessError
from midnight_performance.repo_intelligence.contracts import (
    EdgeClass,
    EvidenceBundle,
    EvidenceItem,
    Exposure,
    ExposureChannel,
    ExposureOutcome,
    GraphLink,
    GraphRelation,
    InternalAnswerStatus,
    ResearchQuestion,
    evidence_bundle_identity,
    research_question_identity,
)
from midnight_performance.repo_intelligence.entity_resolution import (
    bootstrap_entity_refs,
    index_refs_by_path,
)
from midnight_performance.repo_intelligence.identities import (
    RepoIntelligenceKind,
    deterministic_repo_identity,
)
from midnight_performance.repo_intelligence.evidence_join import join_evidence
from midnight_performance.repo_intelligence.project_graph import (
    ConceptRole,
    NodeFamily,
    build_project_graph,
    memory_ref_identity,
    stale_links,
    active_links,
    update_project_graph,
    validate_overlay,
)
from midnight_performance.repo_intelligence.question_compiler import abstract_concept
from midnight_performance.repo_intelligence.signals import scan_signals
from midnight_performance.repository_capture import RepositorySnapshot

PROJECT_ALPHA = deterministic_identity(EntityKind.PROJECT, "alpha")
PROJECT_BETA = deterministic_identity(EntityKind.PROJECT, "beta")
NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
D = timedelta(days=1)
WINDOW_START = NOW - 14 * D
WINDOW_END = NOW

_counter = [0]


def change_env(files, at, *, episode=None, suffix=None, project=PROJECT_ALPHA):
    _counter[0] += 1
    suffix = suffix or _counter[0]
    return ObservationEnvelope(
        observation=Observation(
            identity=deterministic_identity(EntityKind.CHANGE_SET, f"change|{suffix}"),
            claim_kind=ClaimKind.OBSERVED,
            subject=deterministic_identity(EntityKind.REPOSITORY_SNAPSHOT, f"snap|{suffix}"),
            payload={"files": list(files)},
            observed_at=at,
            episode=episode,
            source="test",
        ),
        project=project,
        observation_type=ObservationType.REPOSITORY_CHANGE,
        layer=ObservationLayer.RAW,
        provider="test",
        provider_event_id=str(suffix),
    )


def verify_env(files, passed, at, *, episode=None, suffix=None):
    _counter[0] += 1
    suffix = suffix or _counter[0]
    return ObservationEnvelope(
        observation=Observation(
            identity=deterministic_identity(EntityKind.VERIFICATION_RUN, f"verify|{suffix}"),
            claim_kind=ClaimKind.OBSERVED,
            subject=deterministic_identity(EntityKind.CHANGE_SET, f"verify-subject|{suffix}"),
            payload={"files": list(files), "passed": passed},
            observed_at=at,
            episode=episode,
            source="test",
        ),
        project=PROJECT_ALPHA,
        observation_type=ObservationType.VERIFICATION,
        layer=ObservationLayer.NORMALIZED,
        provider="test",
        provider_event_id=str(suffix),
    )


def prompt_env(at, *, episode=None, suffix=None):
    _counter[0] += 1
    suffix = suffix or _counter[0]
    stable = f"prompt|{suffix}"
    return ObservationEnvelope(
        observation=Observation(
            identity=deterministic_identity(EntityKind.PROMPT_RUN, stable),
            claim_kind=ClaimKind.OBSERVED,
            subject=deterministic_identity(EntityKind.PROMPT_VERSION, stable),
            payload={},
            observed_at=at,
            episode=episode,
            source="test",
        ),
        project=PROJECT_ALPHA,
        observation_type=ObservationType.PROMPT,
        layer=ObservationLayer.NORMALIZED,
        provider="test",
        provider_event_id=stable,
        attributes={"occurrence_only": True},
    )


def fixture_state():
    snapshot = RepositorySnapshot(
        files={
            "src/auth/__init__.py": "a" * 64,
            "src/auth/session.py": "b" * 64,
            "tests/test_session.py": "c" * 64,
        }
    )
    refs = bootstrap_entity_refs(PROJECT_ALPHA, "alpha", snapshot, now=NOW - 3 * D)
    shared = deterministic_identity(EntityKind.EPISODE, "ep-1")
    envelopes = [
        change_env(("src/auth/session.py",), NOW - D, episode=shared, suffix="g1"),
        verify_env(("src/auth/session.py",), False, NOW - D + timedelta(hours=1), suffix="g2"),
        prompt_env(NOW - D, episode=shared, suffix="g3"),
        verify_env(("tests/test_session.py",), True, NOW - timedelta(hours=2), suffix="g4"),
    ]
    joined = join_evidence(envelopes, PROJECT_ALPHA, window_start=WINDOW_START, window_end=WINDOW_END)
    signals = scan_signals(
        PROJECT_ALPHA,
        "alpha",
        envelopes=envelopes,
        refs_by_path=index_refs_by_path(refs.values()),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        now=NOW,
        memory_status=InternalAnswerStatus.ABSENT,
    )
    return refs, joined, signals


class BuildTests(unittest.TestCase):
    def test_rebuild_is_deterministic(self):
        refs, joined, signals = fixture_state()
        first = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, signals=signals.signals, now=NOW
        )
        second = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, signals=signals.signals, now=NOW
        )
        self.assertEqual(first.generation, second.generation)
        self.assertEqual(
            [n.identity for n in first.nodes], [n.identity for n in second.nodes]
        )
        self.assertEqual(
            [(l.relation.value, l.source, l.target) for l in first.links],
            [(l.relation.value, l.source, l.target) for l in second.links],
        )
        self.assertTrue(validate_overlay(first).ok, validate_overlay(first).violations)

    def test_node_families_and_federation_anchors(self):
        refs, joined, signals = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA,
            "alpha",
            entity_refs=refs.values(),
            joined=joined,
            signals=signals.signals,
            memory_refs=(ExternalReference(provider="memory", kind="record", value="r1#rev2"),),
            now=NOW,
        )
        families = {node.family for node in graph.nodes}
        self.assertIn(NodeFamily.REPOSITORY_STRUCTURE, families)
        self.assertIn(NodeFamily.PERFORMANCE_EVIDENCE, families)
        self.assertIn(NodeFamily.CONCEPT, families)
        self.assertIn(NodeFamily.INTELLIGENCE, families)
        self.assertIn(NodeFamily.MEMORY_REFERENCE, families)
        memory_node = next(
            node
            for node in graph.nodes
            if node.family is NodeFamily.MEMORY_REFERENCE
        )
        self.assertEqual(
            memory_node.identity,
            memory_ref_identity(
                PROJECT_ALPHA, ExternalReference(provider="memory", kind="record", value="r1#rev2")
            ).canonical,
        )
        self.assertIn("Midnight Memory owns the record", " ".join(memory_node.provenance))

    def test_structure_contains_hierarchy_from_paths(self):
        refs, joined, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, now=NOW
        )
        contains = [
            (l.source, l.target) for l in graph.links if l.relation is GraphRelation.CONTAINS
        ]
        labels = {n.identity: n.label for n in graph.nodes}
        by_label = {v: k for k, v in labels.items()}
        repo = by_label["alpha"]
        package = by_label["src/auth"]
        module = by_label["src/auth/session.py"]
        test = by_label["tests/test_session.py"]
        self.assertIn((repo, package), contains)
        self.assertIn((package, module), contains)
        self.assertIn((repo, test), contains)

    def test_event_edges_separate_verified_failed_and_discussed(self):
        refs, joined, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, now=NOW
        )
        relations = [l.relation for l in graph.links]
        self.assertIn(GraphRelation.CHANGED_IN, relations)
        self.assertIn(GraphRelation.FAILED_IN, relations)
        self.assertIn(GraphRelation.VERIFIED_BY, relations)
        self.assertIn(GraphRelation.DISCUSSED_IN, relations)
        failed = next(l for l in graph.links if l.relation is GraphRelation.FAILED_IN)
        self.assertFalse(failed.is_stale(NOW))

    def test_intent_edges_carry_occurrence_not_content_uncertainty(self):
        refs, joined, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, now=NOW
        )
        discussed = next(l for l in graph.links if l.relation is GraphRelation.DISCUSSED_IN)
        self.assertIn("occurrence only", discussed.uncertainty)

    def test_concept_about_edges_are_derived_deterministically(self):
        refs, joined, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, now=NOW
        )
        about = [l for l in graph.links if l.relation is GraphRelation.ABOUT]
        self.assertTrue(about)
        concept_labels = {
            n.label
            for n in graph.nodes
            if n.family is NodeFamily.CONCEPT and n.concept_role is ConceptRole.CONCEPT
        }
        self.assertIn(abstract_concept("src/auth/session.py", repository_key="alpha"), concept_labels)
        for link in about:
            self.assertEqual(link.edge_class, EdgeClass.STRUCTURAL)
            self.assertIn("token abstraction", link.uncertainty)

    def test_custom_concept_roles_are_supported(self):
        refs, _, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA,
            "alpha",
            entity_refs=refs.values(),
            concept_specs=(("token expiry drift", ConceptRole.FAILURE_MODE),),
            now=NOW,
        )
        roles = {n.concept_role for n in graph.nodes if n.family is NodeFamily.CONCEPT}
        self.assertIn(ConceptRole.FAILURE_MODE, roles)

    def test_external_reference_nodes_carry_trust_provenance(self):
        refs, _, _ = fixture_state()
        from midnight_performance.repo_intelligence.contracts import ExternalSourceRef, external_source_ref_identity

        digest = "e" * 64
        external = ExternalSourceRef(
            identity=external_source_ref_identity("vendor", "https://docs.example.com/x", digest),
            project=PROJECT_ALPHA,
            source_class=__import__(
                "midnight_performance.repo_intelligence.sources", fromlist=["SourceClass"]
            ).SourceClass.OFFICIAL_DOCS,
            provider="vendor",
            locator="https://docs.example.com/x",
            title="Session handling guide",
            content_digest=digest,
            captured_at=NOW - D,
            retrieval_method="fixture",
            retrieval_version="1",
        )
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), external_refs=(external,), now=NOW
        )
        external_nodes = [n for n in graph.nodes if n.family is NodeFamily.EXTERNAL_KNOWLEDGE]
        self.assertEqual(len(external_nodes), 1)
        self.assertIn("trust vendor_authoritative", " ".join(external_nodes[0].provenance))
        self.assertIn("untrusted evidence", " ".join(external_nodes[0].provenance))


class FederationTests(unittest.TestCase):
    def test_insight_edges_derive_support_and_supersede(self):
        from midnight_performance.repo_intelligence.contracts import (
            ProjectInsight,
            LineageReceipt,
            lineage_receipt_identity,
            project_insight_identity,
        )
        from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind

        items = (
            EvidenceItem(
                ref=deterministic_identity(EntityKind.PROMPT_RUN, "sup-1").canonical,
                source_class=__import__(
                    "midnight_performance.repo_intelligence.sources", fromlist=["SourceClass"]
                ).SourceClass.PERFORMANCE_EVIDENCE,
                trust_class=__import__(
                    "midnight_performance.repo_intelligence.sources", fromlist=["TrustClass"]
                ).TrustClass.FIRST_PARTY_LOCAL,
                captured_at=NOW - D,
            ),
        )
        bundle = EvidenceBundle(
            identity=evidence_bundle_identity(PROJECT_ALPHA, items),
            project=PROJECT_ALPHA,
            items=items,
            created_at=NOW - D,
        )
        statement = "session refresh fails repeatedly under expired tokens"
        receipt = LineageReceipt(
            identity=lineage_receipt_identity(
                PROJECT_ALPHA, "synth", "1", NOW - D, NOW, items[0].ref and (items[0].ref,), (), ()
            ),
            project=PROJECT_ALPHA,
            derivation_method="synth",
            derivation_version="1",
            window_start=NOW - D,
            window_end=NOW,
            claim_kind=ClaimKind.DERIVED,
            privacy_decision="local_only",
            created_at=NOW,
            performance_evidence_ids=(items[0].ref,),
        )
        insight = ProjectInsight(
            identity=project_insight_identity(PROJECT_ALPHA, bundle.identity, "synth", "1", statement),
            project=PROJECT_ALPHA,
            statement=statement,
            claim_kind=ClaimKind.INFERRED,
            method="synth",
            method_version="1",
            uncertainty="inferred",
            evidence_bundle=bundle.identity,
            confidence=0.6,
            lineage_receipt=receipt.identity,
            valid_from=NOW - D,
        )
        refs, _, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA,
            "alpha",
            entity_refs=refs.values(),
            insights=((insight, bundle),),
            now=NOW,
        )
        relations = [l.relation for l in graph.links]
        self.assertIn(GraphRelation.DERIVED_FROM, relations)
        self.assertIn(GraphRelation.SUPPORTED_BY, relations)
        for link in graph.links:
            self.assertIsNotNone(graph.node(link.source), link.source)
            self.assertIsNotNone(graph.node(link.target), link.target)

    def test_question_and_exposure_and_outcome_edges(self):
        from midnight_performance.repo_intelligence.contracts import (
            AssociationKind,
            BudgetCeiling,
            InternalSignal,
            LearningOutcome,
            LineageReceipt,
            lineage_receipt_identity,
            new_event_identity,
        )
        from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind

        concept = "auth session"
        question = ResearchQuestion(
            identity=research_question_identity(PROJECT_ALPHA, f"verification_failure|{concept}"),
            project=PROJECT_ALPHA,
            question_text=f"what are reliable patterns to prevent recurring failures in {concept}",
            privacy_minimized=True,
            why_now="repeated failures",
            triggered_by=(
                deterministic_repo_identity(
                    RepoIntelligenceKind.INTERNAL_SIGNAL, "q-trigger"
                ).canonical,
            ),
            what_is_already_known="known",
            what_is_unknown="unknown",
            what_external_evidence_would_change="authoritative pattern",
            stop_condition="stop",
            budget=BudgetCeiling(max_model_calls=1),
            internal_answer_status=InternalAnswerStatus.ABSENT,
            dedup_key=f"verification_failure|{concept}",
            status=__import__(
                "midnight_performance.repo_intelligence.contracts", fromlist=["QuestionStatus"]
            ).QuestionStatus.OPEN,
            created_at=NOW - D,
        )
        insight_identity = deterministic_repo_identity(
            RepoIntelligenceKind.PROJECT_INSIGHT, "exp-insight"
        )
        exposure = Exposure(
            identity=new_event_identity(RepoIntelligenceKind.EXPOSURE),
            project=PROJECT_ALPHA,
            insight=insight_identity,
            channel=ExposureChannel.PROACTIVE_PUSH,
            outcome=ExposureOutcome.OFFERED,
            surface="terminal",
            occurred_at=NOW - timedelta(hours=12),
            relevance_justification="the user would lose the failure explanation",
        )
        outcome = LearningOutcome(
            identity=deterministic_repo_identity(RepoIntelligenceKind.LEARNING_OUTCOME, "outcome-1"),
            project=PROJECT_ALPHA,
            exposure=exposure.identity,
            insight=insight_identity,
            association=AssociationKind.POSITIVE_ASSOCIATION,
            claim_kind=ClaimKind.STATISTICAL,
            method="assoc",
            method_version="1",
            uncertainty="association is not causality",
            window_start=NOW - timedelta(hours=12),
            window_end=NOW,
            created_at=NOW,
        )
        refs, _, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA,
            "alpha",
            entity_refs=refs.values(),
            questions=(question,),
            exposures=(exposure,),
            outcomes=(outcome,),
            now=NOW,
        )
        relations = [l.relation for l in graph.links]
        self.assertIn(GraphRelation.RELEVANT_TO, relations)
        self.assertIn(GraphRelation.EXPOSED_AS, relations)
        self.assertIn(GraphRelation.LEARNED_FROM, relations)
        learned = next(l for l in graph.links if l.relation is GraphRelation.LEARNED_FROM)
        self.assertIn("not causality", learned.uncertainty)

    def test_cross_project_records_fail_closed(self):
        refs_beta = bootstrap_entity_refs(PROJECT_BETA, "beta", RepositorySnapshot(files={"b.py": "a" * 64}), now=NOW)
        with self.assertRaises(CrossProjectAccessError):
            build_project_graph(PROJECT_ALPHA, "alpha", entity_refs=refs_beta.values(), now=NOW)

    def test_extra_semantic_links_are_validated_and_project_bound(self):
        refs, _, _ = fixture_state()
        labels = {n.label: n.identity for n in build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), now=NOW
        ).nodes}
        a = labels["src/auth/session.py"]
        b = labels["tests/test_session.py"]
        semantic = GraphLink(
            identity=deterministic_repo_identity(
                __import__("midnight_performance.repo_intelligence.identities", fromlist=["RepoIntelligenceKind"]).RepoIntelligenceKind.GRAPH_LINK,
                "semantic-similar-1",
            ),
            project=PROJECT_ALPHA,
            source=a,
            target=b,
            relation=GraphRelation.SIMILAR_TO,
            edge_class=EdgeClass.SEMANTIC,
            claim_kind=ClaimKind.INFERRED,
            method="model-x",
            method_version="1",
            uncertainty="model-scored similarity, probabilistic",
            evidence_ids=(a,),
            first_seen=NOW,
            last_seen=NOW,
            confidence=0.7,
        )
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), extra_links=(semantic,), now=NOW
        )
        self.assertIn(GraphRelation.SIMILAR_TO, [l.relation for l in graph.links])
        cross = GraphLink(
            identity=deterministic_repo_identity(
                __import__("midnight_performance.repo_intelligence.identities", fromlist=["RepoIntelligenceKind"]).RepoIntelligenceKind.GRAPH_LINK,
                "cross-1",
            ),
            project=PROJECT_BETA,
            source=a,
            target=b,
            relation=GraphRelation.RELATED_TO,
            edge_class=EdgeClass.STRUCTURAL,
            claim_kind=ClaimKind.DERIVED,
            method="m",
            method_version="1",
            uncertainty="u",
            evidence_ids=(a,),
            first_seen=NOW,
            last_seen=NOW,
        )
        with self.assertRaises(CrossProjectAccessError):
            build_project_graph(
                PROJECT_ALPHA, "alpha", entity_refs=refs.values(), extra_links=(cross,), now=NOW
            )


class IncrementalTests(unittest.TestCase):
    def test_incremental_update_equals_full_rebuild_and_preserves_untouched(self):
        refs, joined, signals = fixture_state()
        full_before = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, signals=signals.signals, now=NOW
        )
        later = NOW + D
        envelopes_later = [
            change_env(("src/auth/session.py",), NOW - D, suffix="g1b"),
            verify_env(("src/auth/session.py",), False, NOW - D + timedelta(hours=1), suffix="g2b"),
            change_env(("src/auth/session.py", "tests/test_session.py"), later - timedelta(hours=1), suffix="inc-1"),
        ]
        joined_later = join_evidence(
            envelopes_later,
            PROJECT_ALPHA,
            window_start=later - 14 * D,
            window_end=later,
        )
        full_after = build_project_graph(
            PROJECT_ALPHA,
            "alpha",
            entity_refs=refs.values(),
            joined=joined_later,
            signals=signals.signals,
            now=later,
        )
        updated = update_project_graph(
            full_before,
            PROJECT_ALPHA,
            "alpha",
            changed_paths=frozenset({"src/auth/session.py"}),
            now=later,
            entity_refs=refs.values(),
            joined=joined_later,
            signals=signals.signals,
        )
        self.assertTrue(validate_overlay(updated).ok, validate_overlay(updated).violations)
        self.assertEqual(
            {(l.relation.value, l.source, l.target) for l in updated.links},
            {(l.relation.value, l.source, l.target) for l in full_after.links},
        )

    def test_no_changed_paths_returns_full_rebuild(self):
        refs, joined, signals = fixture_state()
        previous = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, signals=signals.signals, now=NOW
        )
        updated = update_project_graph(
            previous,
            PROJECT_ALPHA,
            "alpha",
            changed_paths=frozenset(),
            now=NOW,
            entity_refs=refs.values(),
            joined=joined,
            signals=signals.signals,
        )
        self.assertEqual(updated.generation, previous.generation)

    def test_cross_project_update_fails_closed(self):
        refs, joined, _ = fixture_state()
        previous = build_project_graph(PROJECT_ALPHA, "alpha", entity_refs=refs.values(), now=NOW)
        with self.assertRaises(CrossProjectAccessError):
            update_project_graph(
                previous,
                PROJECT_BETA,
                "alpha",
                changed_paths=frozenset({"src/auth/session.py"}),
                now=NOW,
                entity_refs=refs.values(),
                joined=joined,
            )


class TemporalTests(unittest.TestCase):
    def test_stale_links_decay_and_active_links_preserve(self):
        refs, joined, _ = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, now=NOW
        )
        self.assertEqual(len(active_links(graph, NOW)), len(graph.links))
        self.assertEqual(stale_links(graph, NOW), ())
        expired = NOW + 400 * D
        self.assertEqual(len(active_links(graph, expired)), len(graph.links))
        self.assertEqual(stale_links(graph, expired), ())


class DocumentTests(unittest.TestCase):
    def test_to_document_is_json_serializable_and_deterministic(self):
        import json

        refs, joined, signals = fixture_state()
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, signals=signals.signals, now=NOW
        )
        document = graph.to_document()
        serialized = json.dumps(document, sort_keys=True)
        self.assertIn(document["generation"], serialized)
        self.assertEqual(document["schema_version"], 1)
        again = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=refs.values(), joined=joined, signals=signals.signals, now=NOW
        )
        self.assertEqual(json.dumps(again.to_document(), sort_keys=True), serialized)


class AnalogyOverlayTests(unittest.TestCase):
    """Execution RI-14: analogy nodes, EXTERNAL_ANALOGUE_OF edges, and preserved contradictions."""

    def _internal_ref(self):
        from midnight_performance.repo_intelligence.contracts import (
            ProjectEntityRef,
            ProjectEntityRefKind,
            project_entity_ref_identity,
        )

        return ProjectEntityRef(
            identity=project_entity_ref_identity("alpha", ProjectEntityRefKind.MODULE, "src/queue.py", None, "resolver", "1"),
            project=PROJECT_ALPHA, ref_kind=ProjectEntityRefKind.MODULE, repository_key="alpha",
            resolver_tool="resolver", resolver_version="1", first_seen_at=NOW, last_seen_at=NOW, path="src/queue.py",
        )

    def _external(self, locator):
        from midnight_performance.repo_intelligence.contracts import ExternalSourceRef, external_source_ref_identity
        from midnight_performance.repo_intelligence.sources import SourceClass

        digest = "a" * 64
        return ExternalSourceRef(
            identity=external_source_ref_identity("github", locator, digest),
            project=PROJECT_ALPHA, source_class=SourceClass.GITHUB_REPOSITORY, provider="github",
            locator=locator, title=locator, content_digest=digest, captured_at=NOW,
            retrieval_method="fetch", retrieval_version="1",
        )

    def _record(self, external, profile):
        from midnight_performance.repo_intelligence.analogy import RepositoryProfile, build_analogy_record
        from midnight_performance.repo_intelligence.sources import Freshness

        internal_ref = self._internal_ref()
        internal_profile = RepositoryProfile(
            architectural_role="message-queue-consumer", language="python", evidence_ids=(internal_ref.identity.canonical,),
        )
        return build_analogy_record(
            PROJECT_ALPHA, external, internal_ref, internal_profile, profile,
            why_it_matters_now="test", meaningful_differences=("different language",), freshness=Freshness(captured_at=NOW), now=NOW,
        )

    def test_analogy_node_links_to_internal_and_external_endpoints(self):
        from midnight_performance.repo_intelligence.analogy import RepositoryProfile

        external = self._external("org/first")
        record = self._record(external, RepositoryProfile(architectural_role="message-queue-consumer", language="go", evidence_ids=(external.identity.canonical,)))
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=(self._internal_ref(),), external_refs=(external,),
            analogies=(record,), now=NOW,
        )
        self.assertTrue(validate_overlay(graph).ok, validate_overlay(graph).violations)
        relations = {l.relation for l in graph.links}
        self.assertIn(GraphRelation.EXTERNAL_ANALOGUE_OF, relations)
        analogy_edges = [l for l in graph.links if l.relation is GraphRelation.EXTERNAL_ANALOGUE_OF]
        self.assertEqual(len(analogy_edges), 2)  # internal -> analogy, analogy -> external

    def test_divergent_analogies_for_the_same_entity_are_linked_contradicts_not_deleted(self):
        from midnight_performance.repo_intelligence.analogy import RepositoryProfile

        similar_external = self._external("org/similar")
        dissimilar_external = self._external("org/dissimilar")
        similar = self._record(similar_external, RepositoryProfile(architectural_role="message-queue-consumer", language="go", evidence_ids=(similar_external.identity.canonical,)))
        dissimilar = self._record(dissimilar_external, RepositoryProfile(architectural_role="static-site-generator", language="rust", evidence_ids=(dissimilar_external.identity.canonical,)))
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=(self._internal_ref(),), external_refs=(similar_external, dissimilar_external),
            analogies=(similar, dissimilar), now=NOW,
        )
        self.assertTrue(validate_overlay(graph).ok, validate_overlay(graph).violations)
        contradicts = [l for l in graph.links if l.relation is GraphRelation.CONTRADICTS]
        self.assertEqual(len(contradicts), 1)
        # both analogy nodes remain in the overlay -- neither historical verdict was deleted
        self.assertIsNotNone(graph.node(similar.identity.canonical))
        self.assertIsNotNone(graph.node(dissimilar.identity.canonical))

    def test_agreeing_analogies_do_not_contradict(self):
        from midnight_performance.repo_intelligence.analogy import RepositoryProfile

        first_external = self._external("org/agree-one")
        second_external = self._external("org/agree-two")
        agreeing_profile = RepositoryProfile(architectural_role="message-queue-consumer", language="go", evidence_ids=(first_external.identity.canonical,))
        first = self._record(first_external, agreeing_profile)
        second = self._record(second_external, RepositoryProfile(architectural_role="message-queue-consumer", language="rust", evidence_ids=(second_external.identity.canonical,)))
        graph = build_project_graph(
            PROJECT_ALPHA, "alpha", entity_refs=(self._internal_ref(),), external_refs=(first_external, second_external),
            analogies=(first, second), now=NOW,
        )
        contradicts = [l for l in graph.links if l.relation is GraphRelation.CONTRADICTS]
        self.assertEqual(contradicts, [])


if __name__ == "__main__":
    unittest.main()
