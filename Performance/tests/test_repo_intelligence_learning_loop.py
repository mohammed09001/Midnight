"""Continuous learning loop controls and adversarial termination behavior."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.learning_loop import CircuitBreaker, ContinuousLearningLoop, LearningTrigger, LoopControls, MarginalKnowledgeGain, TriggerKind

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "loop-alpha")
OTHER = deterministic_identity(EntityKind.PROJECT, "loop-beta")
AUTH = RepoIntelligenceAuthorization(PROJECT)

def trigger(second=0, *, kind=TriggerKind.REPOSITORY_CHANGE, project=PROJECT, ref="change-1"):
    return LearningTrigger(project, kind, "auth", T0 + timedelta(seconds=second), "auth files changed", ref)

class LoopTests(unittest.TestCase):
    def test_bursty_duplicate_triggers_coalesce_and_replay_idempotently(self):
        loop = ContinuousLearningLoop(PROJECT)
        first = loop.run((trigger(0), trigger(1, ref="change-2")), AUTH, now=T0 + timedelta(seconds=15))
        self.assertEqual(first.coalesced_trigger_count, 1)
        replay = loop.run((trigger(0), trigger(1, ref="change-2")), AUTH, now=T0 + timedelta(seconds=15))
        self.assertTrue(replay.replayed)
        self.assertEqual(first.job.identity, replay.job.identity)

    def test_zero_marginal_gain_stops_before_remote_spend(self):
        loop = ContinuousLearningLoop(PROJECT)
        result = loop.run((trigger(),), AUTH, now=T0, marginal_gains=(MarginalKnowledgeGain(redundancy=1), MarginalKnowledgeGain(evidence_diversity=1)))
        self.assertEqual(result.remote_steps, 0)
        self.assertIn("redundancy saturation", result.stopped_reason)

    def test_offline_and_duplicate_question_skip_external_branch(self):
        offline = ContinuousLearningLoop(PROJECT).run((trigger(),), AUTH, now=T0, provider_available=False)
        self.assertEqual(offline.remote_steps, 0)
        duplicate = ContinuousLearningLoop(PROJECT).run((trigger(),), AUTH, now=T0, question_key="auth-retry", existing_question_keys=frozenset({"auth-retry"}), marginal_gains=(MarginalKnowledgeGain(evidence_diversity=1),))
        self.assertEqual(duplicate.remote_steps, 0)
        self.assertIn("duplicate research question", duplicate.audit_trail[-1])

    def test_cancellation_checkpoint_resumes_same_job(self):
        loop = ContinuousLearningLoop(PROJECT)
        cancelled = loop.run((trigger(),), AUTH, now=T0, cancel=True)
        self.assertTrue(cancelled.checkpoint.cancelled)
        resumed = loop.run((trigger(),), AUTH, now=T0, resume=cancelled.checkpoint, marginal_gains=(MarginalKnowledgeGain(freshness=1),))
        self.assertEqual(cancelled.job.identity, resumed.job.identity)
        self.assertFalse(resumed.checkpoint.cancelled)

    def test_circuit_breaker_counts_only_transient_failures(self):
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.record_failure(T0, transient=False)
        self.assertTrue(breaker.allow(T0))
        breaker.record_failure(T0, transient=True)
        breaker.record_failure(T0, transient=True)
        loop = ContinuousLearningLoop(PROJECT, circuit_breaker=breaker)
        result = loop.run((trigger(),), AUTH, now=T0, marginal_gains=(MarginalKnowledgeGain(freshness=1),))
        self.assertEqual(result.remote_steps, 0)
        self.assertIn("circuit breaker", result.stopped_reason)

    def test_cross_project_and_disabled_project_fail_closed(self):
        loop = ContinuousLearningLoop(PROJECT)
        with self.assertRaises(PermissionError):
            loop.run((trigger(project=OTHER),), AUTH, now=T0)
        disabled = ContinuousLearningLoop(PROJECT, controls=LoopControls(enabled=False)).run((trigger(),), AUTH, now=T0)
        self.assertIsNone(disabled.job)

if __name__ == "__main__": unittest.main()
