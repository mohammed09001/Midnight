"""Passive qualification of Watch Runtime and Watch Data reference contracts.

This module accepts supplied, versioned references only.  It has no sibling
storage client, credentials, or authority to rewrite Watch-owned truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .associations import AssociationKind, OutcomeAssociation
from .contracts import ClaimKind, ExternalReference
from .outcomes import OutcomeProvider, OutcomeReference, OutcomeWindow

_VERSION = "1"
_DATA = "watch-data"


class WatchQualificationState(str, Enum):
    QUALIFIED = "qualified"
    DEGRADED = "degraded"
    REJECTED = "rejected"


class RuntimeFailure(str, Enum):
    MISSING_TELEMETRY = "missing_telemetry"
    SAMPLED_TELEMETRY = "sampled_telemetry"
    OUTSIDE_OUTCOME_WINDOW = "outside_outcome_window"
    RELEASE_MISMATCH = "release_mismatch"
    INTERVENING_CHANGES = "intervening_changes"


@dataclass(frozen=True, slots=True)
class RuntimeQualificationInput:
    """Supplied Watch Runtime outcome plus the Performance correlation context."""
    prompt_run_id: str
    episode_id: str
    release_id: str
    deployment_id: str
    outcome: OutcomeReference
    window: OutcomeWindow
    telemetry_complete: bool
    sampling_fraction: float | None
    intervening_changes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.prompt_run_id.strip(), self.episode_id.strip(), self.release_id.strip(), self.deployment_id.strip())):
            raise ValueError("runtime qualification requires prompt, episode, release, and deployment identities")
        if self.outcome.provider is not OutcomeProvider.RUNTIME:
            raise ValueError("runtime qualification accepts Watch Runtime outcomes only")
        if self.sampling_fraction is not None and not 0 < self.sampling_fraction <= 1:
            raise ValueError("sampling fraction must be within (0, 1]")


@dataclass(frozen=True, slots=True)
class RuntimeQualification:
    input: RuntimeQualificationInput
    state: WatchQualificationState
    association: OutcomeAssociation | None
    failures: tuple[RuntimeFailure, ...]
    claim_kind: ClaimKind
    uncertainty: str


def qualify_runtime(value: RuntimeQualificationInput) -> RuntimeQualification:
    """Correlate a supplied Watch Runtime outcome without asserting causation."""
    failures: list[RuntimeFailure] = []
    if not value.telemetry_complete or value.sampling_fraction is None:
        failures.append(RuntimeFailure.MISSING_TELEMETRY)
    elif value.sampling_fraction < 1:
        failures.append(RuntimeFailure.SAMPLED_TELEMETRY)
    if value.window.release_id != value.release_id:
        failures.append(RuntimeFailure.RELEASE_MISMATCH)
    if not value.window.contains(value.outcome):
        failures.append(RuntimeFailure.OUTSIDE_OUTCOME_WINDOW)
    if value.intervening_changes:
        failures.append(RuntimeFailure.INTERVENING_CHANGES)
    rejected = {RuntimeFailure.RELEASE_MISMATCH, RuntimeFailure.OUTSIDE_OUTCOME_WINDOW} & set(failures)
    state = WatchQualificationState.REJECTED if rejected else WatchQualificationState.DEGRADED if failures else WatchQualificationState.QUALIFIED
    association = None
    if not rejected:
        confidence = .8 if not failures else .4
        evidence = (f"episode:{value.episode_id}", f"release:{value.release_id}", f"deployment:{value.deployment_id}", f"watch-runtime:{value.outcome.external_id}")
        association = OutcomeAssociation(value.prompt_run_id, value.outcome, AssociationKind.RUNTIME_ISSUE, "watch-runtime-window", _VERSION, confidence, evidence, value.intervening_changes, "time/release correlation only; Watch Runtime remains authoritative for the outcome")
    return RuntimeQualification(value, state, association, tuple(failures), ClaimKind.INFERRED if association else ClaimKind.UNKNOWN, "sampling, missing telemetry, release identity, and intervening changes limit correlation; this does not establish causation or mutate Watch Runtime")


class DataFailure(str, Enum):
    PERMISSION_MISSING = "permission_missing"
    INCOMPLETE_TELEMETRY = "incomplete_telemetry"
    WORKLOAD_MISMATCH = "workload_mismatch"
    INTERVENING_MIGRATION = "intervening_migration"
    STALE_REFERENCE = "stale_reference"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    MISSING_EVIDENCE = "missing_evidence"


@dataclass(frozen=True, slots=True)
class WatchDataEvidence:
    """Explicit Watch Data reference bundle; never a database connection."""
    schema: ExternalReference
    access: ExternalReference | None
    query: ExternalReference | None
    runtime: ExternalReference | None
    cost: ExternalReference | None
    regression: ExternalReference | None
    verification: ExternalReference | None
    access_granted: bool
    telemetry_complete: bool
    expected_workload: str
    observed_workload: str | None
    expected_schema_version: int
    reported_schema_version: int | None
    intervening_migration: ExternalReference | None = None
    stale_references: tuple[ExternalReference, ...] = ()

    def __post_init__(self) -> None:
        refs = (self.schema, self.access, self.query, self.runtime, self.cost, self.regression, self.verification, self.intervening_migration, *self.stale_references)
        if any(reference is not None and reference.provider != _DATA for reference in refs):
            raise ValueError("Watch Data evidence must use watch-data external references")
        if not self.expected_workload.strip() or self.expected_schema_version < 1:
            raise ValueError("expected workload and positive schema version are required")
        if self.reported_schema_version is not None and self.reported_schema_version < 1:
            raise ValueError("reported schema version must be positive")


@dataclass(frozen=True, slots=True)
class DataQualification:
    evidence: WatchDataEvidence
    state: WatchQualificationState
    accepted_references: tuple[ExternalReference, ...]
    failures: tuple[DataFailure, ...]
    claim_kind: ClaimKind
    uncertainty: str


def qualify_data(value: WatchDataEvidence) -> DataQualification:
    """Validate only reference completeness and compatibility, never database truth."""
    failures: list[DataFailure] = []
    required = (value.access, value.query, value.runtime, value.cost, value.regression, value.verification)
    if not value.access_granted: failures.append(DataFailure.PERMISSION_MISSING)
    if not value.telemetry_complete: failures.append(DataFailure.INCOMPLETE_TELEMETRY)
    if any(item is None for item in required): failures.append(DataFailure.MISSING_EVIDENCE)
    if value.observed_workload != value.expected_workload: failures.append(DataFailure.WORKLOAD_MISMATCH)
    if value.reported_schema_version != value.expected_schema_version: failures.append(DataFailure.SCHEMA_VERSION_MISMATCH)
    if value.intervening_migration is not None: failures.append(DataFailure.INTERVENING_MIGRATION)
    if value.stale_references: failures.append(DataFailure.STALE_REFERENCE)
    rejected = DataFailure.PERMISSION_MISSING in failures
    state = WatchQualificationState.REJECTED if rejected else WatchQualificationState.DEGRADED if failures else WatchQualificationState.QUALIFIED
    refs = tuple(item for item in (value.schema, *required, value.intervening_migration, *value.stale_references) if item is not None)
    return DataQualification(value, state, refs, tuple(failures), ClaimKind.DERIVED if not rejected else ClaimKind.UNKNOWN, "reference compatibility only: Watch Data remains authoritative for schema, access, query, runtime, cost, regression, and verification truth")
