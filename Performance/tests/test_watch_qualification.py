from datetime import datetime, timedelta, timezone

from midnight_performance import (
    DataFailure, ExternalReference, OutcomeProvider, OutcomeReference, OutcomeWindow,
    RuntimeFailure, RuntimeQualificationInput, WatchDataEvidence, WatchQualificationState,
    qualify_data, qualify_runtime,
)


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def _runtime(*, occurred_at=NOW, release="release-1", complete=True, sampling=1.0, changes=()):
    return RuntimeQualificationInput(
        "prompt-1", "episode-1", release, "deployment-1",
        OutcomeReference(OutcomeProvider.RUNTIME, "regression", "runtime-1", occurred_at=occurred_at),
        OutcomeWindow("episode-1", NOW - timedelta(minutes=1), NOW + timedelta(minutes=1), "prod", "release-1"),
        complete, sampling, changes,
    )


def _ref(kind):
    return ExternalReference("watch-data", kind, f"{kind}-1", 1)


def _data(**changes):
    values = dict(schema=_ref("schema"), access=_ref("access"), query=_ref("query"), runtime=_ref("runtime"), cost=_ref("cost"), regression=_ref("regression"), verification=_ref("verification"), access_granted=True, telemetry_complete=True, expected_workload="release-query", observed_workload="release-query", expected_schema_version=2, reported_schema_version=2)
    values.update(changes)
    return WatchDataEvidence(**values)


def test_runtime_positive_association_is_explicitly_non_causal_and_reference_only():
    result = qualify_runtime(_runtime())
    assert result.state is WatchQualificationState.QUALIFIED
    assert result.association is not None
    assert result.association.outcome.external_id == "runtime-1"
    assert "causation" in result.uncertainty


def test_runtime_adversarial_counterexamples_reject_or_degrade_without_rewriting_outcome():
    outside = qualify_runtime(_runtime(occurred_at=NOW + timedelta(days=1)))
    assert outside.state is WatchQualificationState.REJECTED
    assert outside.association is None
    assert RuntimeFailure.OUTSIDE_OUTCOME_WINDOW in outside.failures

    sampled = qualify_runtime(_runtime(complete=False, sampling=None, changes=("change:later",)))
    assert sampled.state is WatchQualificationState.DEGRADED
    assert sampled.association is not None
    assert set(sampled.failures) == {RuntimeFailure.MISSING_TELEMETRY, RuntimeFailure.INTERVENING_CHANGES}

    partial_sample = qualify_runtime(_runtime(sampling=.2))
    assert partial_sample.state is WatchQualificationState.DEGRADED
    assert partial_sample.failures == (RuntimeFailure.SAMPLED_TELEMETRY,)


def test_data_contract_requires_all_reference_domains_and_surfaces_failure_accounting():
    healthy = qualify_data(_data())
    assert healthy.state is WatchQualificationState.QUALIFIED
    assert len(healthy.accepted_references) == 7

    degraded = qualify_data(_data(telemetry_complete=False, observed_workload="ad-hoc", reported_schema_version=3, intervening_migration=_ref("migration"), stale_references=(_ref("old-query"),), verification=None))
    assert degraded.state is WatchQualificationState.DEGRADED
    assert set(degraded.failures) == {DataFailure.INCOMPLETE_TELEMETRY, DataFailure.MISSING_EVIDENCE, DataFailure.WORKLOAD_MISMATCH, DataFailure.SCHEMA_VERSION_MISMATCH, DataFailure.INTERVENING_MIGRATION, DataFailure.STALE_REFERENCE}

    denied = qualify_data(_data(access_granted=False))
    assert denied.state is WatchQualificationState.REJECTED
    assert denied.claim_kind.value == "unknown"
    assert DataFailure.PERMISSION_MISSING in denied.failures
