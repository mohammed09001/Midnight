"""Execution RI-14's unique release metric: never optimizes click rate alone."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.contracts import (
    AssociationKind,
    CacheStatus,
    ClaimKind,
    CostRecord,
    CostResourceKind,
    Exposure,
    ExposureChannel,
    ExposureOutcome,
    LearningOutcome,
    ProjectIntelligenceJob,
    project_intelligence_job_identity,
)
from midnight_performance.repo_intelligence.contracts import BudgetCeiling, JobStatus, JobTrigger
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence.release_metric import (
    compute_release_metric,
    normalized_compute_cost,
    useful_project_learning,
    user_attention_cost,
)

T0 = datetime(2026, 9, 5, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "release-alpha")
INSIGHT = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "release-insight")
EXPOSURE_ID = deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, "release-exposure")
JOB = project_intelligence_job_identity(PROJECT, "test", "k1")


def outcome(association, *, suffix="o"):
    return LearningOutcome(
        deterministic_repo_identity(RepoIntelligenceKind.LEARNING_OUTCOME, suffix), PROJECT, EXPOSURE_ID, INSIGHT,
        association, ClaimKind.STATISTICAL, "m", "1", "associative only", T0, T0 + timedelta(days=1),
    )


def push(outcome_kind, *, suffix="p"):
    return Exposure(
        deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, suffix), PROJECT, INSIGHT,
        ExposureChannel.PROACTIVE_PUSH, outcome_kind, "terminal", T0,
        relevance_justification="hiding this would leave a pattern unexplained",
        suppression_reason="attention budget exhausted" if outcome_kind is ExposureOutcome.SUPPRESSED else None,
    )


def cost(cost_micros, *, suffix="c"):
    return CostRecord(
        deterministic_repo_identity(RepoIntelligenceKind.COST_RECORD, suffix), PROJECT, JOB,
        CostResourceKind.MODEL_INFERENCE, "provider", 10.0, T0, CacheStatus.MISS, cost_micros=cost_micros,
    )


class UsefulProjectLearningTests(unittest.TestCase):
    def test_positive_and_negative_associations_net_out(self):
        outcomes = (outcome(AssociationKind.POSITIVE_ASSOCIATION, suffix="p1"), outcome(AssociationKind.POSITIVE_ASSOCIATION, suffix="p2"), outcome(AssociationKind.NEGATIVE_ASSOCIATION, suffix="n1"))
        self.assertEqual(useful_project_learning(outcomes), 1.0)

    def test_inconclusive_and_none_do_not_count_either_way(self):
        outcomes = (outcome(AssociationKind.INCONCLUSIVE, suffix="i1"), outcome(AssociationKind.NONE, suffix="n1"))
        self.assertEqual(useful_project_learning(outcomes), 0.0)


class UserAttentionCostTests(unittest.TestCase):
    def test_a_dismissal_still_cost_attention(self):
        exposures = (push(ExposureOutcome.DISMISSED),)
        self.assertEqual(user_attention_cost(exposures), 1.0)

    def test_suppressed_exposures_that_never_reached_the_user_are_free(self):
        exposures = (push(ExposureOutcome.SUPPRESSED),)
        self.assertEqual(user_attention_cost(exposures), 0.0)


class NormalizedComputeCostTests(unittest.TestCase):
    def test_normalizes_micros_to_units(self):
        costs = (cost(2_000_000, suffix="c1"), cost(500_000, suffix="c2"))
        self.assertEqual(normalized_compute_cost(costs), 2.5)

    def test_rejects_non_positive_unit_size(self):
        with self.assertRaises(ValueError):
            normalized_compute_cost((), micros_per_unit=0)


class ReleaseMetricTests(unittest.TestCase):
    def test_never_optimizes_click_rate_alone(self):
        """A frequently-offered, never-associated insight scores worse than a rarely-offered, positively-associated one."""
        clicky = compute_release_metric(
            (outcome(AssociationKind.INCONCLUSIVE, suffix="i1"),),
            tuple(push(ExposureOutcome.OFFERED, suffix=f"p{i}") for i in range(10)),
            (),
        )
        rare_but_useful = compute_release_metric(
            (outcome(AssociationKind.POSITIVE_ASSOCIATION, suffix="p1"),),
            (push(ExposureOutcome.OFFERED, suffix="single"),),
            (),
        )
        self.assertLess(clicky.value, rare_but_useful.value)

    def test_undefined_ratio_when_nothing_has_been_spent_yet(self):
        metric = compute_release_metric((), (), ())
        self.assertIsNone(metric.value)

    def test_rejects_negative_costs(self):
        from midnight_performance.repo_intelligence.release_metric import ReleaseMetric

        with self.assertRaises(ValueError):
            ReleaseMetric(useful_project_learning=1.0, user_attention_cost=-1.0, normalized_compute_cost=0.0)


if __name__ == "__main__":
    unittest.main()
