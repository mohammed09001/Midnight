import unittest

from midnight_performance.repo_intelligence_qualification import (
    BaselineSnapshot,
    EconomicVerdict,
    EconomicsMetrics,
    QualificationStatus,
    ScenarioResult,
    build_integrated_report,
    compare_workload,
)


class IntegratedQualificationTests(unittest.TestCase):
    def setUp(self):
        self.baseline = BaselineSnapshot(
            QualificationStatus.PASS, QualificationStatus.PASS, QualificationStatus.PASS,
            QualificationStatus.UNKNOWN, "3.14", "20", (("linux", QualificationStatus.PASS), ("windows", QualificationStatus.UNKNOWN), ("macos", QualificationStatus.UNKNOWN)), QualificationStatus.UNKNOWN,
            commands=(("performance", "python -m unittest"),),
        )

    def test_unknown_baseline_or_scenario_cannot_be_reported_as_yes(self):
        report = build_integrated_report(self.baseline, (ScenarioResult("internal-only", QualificationStatus.PASS),))
        self.assertEqual(report.goal, QualificationStatus.UNKNOWN)

    def test_failure_is_stronger_than_unknown(self):
        report = build_integrated_report(self.baseline, (ScenarioResult("privacy", QualificationStatus.FAIL),))
        self.assertEqual(report.goal, QualificationStatus.FAIL)

    def test_cost_benefit_requires_quality_floor(self):
        baseline = EconomicsMetrics(total_answers=10, qualified_answers=10, compute_cost_micros=100, latency_ms=100)
        optimized = EconomicsMetrics(total_answers=10, qualified_answers=9, compute_cost_micros=10, latency_ms=10)
        result = compare_workload("known-question", baseline, optimized, quality_floor=1.0)
        self.assertEqual(result.verdict, EconomicVerdict.REGRESSION)
        self.assertFalse(result.quality_preserved)

    def test_verified_benefit_and_honest_no_benefit(self):
        baseline = EconomicsMetrics(total_answers=10, qualified_answers=9, compute_cost_micros=100, latency_ms=100)
        lower = EconomicsMetrics(total_answers=10, qualified_answers=9, compute_cost_micros=50, latency_ms=90)
        same = EconomicsMetrics(total_answers=10, qualified_answers=9, compute_cost_micros=100, latency_ms=100)
        self.assertEqual(compare_workload("local", baseline, lower, quality_floor=.8).verdict, EconomicVerdict.VERIFIED_BENEFIT)
        self.assertEqual(compare_workload("ambiguous", baseline, same, quality_floor=.8).verdict, EconomicVerdict.NO_VERIFIED_BENEFIT)


if __name__ == "__main__":
    unittest.main()
