"""Execution RI-14: the exact attention-ranking formula and its own finite budget ledger."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.attention import (
    AttentionBudgetLimits,
    AttentionFactors,
    RankedAttentionCandidate,
    attention_budget_allows,
    attention_spend,
    rank_attention_candidates,
)
from midnight_performance.repo_intelligence.contracts import Exposure, ExposureChannel, ExposureOutcome
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity

T0 = datetime(2026, 9, 5, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "attention-alpha")
INSIGHT = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "attention-insight")


def factors(**overrides):
    values = dict(
        learning_pressure=.8, evidence_strength=.8, novelty=.8, expected_learning_value=.8, timing_fit=.8,
        redundancy=.05, interruption_cost=.05, uncertainty=.05, stale_risk=.0,
    )
    values.update(overrides)
    return AttentionFactors(**values)


def exposure(channel, outcome, occurred_at, *, identity_suffix="e"):
    kwargs = {}
    if channel is ExposureChannel.PROACTIVE_PUSH:
        kwargs["relevance_justification"] = "hiding this would leave a recurring pattern unexplained"
    if outcome is ExposureOutcome.SUPPRESSED:
        kwargs["suppression_reason"] = "attention budget exhausted for this window"
    return Exposure(
        deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, identity_suffix), PROJECT, INSIGHT,
        channel, outcome, "terminal", occurred_at, **kwargs,
    )


class AttentionFactorsScoreTests(unittest.TestCase):
    def test_score_is_product_of_gains_minus_sum_of_costs(self):
        f = factors(
            learning_pressure=.5, evidence_strength=.5, novelty=.5, expected_learning_value=.5, timing_fit=.5,
            redundancy=.1, interruption_cost=.1, uncertainty=.1, stale_risk=.1,
        )
        expected = (.5 ** 5) - (.1 + .1 + .1 + .1)
        self.assertAlmostEqual(f.score, expected, places=6)

    def test_rejects_out_of_range_factor(self):
        with self.assertRaises(ValueError):
            factors(novelty=1.5)
        with self.assertRaises(ValueError):
            factors(stale_risk=-0.1)

    def test_a_fully_stale_candidate_can_score_below_zero(self):
        f = factors(stale_risk=1.0, redundancy=0.5)
        self.assertLess(f.score, 0)


class RankAttentionCandidatesTests(unittest.TestCase):
    def test_orders_descending_by_score_with_identity_tiebreak(self):
        low = RankedAttentionCandidate("b-low", factors(learning_pressure=.2), "low pressure")
        high = RankedAttentionCandidate("a-high", factors(learning_pressure=.9), "high pressure")
        ranked = rank_attention_candidates((low, high))
        self.assertEqual([c.identity for c in ranked], ["a-high", "b-low"])

    def test_equal_scores_break_ties_on_identity(self):
        first = RankedAttentionCandidate("z", factors(), "same")
        second = RankedAttentionCandidate("a", factors(), "same")
        ranked = rank_attention_candidates((first, second))
        self.assertEqual([c.identity for c in ranked], ["a", "z"])

    def test_requires_at_least_one_candidate(self):
        with self.assertRaises(ValueError):
            rank_attention_candidates(())


class AttentionSpendTests(unittest.TestCase):
    def test_quiet_queue_and_suppressed_exposures_cost_nothing(self):
        history = (
            exposure(ExposureChannel.QUIET_QUEUE, ExposureOutcome.SUPPRESSED, T0, identity_suffix="q1"),
            exposure(ExposureChannel.PROACTIVE_PUSH, ExposureOutcome.OFFERED, T0, identity_suffix="p1"),
        )
        spend = attention_spend(history, now=T0, window=timedelta(hours=1))
        self.assertEqual(spend.interruptions, 1)
        self.assertEqual(spend.digests, 0)

    def test_events_outside_the_window_do_not_count(self):
        history = (exposure(ExposureChannel.PROACTIVE_PUSH, ExposureOutcome.OFFERED, T0 - timedelta(days=1), identity_suffix="old"),)
        spend = attention_spend(history, now=T0, window=timedelta(hours=1))
        self.assertEqual(spend.interruptions, 0)

    def test_digest_channel_counted_separately_from_interruptions(self):
        history = (exposure(ExposureChannel.DIGEST, ExposureOutcome.OFFERED, T0, identity_suffix="d1"),)
        spend = attention_spend(history, now=T0, window=timedelta(hours=1))
        self.assertEqual(spend.interruptions, 0)
        self.assertEqual(spend.digests, 1)

    def test_budget_is_a_hard_finite_ceiling_independent_of_compute(self):
        limits = AttentionBudgetLimits(window=timedelta(hours=1), max_interruptions=1, max_digests=1)
        under = attention_spend((), now=T0, window=timedelta(hours=1))
        self.assertTrue(attention_budget_allows(under, limits))
        exhausted_history = (exposure(ExposureChannel.PROACTIVE_PUSH, ExposureOutcome.OFFERED, T0, identity_suffix="only"),)
        exhausted = attention_spend(exhausted_history, now=T0, window=timedelta(hours=1))
        self.assertFalse(attention_budget_allows(exhausted, limits))


if __name__ == "__main__":
    unittest.main()
