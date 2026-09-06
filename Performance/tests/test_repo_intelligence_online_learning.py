"""Execution 06: verified online updates, drift rollback, and isolation."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.lightweight_intelligence import (
    FEATURE_SCHEMA_VERSION,
    FETCH_WORTH_IT,
    FeatureVector,
    LightweightDecision,
    record_decision,
)
from midnight_performance.repo_intelligence.online_learning import (
    Attribution,
    DriftPolicy,
    ExplorationPolicy,
    LabelSource,
    ModelStatus,
    OnlineLearningController,
    OnlineLearningPolicy,
    UpdateDisposition,
    VerifiedLabel,
)
from midnight_performance.repo_intelligence_store import RepoIntelligenceStore


NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
PROJECT_A = deterministic_identity(EntityKind.PROJECT, "online-alpha")
PROJECT_B = deterministic_identity(EntityKind.PROJECT, "online-beta")


def features(value: float = 0.8) -> FeatureVector:
    return FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION, (
        ("project_match", value), ("hotspot_match", value), ("evidence_quality", value),
        ("source_authority", value), ("freshness", value), ("novelty", value),
        ("learning_value", value), ("diversity", value), ("redundancy", 0.0),
    ))


def decision(project=PROJECT_A, probability: float = 0.8, offset: int = 0):
    result = LightweightDecision("fetch", probability, None, False, True, "shadow")
    return record_decision(project, result, features(probability), model_name="online-logistic", model_version="1", occurred_at=NOW + timedelta(seconds=offset))


def label(record, event_id: str, value=True, *, project=PROJECT_A, attribution=Attribution.CERTAIN, source=LabelSource.INDEPENDENT_VERIFICATION):
    return VerifiedLabel(event_id, project, record.identity.canonical, value, source, f"verification:{event_id}", NOW, attribution)


class OnlineLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RepoIntelligenceStore.open_for_project(Path(self.temp.name), PROJECT_A)
        self.controller = OnlineLearningController(PROJECT_A, self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_no_label_and_ambiguous_attribution_never_update(self):
        first, second = decision(offset=1), decision(offset=2)
        self.store.append_learned_decision(first)
        self.store.append_learned_decision(second)
        no_label = self.controller.process(label(first, "no-label", None))
        ambiguous = self.controller.process(label(second, "ambiguous", False, attribution=Attribution.AMBIGUOUS))
        self.assertEqual(no_label.disposition, UpdateDisposition.NO_LABEL)
        self.assertEqual(ambiguous.disposition, UpdateDisposition.AMBIGUOUS)
        self.assertIsNone(self.store.load_online_checkpoint(PROJECT_A, FETCH_WORTH_IT))

    def test_verified_outcome_updates_exactly_once_and_replay_is_idempotent(self):
        record = decision()
        self.store.append_learned_decision(record)
        event = label(record, "verified-1", True)
        first = self.controller.process(event)
        replay = self.controller.process(event)
        self.assertEqual(first.disposition, UpdateDisposition.UPDATED)
        self.assertEqual(first.checkpoint.update_count, 1)
        self.assertEqual(replay.disposition, UpdateDisposition.DUPLICATE)
        self.assertEqual(self.store.load_online_checkpoint(PROJECT_A, FETCH_WORTH_IT).update_count, 1)
        self.assertTrue(self.store.get_learned_decision(PROJECT_A, record.identity.canonical).outcome_label)

    def test_second_label_for_same_decision_does_not_train_twice(self):
        record = decision()
        self.store.append_learned_decision(record)
        self.controller.process(label(record, "first", True))
        result = self.controller.process(label(record, "second", False))
        self.assertEqual(result.disposition, UpdateDisposition.ALREADY_LABELED)
        self.assertEqual(self.store.load_online_checkpoint(PROJECT_A, FETCH_WORTH_IT).update_count, 1)

    def test_project_a_cannot_train_project_b(self):
        other = decision(PROJECT_B)
        with self.assertRaises(PermissionError):
            self.controller.process(label(other, "cross-project", project=PROJECT_B))

    def test_proxy_labels_require_explicit_opt_in(self):
        record = decision()
        self.store.append_learned_decision(record)
        result = self.controller.process(label(record, "proxy", source=LabelSource.BOUNDED_PROXY))
        self.assertEqual(result.disposition, UpdateDisposition.INELIGIBLE_SOURCE)

    def test_drift_disables_authority_and_gate_falls_back(self):
        policy = OnlineLearningPolicy(
            minimum_shadow_samples=2, minimum_production_samples=4,
            drift=DriftPolicy(minimum_window=4, rolling_window=8, maximum_calibration_error=0.5, maximum_reward_shift=0.25),
        )
        controller = OnlineLearningController(PROJECT_A, self.store, policy=policy)
        last = None
        for index in range(4):
            record = decision(probability=0.9, offset=index)
            self.store.append_learned_decision(record)
            last = controller.process(label(record, f"good-{index}", True))
        promoted = controller.enable_production_authority(FETCH_WORTH_IT, now=NOW + timedelta(minutes=1))
        self.assertTrue(promoted.production_authority)
        for index in range(4, 8):
            record = decision(probability=0.9, offset=index)
            self.store.append_learned_decision(record)
            last = controller.process(label(record, f"bad-{index}", False))
        self.assertTrue(last.drift.drifted)
        self.assertEqual(last.checkpoint.status, ModelStatus.DEGRADED)
        self.assertFalse(last.checkpoint.production_authority)
        self.assertIsNone(controller.gate(FETCH_WORTH_IT, baseline_threshold=0.35).model)

    def test_deleted_or_corrupt_checkpoint_returns_to_deterministic_baseline(self):
        record = decision()
        self.store.append_learned_decision(record)
        self.controller.process(label(record, "one"))
        self.store._conn.execute(
            "UPDATE online_model_checkpoints SET checkpoint_json = ? WHERE project = ?",
            (json.dumps({"checkpoint_hash": "tampered"}), PROJECT_A.canonical),
        )
        self.store._conn.commit()
        self.assertIsNone(self.controller.gate(FETCH_WORTH_IT, baseline_threshold=0.35).model)
        self.store.discard_online_learning_state(PROJECT_A)
        self.assertIsNone(self.controller.gate(FETCH_WORTH_IT, baseline_threshold=0.35).model)

    def test_exploration_never_overrides_privacy_or_security_hard_rules(self):
        exploration = ExplorationPolicy(enabled=True, rate=1.0, daily_budget=1, maximum_privacy_risk=0.1)
        self.assertFalse(exploration.allows(PROJECT_A, "d1", privacy_risk=0.0, security_sensitive=True, used_today=0))
        self.assertFalse(exploration.allows(PROJECT_A, "d1", privacy_risk=0.2, security_sensitive=False, used_today=0))
        self.assertFalse(exploration.allows(PROJECT_A, "d1", privacy_risk=0.0, security_sensitive=False, used_today=1))
        self.assertTrue(exploration.allows(PROJECT_A, "d1", privacy_risk=0.0, security_sensitive=False, used_today=0))


if __name__ == "__main__":
    unittest.main()
