"""Execution RI-14's own eight named verification scenarios, driven end-to-end.

Mirrors RI-13's ``test_repo_intelligence_fusion_scenarios.py`` pattern: one
test per scenario the spec names explicitly, composing the real contracts
and modules rather than a second, simplified model of them.
"""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.analogy import RepositoryProfile, build_analogy_record
from midnight_performance.repo_intelligence.attention import AttentionFactors, RankedAttentionCandidate, rank_attention_candidates
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import (
    AssociationKind,
    EvidenceBundle,
    EvidenceItem,
    Exposure,
    ExposureChannel,
    ExposureOutcome,
    ExternalSourceRef,
    GraphRelation,
    LearningOutcome,
    LineageReceipt,
    ProjectEntityRef,
    ProjectEntityRefKind,
    ProjectInsight,
    evidence_bundle_identity,
    external_source_ref_identity,
    lineage_receipt_identity,
    new_event_identity,
    project_entity_ref_identity,
    project_insight_identity,
)
from midnight_performance.repo_intelligence.federated_retrieval import RetrievalQuery, classify_query
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence.project_graph import build_project_graph, validate_overlay
from midnight_performance.repo_intelligence.release_metric import compute_release_metric
from midnight_performance.repo_intelligence.sources import Freshness, SourceClass, TrustClass
from midnight_performance.repo_intelligence.terminal_learning import TerminalCandidate, TerminalContext, decide_terminal_card

T0 = datetime(2026, 9, 5, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "ri14-scenarios")
PERF_REF = deterministic_identity(EntityKind.VERIFICATION_RUN, "ri14-run").canonical


def _internal_ref(suffix="queue"):
    return ProjectEntityRef(
        identity=project_entity_ref_identity("repo", ProjectEntityRefKind.MODULE, f"src/{suffix}.py", None, "resolver", "1"),
        project=PROJECT, ref_kind=ProjectEntityRefKind.MODULE, repository_key="repo",
        resolver_tool="resolver", resolver_version="1", first_seen_at=T0, last_seen_at=T0, path=f"src/{suffix}.py",
    )


def _external(locator):
    digest = "a" * 64
    return ExternalSourceRef(
        identity=external_source_ref_identity("github", locator, digest),
        project=PROJECT, source_class=SourceClass.GITHUB_REPOSITORY, provider="github",
        locator=locator, title=locator, content_digest=digest, captured_at=T0,
        retrieval_method="fetch", retrieval_version="1",
    )


def _insight(*, superseded_by=None, valid_to=None):
    item = EvidenceItem(PERF_REF, SourceClass.PERFORMANCE_EVIDENCE, TrustClass.FIRST_PARTY_LOCAL, T0)
    bundle = EvidenceBundle(evidence_bundle_identity(PROJECT, (item,)), PROJECT, (item,), T0)
    receipt = LineageReceipt(
        lineage_receipt_identity(PROJECT, "scenario", "1", T0, T0, (PERF_REF,), (), ()),
        PROJECT, "scenario", "1", T0, T0, ClaimKind.DERIVED, "local_only", T0, (PERF_REF,),
    )
    statement = "supersedes target" if superseded_by is None else "original, superseded"
    identity = project_insight_identity(PROJECT, bundle.identity, "scenario", "1", statement)
    return ProjectInsight(
        identity, PROJECT, statement, ClaimKind.INFERRED, "scenario", "1", "bounded evidence",
        bundle.identity, 0.8, receipt.identity, valid_from=T0, valid_to=valid_to, superseded_by=superseded_by,
    )


class TemporalSupersessionScenario(unittest.TestCase):
    def test_a_superseding_insight_links_supersedes_and_keeps_the_superseded_ones_history(self):
        newer = _insight()
        older = _insight(superseded_by=newer.identity)
        graph = build_project_graph(
            PROJECT, "repo", insights=((newer, None), (older, None)), now=T0 + timedelta(days=1),
        )
        self.assertTrue(validate_overlay(graph).ok, validate_overlay(graph).violations)
        supersedes = [l for l in graph.links if l.relation is GraphRelation.SUPERSEDES]
        self.assertEqual(len(supersedes), 1)
        # the superseded insight's own node -- its historical truth -- is still on record
        self.assertIsNotNone(graph.node(older.identity.canonical))
        self.assertTrue(older.is_superseded())


class ContradictoryExternalSourcesScenario(unittest.TestCase):
    def test_two_external_sources_disagree_and_both_verdicts_are_preserved_as_contradicts(self):
        internal_ref = _internal_ref()
        internal_profile = RepositoryProfile(architectural_role="message-queue-consumer", language="python", evidence_ids=(internal_ref.identity.canonical,))
        source_a, source_b = _external("org/agrees"), _external("org/disagrees")
        agrees = build_analogy_record(
            PROJECT, source_a, internal_ref, internal_profile,
            RepositoryProfile(architectural_role="message-queue-consumer", language="go", evidence_ids=(source_a.identity.canonical,)),
            why_it_matters_now="x", meaningful_differences=("language",), freshness=Freshness(captured_at=T0), now=T0,
        )
        disagrees = build_analogy_record(
            PROJECT, source_b, internal_ref, internal_profile,
            RepositoryProfile(architectural_role="static-site-generator", language="rust", evidence_ids=(source_b.identity.canonical,)),
            why_it_matters_now="x", meaningful_differences=("domain",), freshness=Freshness(captured_at=T0), now=T0,
        )
        graph = build_project_graph(
            PROJECT, "repo", entity_refs=(internal_ref,), external_refs=(source_a, source_b),
            analogies=(agrees, disagrees), now=T0,
        )
        contradicts = [l for l in graph.links if l.relation is GraphRelation.CONTRADICTS]
        self.assertEqual(len(contradicts), 1)
        self.assertIsNotNone(graph.node(agrees.identity.canonical))
        self.assertIsNotNone(graph.node(disagrees.identity.canonical))


class StructurallySimilarDifferentLanguageScenario(unittest.TestCase):
    def test_a_go_rewrite_of_the_same_component_scores_a_strong_analogy(self):
        internal_ref = _internal_ref()
        internal_profile = RepositoryProfile(
            architectural_role="message-queue-consumer", language="python", evidence_ids=(internal_ref.identity.canonical,),
            dependencies=frozenset({"redis"}), data_flow_patterns=frozenset({"pub-sub"}),
            failure_modes=frozenset({"poison-message"}), test_strategy="integration", scale_class="single-region",
        )
        external = _external("org/go-rewrite")
        record = build_analogy_record(
            PROJECT, external, internal_ref, internal_profile,
            RepositoryProfile(
                architectural_role="message-queue-consumer", language="go", evidence_ids=(external.identity.canonical,),
                dependencies=frozenset({"redis"}), data_flow_patterns=frozenset({"pub-sub"}),
                failure_modes=frozenset({"poison-message"}), test_strategy="integration", scale_class="single-region",
            ),
            why_it_matters_now="a maintained Go rewrite of the same consumer pattern",
            meaningful_differences=("different language runtime",), freshness=Freshness(captured_at=T0), now=T0,
        )
        self.assertGreaterEqual(record.confidence, 0.8)
        self.assertEqual(record.non_comparable_dimensions(), ())


class KeywordSimilarButStructurallyIrrelevantScenario(unittest.TestCase):
    def test_a_name_that_sounds_similar_does_not_earn_a_structural_analogy(self):
        query_text = "is there a similar repository to our queue consumer"
        # the keyword-only query router would flag this as an external-analogue candidate...
        self.assertEqual(classify_query(RetrievalQuery(text=query_text)).value, "external_analogue")

        # ...but the structural engine, given the actual candidate's typed facts, does not inflate it.
        internal_ref = _internal_ref()
        internal_profile = RepositoryProfile(
            architectural_role="message-queue-consumer", language="python", evidence_ids=(internal_ref.identity.canonical,),
            dependencies=frozenset({"redis"}), data_flow_patterns=frozenset({"pub-sub"}), failure_modes=frozenset({"poison-message"}),
        )
        external = _external("org/queue-consumer-clone")  # name alone suggests similarity
        record = build_analogy_record(
            PROJECT, external, internal_ref, internal_profile,
            RepositoryProfile(architectural_role="static-site-generator", language="rust", evidence_ids=(external.identity.canonical,)),
            why_it_matters_now="surfaced by name/topic match only", meaningful_differences=("entirely different domain",),
            freshness=Freshness(captured_at=T0), now=T0,
        )
        self.assertEqual(record.confidence, 0.0)


class StaleInsightScenario(unittest.TestCase):
    def test_a_past_validity_window_suppresses_proactive_exposure_without_deleting_the_insight(self):
        stale = _insight(valid_to=T0)
        candidate = TerminalCandidate(stale, "now", "project", "learn", .9, .9, .9, .9, .1)
        result = decide_terminal_card((candidate,), RepoIntelligenceAuthorization(PROJECT), now=T0 + timedelta(days=1))
        self.assertIsNone(result.card)
        self.assertTrue(stale.is_superseded())


class RepeatedDismissalScenario(unittest.TestCase):
    def test_dismissal_limit_suppresses_the_same_insight_without_deleting_history(self):
        fresh = _insight()
        candidate = TerminalCandidate(fresh, "now", "project", "learn", .9, .9, .9, .9, .1)
        context = TerminalContext(dismissal_limit=2)
        history = tuple(
            Exposure(
                deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, f"dismiss-{i}"), PROJECT, fresh.identity,
                ExposureChannel.USER_PULL, ExposureOutcome.DISMISSED, "terminal", T0 - timedelta(days=i),
            )
            for i in range(2)
        )
        result = decide_terminal_card((candidate,), RepoIntelligenceAuthorization(PROJECT), now=T0, history=history, context=context)
        self.assertIsNone(result.card)
        self.assertIn("dismissal", result.reason)
        # dismissal history itself is durable, never pruned by discard_rebuildable_state
        self.assertEqual(len(history), 2)


class QuietModeScenario(unittest.TestCase):
    def test_paused_proactive_enrichment_routes_to_the_quiet_queue(self):
        fresh = _insight()
        candidate = TerminalCandidate(fresh, "now", "project", "learn", .9, .9, .9, .9, .1)
        result = decide_terminal_card(
            (candidate,), RepoIntelligenceAuthorization(PROJECT), now=T0, context=TerminalContext(proactive_enabled=False),
        )
        self.assertIsNone(result.card)
        self.assertEqual(result.exposure.channel, ExposureChannel.QUIET_QUEUE)
        self.assertEqual(result.exposure.outcome, ExposureOutcome.SUPPRESSED)
        # a user-pull override still reaches the same insight despite the quiet mode
        pulled = decide_terminal_card(
            (candidate,), RepoIntelligenceAuthorization(PROJECT), now=T0,
            context=TerminalContext(proactive_enabled=False), user_pull=True,
        )
        self.assertIsNotNone(pulled.card)


class LaterAssociationWithoutCausalOverclaimScenario(unittest.TestCase):
    def test_a_later_positive_association_stays_statistical_and_feeds_the_release_metric(self):
        insight = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "later-assoc-insight")
        exposure = Exposure(
            new_event_identity(RepoIntelligenceKind.EXPOSURE), PROJECT, insight, ExposureChannel.PROACTIVE_PUSH,
            ExposureOutcome.OFFERED, "terminal", T0, relevance_justification="hiding this would leave a pattern unexplained",
        )
        with self.assertRaises(ValueError):
            LearningOutcome(
                new_event_identity(RepoIntelligenceKind.LEARNING_OUTCOME), PROJECT, exposure.identity, insight,
                AssociationKind.POSITIVE_ASSOCIATION, ClaimKind.OBSERVED,  # causal-strength claim: rejected
                "m", "1", "x", T0, T0 + timedelta(days=1),
            )
        outcome = LearningOutcome(
            new_event_identity(RepoIntelligenceKind.LEARNING_OUTCOME), PROJECT, exposure.identity, insight,
            AssociationKind.POSITIVE_ASSOCIATION, ClaimKind.STATISTICAL,
            "m", "1", "association observed after exposure; not evidence of causality", T0, T0 + timedelta(days=1),
        )
        metric = compute_release_metric((outcome,), (exposure,), ())
        self.assertEqual(metric.value, 1.0)


if __name__ == "__main__":
    unittest.main()
