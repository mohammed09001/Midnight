"""Execution RI-14: structural analogy comparison, never keyword-only similarity."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.analogy import RepositoryProfile, build_analogy_record, compare_repositories
from midnight_performance.repo_intelligence.contracts import (
    AnalogyDimension,
    DimensionComparison,
    ExternalSourceRef,
    ProjectEntityRef,
    ProjectEntityRefKind,
    external_source_ref_identity,
    project_entity_ref_identity,
)
from midnight_performance.repo_intelligence.sources import Freshness, SourceClass

T0 = datetime(2026, 9, 5, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "analogy-alpha")


def internal_ref(path="src/queue.py"):
    return ProjectEntityRef(
        identity=project_entity_ref_identity("repo", ProjectEntityRefKind.MODULE, path, None, "resolver", "1"),
        project=PROJECT, ref_kind=ProjectEntityRefKind.MODULE, repository_key="repo",
        resolver_tool="resolver", resolver_version="1", first_seen_at=T0, last_seen_at=T0, path=path,
    )


def external_source(locator="org/other-repo"):
    digest = "a" * 64
    return ExternalSourceRef(
        identity=external_source_ref_identity("github", locator, digest),
        project=PROJECT, source_class=SourceClass.GITHUB_REPOSITORY, provider="github",
        locator=locator, title=locator, content_digest=digest, captured_at=T0,
        retrieval_method="fetch", retrieval_version="1",
    )


INTERNAL_PROFILE = RepositoryProfile(
    architectural_role="message-queue-consumer", language="python",
    evidence_ids=(internal_ref().identity.canonical,),
    dependencies=frozenset({"redis", "celery"}), data_flow_patterns=frozenset({"pub-sub"}),
    failure_modes=frozenset({"poison-message"}), test_strategy="integration", scale_class="single-region",
)


def similar_external_profile():
    return RepositoryProfile(
        architectural_role="message-queue-consumer", language="go",
        evidence_ids=(external_source().identity.canonical,),
        dependencies=frozenset({"redis"}), data_flow_patterns=frozenset({"pub-sub"}),
        failure_modes=frozenset({"poison-message"}), test_strategy="integration", scale_class="multi-region",
    )


def bare_external_profile():
    """No structural facts at all beyond the required role/language -- an under-evidenced candidate."""
    return RepositoryProfile(architectural_role="static-site-generator", language="rust", evidence_ids=(external_source("org/bare-repo").identity.canonical,))


class CompareRepositoriesTests(unittest.TestCase):
    def test_covers_all_six_dimensions_every_time(self):
        comparisons = compare_repositories(INTERNAL_PROFILE, similar_external_profile())
        self.assertEqual({c.dimension for c in comparisons}, set(AnalogyDimension))

    def test_missing_facts_are_honestly_non_comparable_not_zero_similarity(self):
        comparisons = compare_repositories(INTERNAL_PROFILE, bare_external_profile())
        by_dim = {c.dimension: c for c in comparisons}
        self.assertFalse(by_dim[AnalogyDimension.TEST_STRATEGY].comparable)
        self.assertIsNone(by_dim[AnalogyDimension.TEST_STRATEGY].similarity)
        self.assertFalse(by_dim[AnalogyDimension.DEPENDENCY_PROTOCOL_OVERLAP].comparable)
        # the one dimension both sides always state is genuinely comparable, and honestly dissimilar
        self.assertTrue(by_dim[AnalogyDimension.ARCHITECTURAL_ROLE].comparable)
        self.assertEqual(by_dim[AnalogyDimension.ARCHITECTURAL_ROLE].similarity, 0.0)

    def test_engine_has_no_free_text_field_to_feed_keyword_similarity(self):
        # A RepositoryProfile literally cannot carry a description/README string;
        # nothing here can be fed keyword soup and asked "is this similar."
        self.assertNotIn("description", RepositoryProfile.__dataclass_fields__)
        self.assertNotIn("readme", RepositoryProfile.__dataclass_fields__)


class DimensionComparisonValidationTests(unittest.TestCase):
    def test_comparable_dimension_requires_similarity_and_evidence(self):
        with self.assertRaises(ValueError):
            DimensionComparison(AnalogyDimension.TEST_STRATEGY, True, None, "basis")
        with self.assertRaises(ValueError):
            DimensionComparison(AnalogyDimension.TEST_STRATEGY, True, 0.5, "basis", evidence_ids=())

    def test_non_comparable_dimension_rejects_similarity_score(self):
        with self.assertRaises(ValueError):
            DimensionComparison(AnalogyDimension.TEST_STRATEGY, False, 0.5, "basis")


class BuildAnalogyRecordTests(unittest.TestCase):
    def test_structurally_similar_repo_with_different_language_scores_high(self):
        record = build_analogy_record(
            PROJECT, external_source(), internal_ref(), INTERNAL_PROFILE, similar_external_profile(),
            why_it_matters_now="poison-message handling recurred this week",
            meaningful_differences=("different language runtime (go vs python)", "multi-region vs single-region"),
            freshness=Freshness(captured_at=T0, valid_to=T0 + timedelta(days=30)), now=T0,
        )
        self.assertGreater(record.confidence, 0.7)
        self.assertEqual(len(record.comparable_dimensions()), 6)
        self.assertEqual(record.non_comparable_dimensions(), ())

    def test_keyword_similar_but_structurally_irrelevant_repo_scores_low(self):
        record = build_analogy_record(
            PROJECT, external_source("org/bare-repo"), internal_ref(), INTERNAL_PROFILE, bare_external_profile(),
            why_it_matters_now="surfaced by a name/topic match worth checking",
            meaningful_differences=("entirely different domain and language",),
            freshness=Freshness(captured_at=T0), now=T0,
        )
        self.assertEqual(record.confidence, 0.0)
        self.assertEqual(len(record.non_comparable_dimensions()), 5)

    def test_requires_at_least_one_meaningful_difference(self):
        with self.assertRaises(ValueError):
            build_analogy_record(
                PROJECT, external_source(), internal_ref(), INTERNAL_PROFILE, similar_external_profile(),
                why_it_matters_now="x", meaningful_differences=(), freshness=Freshness(captured_at=T0), now=T0,
            )

    def test_stale_when_freshness_expires_or_superseded(self):
        record = build_analogy_record(
            PROJECT, external_source(), internal_ref(), INTERNAL_PROFILE, similar_external_profile(),
            why_it_matters_now="x", meaningful_differences=("y",),
            freshness=Freshness(captured_at=T0, valid_to=T0 + timedelta(days=1)), now=T0,
        )
        self.assertFalse(record.is_stale(T0))
        self.assertTrue(record.is_stale(T0 + timedelta(days=2)))

    def test_re_comparing_with_a_changed_verdict_yields_a_new_identity(self):
        same = build_analogy_record(
            PROJECT, external_source(), internal_ref(), INTERNAL_PROFILE, similar_external_profile(),
            why_it_matters_now="x", meaningful_differences=("y",), freshness=Freshness(captured_at=T0), now=T0,
        )
        again = build_analogy_record(
            PROJECT, external_source(), internal_ref(), INTERNAL_PROFILE, similar_external_profile(),
            why_it_matters_now="x", meaningful_differences=("y",), freshness=Freshness(captured_at=T0), now=T0,
        )
        self.assertEqual(same.identity, again.identity)  # idempotent rebuild, same facts
        changed = build_analogy_record(
            PROJECT, external_source(), internal_ref(), INTERNAL_PROFILE, bare_external_profile(),
            why_it_matters_now="x", meaningful_differences=("y",), freshness=Freshness(captured_at=T0), now=T0,
        )
        self.assertNotEqual(same.identity, changed.identity)  # different verdict, different record

    def test_round_trips_through_to_dict_from_dict(self):
        from midnight_performance.repo_intelligence.contracts import AnalogyRecord

        record = build_analogy_record(
            PROJECT, external_source(), internal_ref(), INTERNAL_PROFILE, similar_external_profile(),
            why_it_matters_now="x", meaningful_differences=("y",), freshness=Freshness(captured_at=T0), now=T0,
        )
        restored = AnalogyRecord.from_dict(record.to_dict())
        self.assertEqual(restored, record)


def _valid_comparisons():
    return compare_repositories(INTERNAL_PROFILE, similar_external_profile())


class AnalogyRecordValidationTests(unittest.TestCase):
    """Direct contract-level checks: a keyword-only "looks similar" can never satisfy this shape."""

    def _record(self, comparisons):
        from midnight_performance.repo_intelligence.contracts import AnalogyRecord, analogy_record_identity

        identity = analogy_record_identity(PROJECT, external_source().identity, internal_ref().identity, "m", "1", comparisons)
        return AnalogyRecord(
            identity=identity, project=PROJECT, external_repository=external_source().identity,
            internal_entity_ref=internal_ref().identity, comparisons=comparisons,
            meaningful_differences=("y",), confidence=0.5, why_it_matters_now="x",
            freshness=Freshness(captured_at=T0), method="m", method_version="1",
            evidence_ids=(external_source().identity.canonical,),
        )

    def test_missing_dimension_is_rejected(self):
        comparisons = tuple(c for c in _valid_comparisons() if c.dimension is not AnalogyDimension.TEST_STRATEGY)
        with self.assertRaises(ValueError):
            self._record(comparisons)

    def test_repeated_dimension_is_rejected(self):
        comparisons = _valid_comparisons() + (_valid_comparisons()[0],)
        with self.assertRaises(ValueError):
            self._record(comparisons)

    def test_all_non_comparable_dimensions_is_rejected(self):
        all_non_comparable = tuple(
            DimensionComparison(c.dimension, False, None, "not investigated") for c in _valid_comparisons()
        )
        with self.assertRaises(ValueError):
            self._record(all_non_comparable)


if __name__ == "__main__":
    unittest.main()
