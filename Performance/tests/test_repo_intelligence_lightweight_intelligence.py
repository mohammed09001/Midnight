"""Lightweight intelligence layer (Repo Intelligent 02, Execution 04).

Verifies every bullet in the execution's spec:
- ML can be disabled/deleted with no correctness failure;
- cold start uses deterministic policy;
- shadow mode never changes user-visible action;
- feature records do not contain prohibited raw content;
- model-version mismatch fails safely;
- uncertain predictions abstain;
- at least one candidate decision demonstrates measurable offline value
  before production eligibility (or a real ``NO ML PROMOTION`` result).
"""

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.contracts import UnsupportedSchemaVersionError
from midnight_performance.repo_intelligence.discovery import score_discovery
from midnight_performance.repo_intelligence.lightweight_intelligence import (
    FEATURE_SCHEMA_VERSION,
    FETCH_WORTH_IT,
    AbstentionPolicy,
    DeterministicBaseline,
    FeatureVector,
    LightweightDecision,
    OnlineLogisticModel,
    ShadowModeGate,
    abstention_rate,
    calibrate,
    evaluate_against_baselines,
    promotion_reason,
    record_decision,
    relevance_features,
)
from midnight_performance.repo_intelligence.ports import DiscoveredSource
from midnight_performance.repo_intelligence.sources import SourceClass

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "lightweight-intelligence-alpha")


def fv(match: float, auth: float, *, freshness=0.5, novelty=1.0, diversity=0.5, redundancy=0.0) -> FeatureVector:
    """A directly-constructed feature vector: full control for the offline-value demonstration."""
    return FeatureVector(
        FETCH_WORTH_IT,
        FEATURE_SCHEMA_VERSION,
        (
            ("project_match", match),
            ("hotspot_match", match),
            ("evidence_quality", match),
            ("source_authority", auth),
            ("freshness", freshness),
            ("novelty", novelty),
            ("learning_value", match),
            ("diversity", diversity),
            ("redundancy", redundancy),
        ),
    )


_VALID_VALUES = dict(fv(0.5, 0.5).values)


def _record_for(features: FeatureVector, prediction: float, label: bool) -> "object":
    decision = LightweightDecision(
        action="fetch" if prediction >= 0.5 else "skip",
        shadow_probability=prediction,
        production_probability=None,
        abstained=False,
        used_model=True,
        reason="test-fixture",
    )
    record = record_decision(PROJECT, decision, features, model_name="test", model_version="1", occurred_at=T0)
    return replace(record, outcome_label=label, label_recorded_at=T0)


class FeatureContractTests(unittest.TestCase):
    def test_relevance_features_reproduces_a_real_score_discovery_result(self):
        hit = DiscoveredSource("fixture", "https://docs.example.com/retry", "Official retry", SourceClass.OFFICIAL_DOCS, 0.7)
        score = score_discovery(hit)
        features = relevance_features(score)
        self.assertEqual(features.decision_type, FETCH_WORTH_IT)
        self.assertEqual(dict(features.values)["source_authority"], score.source_authority)
        self.assertEqual(DeterministicBaseline().predict_proba(features), score.total)

    def test_unknown_decision_type_is_rejected(self):
        with self.assertRaises(ValueError):
            FeatureVector("some_other_decision", FEATURE_SCHEMA_VERSION, tuple(_VALID_VALUES.items()))

    def test_unsupported_schema_version_is_rejected(self):
        with self.assertRaises(ValueError):
            FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION + 1, tuple(_VALID_VALUES.items()))

    def test_unregistered_feature_name_is_rejected(self):
        values = tuple(_VALID_VALUES.items()) + (("raw_source_code", 0.5),)
        with self.assertRaises(ValueError):
            FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION, values)

    def test_missing_required_feature_is_rejected(self):
        incomplete = tuple((k, v) for k, v in _VALID_VALUES.items() if k != "redundancy")
        with self.assertRaises(ValueError):
            FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION, incomplete)

    def test_duplicate_feature_name_is_rejected(self):
        values = tuple(_VALID_VALUES.items()) + (("project_match", 0.1),)
        with self.assertRaises(ValueError):
            FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION, values)

    def test_out_of_range_value_is_rejected(self):
        values = tuple((k, 1.5 if k == "project_match" else v) for k, v in _VALID_VALUES.items())
        with self.assertRaises(ValueError):
            FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION, values)

    def test_forbidden_raw_text_feature_value_is_rejected(self):
        """Structural guard: a feature contract cannot smuggle raw text/objects."""
        values = tuple((k, "malicious instructions embedded here" if k == "project_match" else v) for k, v in _VALID_VALUES.items())
        with self.assertRaises(ValueError):
            FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION, values)

    def test_non_finite_value_is_rejected(self):
        values = tuple((k, float("nan") if k == "project_match" else v) for k, v in _VALID_VALUES.items())
        with self.assertRaises(ValueError):
            FeatureVector(FETCH_WORTH_IT, FEATURE_SCHEMA_VERSION, values)


class LearnedDecisionRecordTests(unittest.TestCase):
    def test_schema_version_mismatch_fails_safely(self):
        decision = LightweightDecision("fetch", 0.9, None, False, True, "test")
        record = record_decision(PROJECT, decision, fv(0.9, 0.9), model_name="m", model_version="1", occurred_at=T0)
        raw = record.to_dict()
        raw["schema_version"] = raw["schema_version"] + 1
        with self.assertRaises(UnsupportedSchemaVersionError):
            type(record).from_dict(raw)

    def test_round_trips_through_to_dict_from_dict(self):
        decision = LightweightDecision("skip", 0.2, None, False, True, "test")
        record = record_decision(
            PROJECT, decision, fv(0.2, 0.2), model_name="m", model_version="1", occurred_at=T0,
            evidence_ids=(), cost_micros=1000, latency_ms=12.5,
        )
        restored = type(record).from_dict(record.to_dict())
        self.assertEqual(restored, record)


class ColdStartAndShadowModeTests(unittest.TestCase):
    """Verifies: ML can be disabled with no correctness failure; cold start is
    deterministic; shadow mode never changes the user-visible action."""

    def setUp(self):
        self.baseline = DeterministicBaseline()
        self.threshold = 0.35

    def test_missing_model_uses_pure_deterministic_baseline(self):
        gate = ShadowModeGate(decision_type=FETCH_WORTH_IT, baseline=self.baseline, baseline_threshold=self.threshold, model=None)
        for match, auth in ((0.9, 0.1), (0.1, 0.9), (0.0, 0.0), (1.0, 1.0)):
            features = fv(match, auth)
            decision = gate.decide(features)
            self.assertEqual(decision.action, self.baseline.action(features, threshold=self.threshold))
            self.assertFalse(decision.used_model)
            self.assertIsNone(decision.shadow_probability)
            self.assertEqual(decision.reason, "cold_start_deterministic")

    def test_low_sample_count_is_cold_start_even_with_a_model_present(self):
        model = OnlineLogisticModel.initial(FETCH_WORTH_IT)
        gate = ShadowModeGate(
            decision_type=FETCH_WORTH_IT, baseline=self.baseline, baseline_threshold=self.threshold,
            model=model, sample_count=1, min_samples_for_shadow=20,
        )
        decision = gate.decide(fv(0.4, 1.0))
        self.assertEqual(decision.reason, "cold_start_deterministic")
        self.assertFalse(decision.used_model)

    def test_shadow_mode_records_disagreement_but_never_changes_the_action(self):
        model = _trained_model()
        disagreement_point = fv(0.4, 1.0)
        baseline_action = self.baseline.action(disagreement_point, threshold=self.threshold)
        model_probability = model.predict_proba(disagreement_point)
        # Confirm this really is a disagreement fixture before trusting the assertion below.
        self.assertEqual(baseline_action, "fetch")
        self.assertLess(model_probability, 0.5)

        gate = ShadowModeGate(
            decision_type=FETCH_WORTH_IT, baseline=self.baseline, baseline_threshold=self.threshold,
            model=model, sample_count=50, min_samples_for_shadow=20, min_samples_for_production=200,
        )
        self.assertTrue(gate.eligible_for_shadow)
        self.assertFalse(gate.eligible_for_production)
        decision = gate.decide(disagreement_point)
        self.assertEqual(decision.action, "fetch")  # baseline's action, unchanged
        self.assertAlmostEqual(decision.shadow_probability, model_probability)
        self.assertIsNone(decision.production_probability)
        self.assertEqual(decision.reason, "shadow_mode_no_production_effect")

    def test_promoted_model_can_change_the_action_when_confident(self):
        model = _trained_model()
        examples = _training_examples()
        report = calibrate(model, examples, buckets=5)
        gate = ShadowModeGate(
            decision_type=FETCH_WORTH_IT, baseline=self.baseline, baseline_threshold=self.threshold,
            model=model, sample_count=50, calibration=report,
            min_samples_for_shadow=20, min_samples_for_production=50, max_calibration_error=0.1,
        )
        self.assertTrue(gate.eligible_for_production)
        disagreement_point = fv(0.4, 1.0)
        decision = gate.decide(disagreement_point)
        self.assertEqual(decision.action, "skip")  # now the model's action, not the baseline's
        self.assertEqual(decision.reason, "model_promoted")
        self.assertIsNotNone(decision.production_probability)

    def test_promoted_model_abstains_on_an_ambiguous_prediction(self):
        model = _trained_model()
        examples = _training_examples()
        report = calibrate(model, examples, buckets=5)
        gate = ShadowModeGate(
            decision_type=FETCH_WORTH_IT, baseline=self.baseline, baseline_threshold=self.threshold,
            model=model, sample_count=50, calibration=report,
            min_samples_for_shadow=20, min_samples_for_production=50, max_calibration_error=0.1,
            abstention=AbstentionPolicy(margin=0.1),
        )
        boundary_point = fv(0.45, 0.5)
        probability = model.predict_proba(boundary_point)
        self.assertLess(abs(probability - 0.5), 0.1)  # confirm this really sits in the abstention zone
        decision = gate.decide(boundary_point)
        self.assertTrue(decision.abstained)
        self.assertFalse(decision.used_model)
        self.assertEqual(decision.action, self.baseline.action(boundary_point, threshold=self.threshold))
        self.assertEqual(decision.reason, "abstained_ambiguous")

    def test_abstention_rate_over_a_batch_of_decisions(self):
        decisions = (
            LightweightDecision("fetch", 0.9, 0.9, False, True, "model_promoted"),
            LightweightDecision("skip", 0.45, None, True, False, "abstained_ambiguous"),
            LightweightDecision("skip", 0.1, 0.1, False, True, "model_promoted"),
        )
        self.assertAlmostEqual(abstention_rate(decisions), 1 / 3)
        self.assertEqual(abstention_rate(()), 0.0)


_MATCHES_POSITIVE = (0.5, 0.6, 0.7, 0.8, 0.9)
_MATCHES_NEGATIVE = (0.0, 0.1, 0.2, 0.3, 0.4)
_AUTHORITIES = (0.0, 0.1, 0.45, 0.9, 1.0)


def _training_examples() -> tuple[tuple[FeatureVector, bool], ...]:
    """50 fixtures: label depends only on the match dimensions; source_authority
    is genuine noise, uncorrelated with the label -- exactly the shape a
    single equal-weighted threshold on ``RelevanceScore.total`` cannot
    separate cleanly (authority still gets 1/8 of the weight), but a model
    that learns to down-weight authority can."""
    examples = []
    for match in _MATCHES_POSITIVE:
        for auth in _AUTHORITIES:
            examples.append((fv(match, auth), True))
    for match in _MATCHES_NEGATIVE:
        for auth in _AUTHORITIES:
            examples.append((fv(match, auth), False))
    return tuple(examples)


def _trained_model() -> OnlineLogisticModel:
    model = OnlineLogisticModel.initial(FETCH_WORTH_IT, learning_rate=0.5)
    return model.fit(_training_examples(), epochs=300)


class OfflineValueDemonstrationTests(unittest.TestCase):
    """The spec requires at least one candidate decision to demonstrate
    measurable offline value before production eligibility -- or an honest
    ``NO ML PROMOTION`` result. Both paths are proven here, on the SAME
    fixture dataset, using the real `discovery.RelevanceScore`-derived
    feature contract and the real `DeterministicBaseline` (which reproduces
    the production `MINIMUM_FETCH_RELEVANCE` gate's arithmetic exactly)."""

    def test_untrained_model_does_not_beat_baseline_and_says_so_honestly(self):
        examples = _training_examples()
        untrained = OnlineLogisticModel.initial(FETCH_WORTH_IT)
        baseline = DeterministicBaseline()
        records = tuple(_record_for(features, untrained.predict_proba(features), label) for features, label in examples)
        evaluation = evaluate_against_baselines(records, baseline=baseline, baseline_threshold=0.35)
        self.assertEqual(
            promotion_reason(evaluation),
            "NO ML PROMOTION — deterministic baseline remains superior",
        )

    def test_trained_model_measurably_beats_the_deterministic_baseline(self):
        examples = _training_examples()
        trained = _trained_model()
        baseline = DeterministicBaseline()
        records = tuple(_record_for(features, trained.predict_proba(features), label) for features, label in examples)
        evaluation = evaluate_against_baselines(records, baseline=baseline, baseline_threshold=0.35)

        model_eval = evaluation["model"]
        baseline_eval = evaluation["deterministic_baseline"]
        always_escalate_eval = evaluation["always_escalate"]

        # The static 0.35 threshold over-trusts source authority: it lets
        # through every high-authority, low-match candidate (poor precision)
        # while never missing a true positive (perfect recall).
        self.assertAlmostEqual(baseline_eval.precision, 25 / 45, places=4)
        self.assertEqual(baseline_eval.recall, 1.0)
        self.assertGreater(baseline_eval.false_escalation_rate, 0.5)

        # The trained model learns to down-weight the noisy authority
        # feature and separates on the match dimensions instead.
        self.assertGreater(model_eval.precision, baseline_eval.precision)
        self.assertGreaterEqual(model_eval.recall, baseline_eval.recall)
        self.assertLess(model_eval.calibration_error, baseline_eval.calibration_error)

        # always_escalate is a real, measured baseline too, not a strawman.
        self.assertEqual(always_escalate_eval.recall, 1.0)
        self.assertLessEqual(always_escalate_eval.precision, model_eval.precision)

        reason = promotion_reason(evaluation)
        self.assertTrue(reason.startswith("model promotion-eligible"), reason)

    def test_unlabeled_records_are_excluded_not_treated_as_negative(self):
        examples = _training_examples()[:10]
        trained = _trained_model()
        baseline = DeterministicBaseline()
        labeled_records = tuple(_record_for(features, trained.predict_proba(features), label) for features, label in examples)
        unlabeled_decision = LightweightDecision("fetch", 0.9, None, False, True, "test")
        unlabeled_record = record_decision(
            PROJECT, unlabeled_decision, fv(0.9, 0.9), model_name="m", model_version="1", occurred_at=T0,
        )
        self.assertIsNone(unlabeled_record.outcome_label)

        with_unlabeled = evaluate_against_baselines(labeled_records + (unlabeled_record,), baseline=baseline, baseline_threshold=0.35)
        without_unlabeled = evaluate_against_baselines(labeled_records, baseline=baseline, baseline_threshold=0.35)
        self.assertEqual(with_unlabeled["model"].sample_count, without_unlabeled["model"].sample_count)
        self.assertEqual(with_unlabeled["model"].precision, without_unlabeled["model"].precision)


if __name__ == "__main__":
    unittest.main()
