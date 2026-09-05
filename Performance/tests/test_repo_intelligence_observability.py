"""Reproducible metrics, privacy-safe telemetry, comparisons, and release gating."""

import unittest
from datetime import datetime, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.observability import DatasetCategory, EvaluationCase, EvaluationVariant, OperationName, OperationRecord, RecordKind, VariantResult, derive_metrics, evaluate_release, rank_variants

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "observability-alpha")
AUTH = RepoIntelligenceAuthorization(PROJECT)

def event(operation, **attrs):
    return OperationRecord(PROJECT, operation, RecordKind.EVENT, T0, True, attributes=tuple(sorted(attrs.items())))

def corpus():
    return (
        event(OperationName.INSIGHT_GENERATION, accepted=True, unsupported=False, evidence_coverage=.9, provenance_accurate=True, internal_only=True),
        event(OperationName.FEEDBACK_OUTCOME, useful=True, time_to_useful_ms=100, later_positive_association=True),
        event(OperationName.EXPOSURE, duplicate=False),
        event(OperationName.EXTERNAL_SEARCH, search_results=4, search_selected=2, cost_micros=8),
        event(OperationName.CACHE_LOOKUP, cache_hit=True),
        event(OperationName.MODEL_CLASSIFICATION, strong_model=False, tokens=10),
        event(OperationName.SIGNAL_DETECTION, hotspot=True, hotspot_converted=True),
    )

class ObservabilityTests(unittest.TestCase):
    def test_metrics_are_reproducible_and_order_independent(self):
        first = derive_metrics(corpus(), AUTH)
        second = derive_metrics(tuple(reversed(corpus())), AUTH)
        self.assertEqual(first, second)
        self.assertEqual(first.insight_acceptance_rate, 1)
        self.assertEqual(first.external_search_yield, .5)
        self.assertEqual(first.cost_per_useful_insight_micros, 8)
        self.assertIn("never causal", first.association_disclosure)

    def test_quality_failure_blocks_release_even_when_computation_succeeds(self):
        bad = (event(OperationName.INSIGHT_GENERATION, accepted=True, unsupported=True, evidence_coverage=.2, provenance_accurate=False), event(OperationName.FEEDBACK_OUTCOME, useful=False))
        gate = evaluate_release(derive_metrics(bad, AUTH), bad)
        self.assertFalse(gate.passed)
        self.assertTrue(any("unsupported" in failure for failure in gate.failures))

    def test_missing_metrics_fail_closed(self):
        gate = evaluate_release(derive_metrics((), AUTH), ())
        self.assertFalse(gate.passed)
        self.assertIn("unmeasured", " ".join(gate.failures))

    def test_sensitive_or_verbose_telemetry_is_rejected(self):
        with self.assertRaises(ValueError):
            event(OperationName.FAILURE_DEGRADATION, failure_class="api_key=topsecret")
        with self.assertRaises(ValueError):
            event(OperationName.EXPOSURE, raw_prompt="do not record")

    def test_dataset_contract_covers_all_required_categories(self):
        cases = tuple(EvaluationCase(kind.value, kind, ("evidence:fixture",)) for kind in DatasetCategory)
        self.assertEqual({case.category for case in cases}, set(DatasetCategory))
        self.assertEqual(len(cases), 8)

    def test_variant_ranking_is_quality_first_and_stable(self):
        rows = (
            VariantResult(EvaluationVariant.LEXICAL_VECTOR, .6, .5, .4, 1, 10, 1),
            VariantResult(EvaluationVariant.FULL_ADAPTIVE, .9, .8, .8, 1, 50, 20),
            VariantResult(EvaluationVariant.INTERNAL_GRAPH, .7, .6, .5, 1, 20, 2),
            VariantResult(EvaluationVariant.INTERNAL_EXTERNAL, .8, .7, .7, 1, 30, 8),
        )
        self.assertEqual(rank_variants(rows)[0].variant, EvaluationVariant.FULL_ADAPTIVE)

if __name__ == "__main__": unittest.main()
