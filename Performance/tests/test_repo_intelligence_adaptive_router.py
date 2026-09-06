"""Adaptive cost-quality router (Repo Intelligent 02, Execution 05).

Verifies: the LIGHTWEIGHT_ML resolver tier and its routing_confidence
lightweight-ML bridge; quality floors (including the privacy-risk hard
override); the typed cascade outcome (ACCEPTED/ABSTAINED/BUDGET_INSUFFICIENT);
counterfactual-evidence tracking (OBSERVED-only from a real route() call,
REPLAYED from opt-in bounded_replay); the promotion gate's positive and
honest-negative paths; and provider neutrality.
"""

import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.cost_quality import (
    BudgetLedger,
    BudgetLimits,
    CounterfactualEvidenceStatus,
    MethodResult,
    MethodTier,
    QualityFloor,
    RouteOutcome,
    RouterReplayRecord,
    ScopedCaches,
    Spend,
    TaskProfile,
    WorkClass,
    bounded_replay,
    effective_quality_floor,
    evaluate_router_promotion,
    route,
    router_promotion_reason,
)
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence.lightweight_intelligence import (
    ROUTING_CONFIDENCE,
    DeterministicBaseline,
    ShadowModeGate,
    resolve_routing_confidence,
    routing_confidence_features,
)

T0 = datetime(2026, 9, 6, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "adaptive-router-alpha")
JOB = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB, "adaptive-router-job")


def profile(kind=WorkClass.CLASSIFICATION_RANKING, quality=0.5, uncertainty=0.5, privacy_risk=0.1):
    return TaskProfile(PROJECT, JOB, kind, "task", quality, uncertainty, 0.2, privacy_risk, 0.3, 100, "interactive", "evidence-v1")


def ledger(cost=10_000):
    return BudgetLedger(BudgetLimits(10, 10_000, 10_000, 1_000_000, 10_000, 2, 3, cost))


class FakePricedExecutor:
    def __init__(self, results):
        self.results, self.calls = results, []

    def estimate(self, tier, _profile):
        return self.results[tier].spend

    def execute(self, tier, _profile):
        self.calls.append(tier)
        return self.results[tier]


class LightweightMlTierTests(unittest.TestCase):
    def test_lightweight_ml_tier_is_reachable_in_the_classification_ladder(self):
        executor = FakePricedExecutor({
            MethodTier.DETERMINISTIC: MethodResult("weak", 0.1, 0.9, Spend(wall_time_ms=1)),
            MethodTier.LIGHTWEIGHT_ML: MethodResult("good", 0.9, 0.1, Spend(wall_time_ms=1)),
        })
        result = route(profile(), RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(), now=T0)
        self.assertEqual(executor.calls, [MethodTier.DETERMINISTIC, MethodTier.LIGHTWEIGHT_ML])
        self.assertEqual(result.accepted_tier, MethodTier.LIGHTWEIGHT_ML)
        self.assertEqual(result.costs[-1].resource.value, "local_compute")

    def test_deep_cross_source_reasoning_has_no_lightweight_ml_shortcut(self):
        """The one class whose whole point is full verification keeps no cheap rung."""
        executor = FakePricedExecutor({
            MethodTier.RETRIEVAL: MethodResult("weak", 0.1, 0.9, Spend(wall_time_ms=1)),
            MethodTier.SMALL_MODEL: MethodResult("weak", 0.1, 0.9, Spend(wall_time_ms=1)),
            MethodTier.EXTERNAL: MethodResult("weak", 0.1, 0.9, Spend(wall_time_ms=1)),
            MethodTier.STRONG_MODEL: MethodResult("good", 0.95, 0.05, Spend(wall_time_ms=1)),
        })
        result = route(
            profile(WorkClass.DEEP_CROSS_SOURCE_REASONING, quality=0.9, uncertainty=0.1),
            RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(), now=T0,
        )
        self.assertNotIn(MethodTier.LIGHTWEIGHT_ML, result.attempted_tiers)
        self.assertEqual(result.accepted_tier, MethodTier.STRONG_MODEL)


class QualityFloorTests(unittest.TestCase):
    def test_hard_floor_rejects_an_undersized_profile_at_construction(self):
        with self.assertRaises(ValueError):
            route(
                profile(WorkClass.BOUNDED_SYNTHESIS, quality=0.5, uncertainty=0.5),
                RepoIntelligenceAuthorization(PROJECT), FakePricedExecutor({}), ScopedCaches(PROJECT), ledger(), now=T0,
            )

    def test_bounded_synthesis_floor_is_hard_by_default(self):
        floor = effective_quality_floor(profile(WorkClass.BOUNDED_SYNTHESIS, quality=0.9, uncertainty=0.1))
        self.assertTrue(floor.hard)
        self.assertEqual(floor.minimum_quality, 0.8)

    def test_high_privacy_risk_forces_a_hard_floor_on_an_otherwise_soft_class(self):
        soft_floor = effective_quality_floor(profile(WorkClass.CLASSIFICATION_RANKING, privacy_risk=0.1))
        self.assertFalse(soft_floor.hard)
        hardened = effective_quality_floor(profile(WorkClass.CLASSIFICATION_RANKING, privacy_risk=0.9))
        self.assertTrue(hardened.hard)
        self.assertGreaterEqual(hardened.minimum_quality, 0.9)
        with self.assertRaises(ValueError):
            route(
                profile(WorkClass.CLASSIFICATION_RANKING, quality=0.5, uncertainty=0.5, privacy_risk=0.9),
                RepoIntelligenceAuthorization(PROJECT), FakePricedExecutor({}), ScopedCaches(PROJECT), ledger(), now=T0,
            )


class RouteOutcomeTests(unittest.TestCase):
    def test_accepted_outcome(self):
        executor = FakePricedExecutor({MethodTier.DETERMINISTIC: MethodResult("ok", 1.0, 0.0, Spend(wall_time_ms=1))})
        result = route(
            profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(), now=T0,
        )
        self.assertEqual(result.outcome, RouteOutcome.ACCEPTED)

    def test_abstained_outcome_when_every_tier_runs_but_none_qualifies(self):
        executor = FakePricedExecutor({
            MethodTier.RETRIEVAL: MethodResult("weak", 0.1, 0.9, Spend(wall_time_ms=1)),
            MethodTier.EMBEDDING: MethodResult("weak", 0.2, 0.8, Spend(wall_time_ms=1)),
        })
        result = route(
            profile(WorkClass.RETRIEVAL_ONLY, quality=0.9, uncertainty=0.1),
            RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(), now=T0,
        )
        self.assertEqual(result.outcome, RouteOutcome.ABSTAINED)
        self.assertIsNone(result.output)
        self.assertEqual(len(result.attempted_tiers), 2)

    def test_budget_insufficient_outcome_before_any_execution(self):
        executor = FakePricedExecutor({MethodTier.DETERMINISTIC: MethodResult("expensive", 1.0, 0.0, Spend(cost_micros=11))})
        result = route(
            profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(cost=10), now=T0,
        )
        self.assertEqual(result.outcome, RouteOutcome.BUDGET_INSUFFICIENT)
        self.assertEqual(executor.calls, [])


class CounterfactualEvidenceTests(unittest.TestCase):
    def test_only_genuinely_attempted_tiers_are_observed(self):
        executor = FakePricedExecutor({
            MethodTier.DETERMINISTIC: MethodResult("weak", 0.1, 0.9, Spend(wall_time_ms=1)),
            MethodTier.LIGHTWEIGHT_ML: MethodResult("good", 0.9, 0.1, Spend(wall_time_ms=1)),
            MethodTier.SMALL_MODEL: MethodResult("unused", 1.0, 0.0, Spend(wall_time_ms=1)),
        })
        result = route(profile(), RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(), now=T0)
        observed_tiers = [c.tier for c in result.counterfactuals]
        self.assertEqual(observed_tiers, [MethodTier.DETERMINISTIC, MethodTier.LIGHTWEIGHT_ML])
        self.assertNotIn(MethodTier.SMALL_MODEL, observed_tiers)
        self.assertTrue(all(c.status is CounterfactualEvidenceStatus.OBSERVED for c in result.counterfactuals))
        self.assertTrue(all(c.result is not None for c in result.counterfactuals))

    def test_bounded_replay_produces_replayed_counterfactuals_on_its_own_ledger(self):
        executor = FakePricedExecutor({MethodTier.SMALL_MODEL: MethodResult("replayed", 0.7, 0.3, Spend(cost_micros=5, wall_time_ms=2))})
        replay_ledger = ledger()
        comparisons = bounded_replay(profile(), (MethodTier.SMALL_MODEL,), executor, replay_ledger, now=T0)
        self.assertEqual(len(comparisons), 1)
        self.assertEqual(comparisons[0].status, CounterfactualEvidenceStatus.REPLAYED)
        self.assertEqual(comparisons[0].result.output, "replayed")
        self.assertEqual(replay_ledger.used.cost_micros, 5)

        # An independent route() call's ledger is untouched by the replay.
        route_ledger = ledger()
        route_executor = FakePricedExecutor({MethodTier.DETERMINISTIC: MethodResult("ok", 1.0, 0.0, Spend(wall_time_ms=1))})
        route(profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), route_executor, ScopedCaches(PROJECT), route_ledger, now=T0)
        self.assertEqual(route_ledger.used.cost_micros, 0)


class RoutingConfidenceResolverTests(unittest.TestCase):
    def test_cold_start_reports_zero_coverage_so_the_router_escalates(self):
        gate = ShadowModeGate(decision_type=ROUTING_CONFIDENCE, baseline=DeterministicBaseline(ROUTING_CONFIDENCE), baseline_threshold=0.5)
        result = resolve_routing_confidence(gate, profile())
        self.assertEqual(result.evidence_coverage, 0.0)
        self.assertEqual(result.uncertainty, 1.0)
        self.assertEqual(result.spend, Spend())

    def test_feature_vector_round_trips_the_real_task_profile_fields(self):
        p = profile(quality=0.4, uncertainty=0.6, privacy_risk=0.2)
        features = routing_confidence_features(p)
        values = dict(features.values)
        self.assertEqual(values["required_quality"], 0.4)
        self.assertEqual(values["uncertainty"], 0.6)
        self.assertEqual(values["privacy_risk"], 0.2)


class PromotionGateTests(unittest.TestCase):
    def test_no_paired_evidence(self):
        self.assertEqual(
            router_promotion_reason(evaluate_router_promotion(())),
            "ADAPTIVE ROUTING NOT PROMOTED — no paired replay evidence available",
        )

    def test_quality_floor_violation_blocks_promotion(self):
        floor = QualityFloor(0.8, 0.2, hard=True)
        records = (
            RouterReplayRecord(
                WorkClass.BOUNDED_SYNTHESIS,
                adaptive=MethodResult("weak", 0.5, 0.5, Spend(cost_micros=1)),  # below the floor
                baseline=MethodResult("ok", 0.9, 0.1, Spend(cost_micros=10)),
                adaptive_spend=Spend(cost_micros=1), baseline_spend=Spend(cost_micros=10),
                quality_floor=floor,
            ),
        )
        evaluation = evaluate_router_promotion(records)
        self.assertFalse(evaluation.quality_preserved)
        self.assertIn("quality floor violated", router_promotion_reason(evaluation))

    def test_quality_preserved_but_no_improvement_is_an_honest_negative(self):
        floor = QualityFloor(0.5, 0.5, hard=False)
        records = tuple(
            RouterReplayRecord(
                WorkClass.CLASSIFICATION_RANKING,
                adaptive=MethodResult("ok", 0.9, 0.1, Spend(cost_micros=10)),
                baseline=MethodResult("ok", 0.9, 0.1, Spend(cost_micros=10)),
                adaptive_spend=Spend(cost_micros=10, wall_time_ms=5),
                baseline_spend=Spend(cost_micros=10, wall_time_ms=5),
                quality_floor=floor,
            )
            for _ in range(5)
        )
        evaluation = evaluate_router_promotion(records)
        self.assertTrue(evaluation.quality_preserved)
        self.assertEqual(
            router_promotion_reason(evaluation),
            "ADAPTIVE ROUTING NOT PROMOTED — quality preserved but no cost/latency improvement observed",
        )

    def test_lower_cost_at_preserved_quality_is_promotion_eligible(self):
        floor = QualityFloor(0.5, 0.5, hard=False)
        records = tuple(
            RouterReplayRecord(
                WorkClass.CLASSIFICATION_RANKING,
                adaptive=MethodResult("ok", 0.85, 0.15, Spend(cost_micros=2)),
                baseline=MethodResult("ok", 0.85, 0.15, Spend(cost_micros=10)),
                adaptive_spend=Spend(cost_micros=2, wall_time_ms=1),
                baseline_spend=Spend(cost_micros=10, wall_time_ms=5),
                quality_floor=floor,
            )
            for _ in range(10)
        )
        evaluation = evaluate_router_promotion(records)
        self.assertTrue(evaluation.quality_preserved)
        self.assertLess(evaluation.mean_cost_delta_micros, 0)
        reason = router_promotion_reason(evaluation)
        self.assertTrue(reason.startswith("adaptive routing promotion-eligible"), reason)


class ProviderNeutralityTests(unittest.TestCase):
    def test_no_vendor_names_appear_in_the_router_module(self):
        from midnight_performance.repo_intelligence import cost_quality
        source = Path(inspect.getfile(cost_quality)).read_text(encoding="utf-8").lower()
        for vendor in ("claude", "openai", "gemini", "anthropic"):
            self.assertNotIn(vendor, source)



if __name__ == "__main__":
    unittest.main()
