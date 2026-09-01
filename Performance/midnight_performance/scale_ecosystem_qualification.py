"""Evidence gates for scale/recovery and full reference-only ecosystem loops."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ScaleRecoveryEvidence:
    measured_workloads: tuple[str, ...]; cost_measured: bool; scale_decision_evidence: bool
    process_crash_recovered: bool; missing_hooks_degraded: bool; siblings_unavailable_degraded: bool
    queue_storage_recovered: bool; partial_migration_recovered: bool; projections_rebuilt: bool; model_failure_recovered: bool

@dataclass(frozen=True, slots=True)
class ScaleRecoveryQualification:
    evidence: ScaleRecoveryEvidence; qualified: bool; failures: tuple[str, ...]
    uncertainty: str = "measurements apply only to supplied workloads and recovery exercises; no capacity claim is inferred without them"

def qualify_scale_recovery(value: ScaleRecoveryEvidence) -> ScaleRecoveryQualification:
    failures = []
    if not value.measured_workloads: failures.append("no_benchmarked_workloads")
    for name in value.__dataclass_fields__:
        if name != "measured_workloads" and not getattr(value, name): failures.append(name)
    return ScaleRecoveryQualification(value, not failures, tuple(failures))

@dataclass(frozen=True, slots=True)
class EcosystemEvidence:
    prompt_run: bool; change_set: bool; verification: bool; release_deployment: bool
    sibling_outcome_reference: bool; security_reference_when_applicable: bool; episode_memory_update: bool
    stable_references: bool; independent_failure_domains: bool; explicit_degraded_behavior: bool
    no_direct_sibling_database_reads: bool; orchestration_capability_only: bool

@dataclass(frozen=True, slots=True)
class EcosystemQualification:
    evidence: EcosystemEvidence; qualified: bool; failures: tuple[str, ...]
    uncertainty: str = "the loop correlates versioned references; Watch and Security remain authoritative and independent"

def qualify_ecosystem(value: EcosystemEvidence) -> EcosystemQualification:
    failures = tuple(name for name in value.__dataclass_fields__ if not getattr(value, name))
    return EcosystemQualification(value, not failures, failures)
