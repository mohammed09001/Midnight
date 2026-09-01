"""Qualification gates for advisory usefulness and security/isolation test evidence."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdvisorQualificationEvidence:
    held_out_improved: bool; controlled_improved: bool; opt_in_real_use: bool
    user_relevant_outcome_improved: bool; internal_metric_improved: bool
    recommendation_count: int

@dataclass(frozen=True, slots=True)
class AdvisorQualification:
    evidence: AdvisorQualificationEvidence; qualified: bool; failures: tuple[str, ...]
    uncertainty: str = "recommendations remain optional, explainable suggestions; observed benefit is limited to supplied held-out, controlled, and opt-in evidence"

def qualify_advisor(value: AdvisorQualificationEvidence) -> AdvisorQualification:
    failures = []
    if value.recommendation_count < 1: failures.append("no_recommendations_evaluated")
    if not value.held_out_improved: failures.append("held_out_usefulness_unproven")
    if not value.controlled_improved: failures.append("controlled_usefulness_unproven")
    if not value.opt_in_real_use: failures.append("opt_in_real_use_unproven")
    if not value.user_relevant_outcome_improved: failures.append("user_relevant_outcome_unimproved")
    if value.internal_metric_improved and not value.user_relevant_outcome_improved: failures.append("internal_metric_optimization_only")
    return AdvisorQualification(value, not failures, tuple(failures))


@dataclass(frozen=True, slots=True)
class SecurityIsolationEvidence:
    tenant_project_isolation: bool; privacy: bool; poisoning: bool; prompt_injection: bool
    forged_evidence: bool; hook_plugin_tampering: bool; credential: bool; deletion: bool
    malicious_payload: bool; transcript: bool; dataset_model: bool; mcp: bool; ai_provider: bool
    cross_product_contract: bool; siblings_absent_usable: bool

@dataclass(frozen=True, slots=True)
class SecurityIsolationQualification:
    evidence: SecurityIsolationEvidence; qualified: bool; failures: tuple[str, ...]
    uncertainty: str = "this records executed control evidence; host, provider, and sibling-system security remain external boundaries"

def qualify_security_isolation(value: SecurityIsolationEvidence) -> SecurityIsolationQualification:
    missing = tuple(name for name in value.__dataclass_fields__ if not getattr(value, name))
    return SecurityIsolationQualification(value, not missing, missing)
