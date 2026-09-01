from datetime import datetime, timedelta, timezone

from midnight_performance import DatasetRow, MLQualificationEvidence, qualify_analytics, qualify_ml


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def _rows(offset=0):
    return tuple(DatasetRow(f"r{offset}-{i}", NOW + timedelta(minutes=i), {"score": value}, "achieved" if value > .5 else "not_achieved", .9, {"project": "p1" if i % 2 else "p2", "cohort": "a" if i < 3 else "b"}, ("change",)) for i, value in enumerate((.1, .2, .3, .7, .8, .9)))


def test_analytics_qualification_runs_canonical_statistics_over_frozen_synthetic_rows():
    rows = _rows()
    result = qualify_analytics("frozen-v1", rows, rows, rows, feature="score", cohort=lambda row: row.agent_metadata["cohort"])
    assert result.state.value == "qualified"
    assert result.distribution.mean == .5
    assert result.comparison.sufficient and result.interval_sufficient and result.correlations_sufficient and result.confounder_sufficient


def test_analytics_and_ml_missing_gates_degrade_explicitly():
    empty = qualify_analytics("frozen-v1", (), _rows(), _rows(), feature="score", cohort=lambda row: row.agent_metadata.get("project"))
    assert empty.state.value == "degraded"
    assert "missing_feature_values" in empty.failures

    ml = qualify_ml(MLQualificationEvidence(None, None, 0, None, (), None, None, False))
    assert ml.state.value == "degraded"
    assert "readiness_or_leakage_gate_failed" in ml.failures
