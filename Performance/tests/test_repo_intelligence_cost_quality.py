"""Cost-quality routing, cache isolation, pruning, escalation, and reconciliation."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.cost_quality import BudgetLedger, BudgetLimits, CacheKind, MethodResult, MethodTier, ScopedCaches, Spend, TaskProfile, WorkClass, prune_communities, route
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "router-alpha")
OTHER = deterministic_identity(EntityKind.PROJECT, "router-beta")
JOB = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB, "router-job")

def profile(kind=WorkClass.BOUNDED_SYNTHESIS, quality=.8):
    return TaskProfile(PROJECT, JOB, kind, "auth-retry", quality, .2, .5, .1, .8, 100, "interactive", "evidence-v1")

def ledger(cost=10_000):
    return BudgetLedger(BudgetLimits(10, 10_000, 10_000, 1_000_000, 10_000, 2, 3, cost))

class FakePricedExecutor:
    def __init__(self, results): self.results, self.calls = results, []
    def estimate(self, tier, _profile): return self.results[tier].spend
    def execute(self, tier, _profile):
        self.calls.append(tier)
        return self.results[tier]

class RouterTests(unittest.TestCase):
    def test_deterministic_work_never_calls_models(self):
        executor = FakePricedExecutor({MethodTier.DETERMINISTIC: MethodResult("ast answer", 1, 0, Spend(wall_time_ms=1))})
        result = route(profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(), now=T0)
        self.assertEqual(executor.calls, [MethodTier.DETERMINISTIC])
        self.assertEqual(result.accepted_tier, MethodTier.DETERMINISTIC)

    def test_quality_gate_forces_then_stops_escalation(self):
        executor = FakePricedExecutor({
            MethodTier.RETRIEVAL: MethodResult("weak", .4, .6, Spend(wall_time_ms=1)),
            MethodTier.LIGHTWEIGHT_ML: MethodResult("weak-ml", .5, .5, Spend(wall_time_ms=1)),
            MethodTier.SMALL_MODEL: MethodResult("good", .9, .1, Spend(requests=1, tokens_in=20, tokens_out=5, wall_time_ms=2, cost_micros=7)),
            MethodTier.STRONG_MODEL: MethodResult("unused", 1, 0),
        })
        result = route(profile(), RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(), now=T0)
        self.assertEqual(executor.calls, [MethodTier.RETRIEVAL, MethodTier.LIGHTWEIGHT_ML, MethodTier.SMALL_MODEL])
        self.assertEqual(result.final_spend.cost_micros, 7)
        self.assertEqual(sum(item.cost_micros or 0 for item in result.costs), 7)
        self.assertEqual(result.outcome.value, "accepted")
        self.assertEqual(len(result.attempted_results), 3)
        self.assertTrue(all(c.status.value == "observed" for c in result.counterfactuals))

    def test_cache_hit_avoids_duplicate_spend_and_stale_cache_recomputes(self):
        executor = FakePricedExecutor({MethodTier.DETERMINISTIC: MethodResult("answer", 1, 0, Spend(cost_micros=3))})
        caches, budget = ScopedCaches(PROJECT), ledger()
        first = route(profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), executor, caches, budget, now=T0, ttl=timedelta(minutes=1))
        second = route(profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), executor, caches, budget, now=T0)
        self.assertTrue(second.cache_hit)
        self.assertEqual(len(executor.calls), 1)
        route(profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), executor, caches, budget, now=T0 + timedelta(minutes=2))
        self.assertEqual(len(executor.calls), 2)

    def test_hard_budget_returns_gap_without_consuming_overage(self):
        executor = FakePricedExecutor({MethodTier.DETERMINISTIC: MethodResult("expensive", 1, 0, Spend(cost_micros=11))})
        result = route(profile(WorkClass.DETERMINISTIC), RepoIntelligenceAuthorization(PROJECT), executor, ScopedCaches(PROJECT), ledger(cost=10), now=T0)
        self.assertIsNone(result.output)
        self.assertIn("hard budget", result.gap)
        self.assertEqual(result.final_spend.cost_micros, 0)
        self.assertEqual(executor.calls, [])

    def test_irrelevant_communities_are_pruned_deterministically(self):
        self.assertEqual(prune_communities((("z", .1), ("b", .8), ("a", .8)), relevance_threshold=.5, maximum=2), ("a", "b"))

    def test_cross_project_cache_fails_closed(self):
        with self.assertRaises(PermissionError):
            ScopedCaches(PROJECT).get(CacheKind.SOURCE_CONTENT, "x", project=OTHER, now=T0, evidence_set_hash="e")

if __name__ == "__main__": unittest.main()
