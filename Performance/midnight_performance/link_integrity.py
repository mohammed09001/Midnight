"""Deterministic validation of derived Performance relationships.

This validator reports evidence; it never changes records or attempts to infer
missing links.  Callers supply project/run scope because the component
projections intentionally do not own a global cross-project store.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .behavior_analysis import BehaviorContract
from .decision_story import DecisionStory
from .traceability import CodeElement, RequirementUnit, TraceLink, TraceState
from .trajectory import Trajectory
from .verification_intelligence import BehaviorVerificationEvidence

LINK_INTEGRITY_VERSION = "1"

class IntegritySeverity(str, Enum): INFO = "info"; WARNING = "warning"; ERROR = "error"
class IntegrityMode(str, Enum): DIAGNOSTIC = "diagnostic"; STRICT = "strict"

@dataclass(frozen=True, slots=True)
class LinkIntegrityFinding:
    kind: str; severity: IntegritySeverity; subject_id: str; reference_id: str | None
    evidence: tuple[str, ...]; qualified_historical: bool; uncertainty: str

@dataclass(frozen=True, slots=True)
class LinkIntegrityReport:
    project_id: str; run_id: str; mode: IntegrityMode; findings: tuple[LinkIntegrityFinding, ...]
    version: str = LINK_INTEGRITY_VERSION

    @property
    def qualifies(self) -> bool:
        return not any(item.severity is IntegritySeverity.ERROR for item in self.findings)

def validate_link_integrity(*, project_id: str, run_id: str, requirement_units: tuple[RequirementUnit, ...],
                            code_elements: tuple[CodeElement, ...], trace_links: tuple[TraceLink, ...],
                            behavior: BehaviorContract | None = None,
                            verification: tuple[BehaviorVerificationEvidence, ...] = (),
                            trajectory: Trajectory | None = None, story: DecisionStory | None = None,
                            reference_projects: dict[str, str] | None = None,
                            historical_requirement_ids: frozenset[str] = frozenset(),
                            mode: IntegrityMode = IntegrityMode.DIAGNOSTIC) -> LinkIntegrityReport:
    """Validate current links and qualify, rather than erase, historical ones."""
    if not project_id.strip() or not run_id.strip():
        raise ValueError("project and run identities are required")
    reference_projects = reference_projects or {}
    findings: list[LinkIntegrityFinding] = []
    requirement_ids = {unit.id for unit in requirement_units}
    code_ids = {element.id for element in code_elements}
    clauses = {clause.id: clause for clause in behavior.clauses} if behavior else {}

    def finding(kind: str, severity: IntegritySeverity, subject: str, reference: str | None, evidence: tuple[str, ...], historical: bool, uncertainty: str) -> None:
        findings.append(LinkIntegrityFinding(kind, severity, subject, reference, evidence, historical, uncertainty))

    def cross_project(subject: str, reference: str | None) -> None:
        if reference and reference_projects.get(reference) not in (None, project_id):
            finding("cross_project_reference", IntegritySeverity.ERROR, subject, reference, (f"project:{reference_projects[reference]}",), False, "references must remain within the caller-supplied project scope")

    if behavior and behavior.project_id != project_id:
        finding("cross_project_behavior_contract", IntegritySeverity.ERROR, "behavior-contract", behavior.project_id, (f"project:{behavior.project_id}",), False, "behavior contract project differs from validation scope")
    if trajectory and trajectory.run_id != run_id:
        finding("cross_run_trajectory", IntegritySeverity.ERROR, trajectory.run_id, run_id, (), False, "trajectory belongs to a different run")
    if story and story.run_id != run_id:
        finding("cross_run_decision_story", IntegritySeverity.ERROR, story.run_id, run_id, (), False, "decision story belongs to a different run")

    for link in trace_links:
        cross_project(link.code_element_id, link.requirement_id)
        if link.requirement_id is not None and link.requirement_id not in requirement_ids:
            historical = link.state in {TraceState.STALE, TraceState.SUPERSEDED} and link.requirement_id in historical_requirement_ids
            severity = IntegritySeverity.WARNING if historical else IntegritySeverity.ERROR
            finding("historical_requirement_reference" if historical else "dangling_requirement", severity, link.code_element_id, link.requirement_id, link.evidence, historical, "stale/superseded records are retained only when supplied historical identity evidence exists" if historical else "current trace link references no supplied canonical RequirementUnit")
        if link.code_element_id not in code_ids and link.state not in {TraceState.STALE, TraceState.SUPERSEDED}:
            finding("dangling_code_element", IntegritySeverity.ERROR, link.requirement_id or "unrequested", link.code_element_id, link.evidence, False, "current trace link references no supplied code element")

    for clause in clauses.values():
        cross_project(clause.id, clause.requirement_id)
        if clause.requirement_id is not None and clause.requirement_id not in requirement_ids:
            finding("dangling_clause_requirement", IntegritySeverity.ERROR, clause.id, clause.requirement_id, clause.evidence, False, "behavior clause must name a current canonical RequirementUnit id")
        if clause.requirement_id is not None:
            matching = next((unit for unit in requirement_units if unit.id == clause.requirement_id), None)
            if matching and clause.intent_element_id != matching.intent_element_id:
                finding("clause_provenance_mismatch", IntegritySeverity.ERROR, clause.id, clause.requirement_id, clause.evidence, False, "clause source provenance does not match its canonical requirement")

    for item in verification:
        if item.clause_id is not None and item.clause_id not in clauses:
            finding("dangling_verification_clause", IntegritySeverity.ERROR, item.id, item.clause_id, item.provenance, False, "verification evidence references no behavior clause in this contract")
        cross_project(item.id, item.clause_id)
    if story:
        for item in story.matrix:
            if item.requirement_id is not None and item.requirement_id not in requirement_ids:
                finding("dangling_story_requirement", IntegritySeverity.ERROR, item.evidence_id, item.requirement_id, (item.evidence_id,), False, "decision-story matrix references no current canonical requirement")
            cross_project(item.evidence_id, item.requirement_id)
    if trajectory:
        event_ids = {event.id for event in trajectory.events}
        for event in trajectory.events:
            if event.parent_id and event.parent_id not in event_ids:
                finding("dangling_trajectory_parent", IntegritySeverity.WARNING, event.id, event.parent_id, (event.evidence_id,), False, "trajectory already records ordering uncertainty; missing parent is diagnostic")
            cross_project(event.id, event.parent_id)
    if mode is IntegrityMode.STRICT:
        findings = [item if item.severity is not IntegritySeverity.WARNING else LinkIntegrityFinding(item.kind, IntegritySeverity.ERROR, item.subject_id, item.reference_id, item.evidence, item.qualified_historical, item.uncertainty) for item in findings if not item.qualified_historical]
    return LinkIntegrityReport(project_id, run_id, mode, tuple(findings))
