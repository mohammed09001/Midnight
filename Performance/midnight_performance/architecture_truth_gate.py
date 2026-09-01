"""Final explicit architecture and product-truth audit gate."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ArchitectureTruthEvidence:
    repository_evidence_over_prose: bool; vcs_filesystem_changes_grounded: bool; no_midnight_code_required: bool
    no_graphrag_required: bool; does_not_host_agents: bool; passive_capture_no_prompt_rewrite: bool
    siblings_authoritative: bool; data_science_before_ml: bool; vector_graphs_rebuildable: bool
    memory_provenance_backed: bool; advisor_user_controlled: bool; orchestration_capability_only: bool
    independently_useful_without_siblings_ai_graphrag: bool; self_hosted_or_byoc: bool; degraded_failure_accounting: bool

@dataclass(frozen=True, slots=True)
class ArchitectureTruthGate:
    evidence: ArchitectureTruthEvidence; passed: bool; failures: tuple[str, ...]
    uncertainty: str = "this is a final contract audit over supplied verification evidence; external environments remain independently testable"

def audit_architecture_truth(value: ArchitectureTruthEvidence) -> ArchitectureTruthGate:
    failures = tuple(name for name in value.__dataclass_fields__ if not getattr(value, name))
    return ArchitectureTruthGate(value, not failures, failures)
