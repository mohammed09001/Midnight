"""Qualified ambiguity, conflict, and missing-oracle analysis over intent contracts."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import re
from .contracts import ClaimKind
from .intent_contract import IntentContract, IntentElement, IntentKind, SourceSpan

AMBIGUITY_ANALYSIS_VERSION = "1"
class AmbiguityKind(str, Enum):
    UNRESOLVED_REFERENT = "unresolved_referent"; CONFLICT = "conflict"; MISSING_ACCEPTANCE = "missing_acceptance"; MISSING_VERIFICATION_ORACLE = "missing_verification_oracle"; UNDERSPECIFIED_SCOPE = "underspecified_scope"; REPOSITORY_CONTEXT = "repository_context"
class ResolutionStatus(str, Enum): OPEN = "open"; RESOLVED = "resolved"; CHANGED_BY_STEERING = "changed_by_steering"
@dataclass(frozen=True, slots=True)
class AmbiguityFinding:
    kind: AmbiguityKind; element_ids: tuple[str, ...]; spans: tuple[SourceSpan, ...]; message: str; claim_kind: ClaimKind; status: ResolutionStatus = ResolutionStatus.OPEN; repository_evidence: tuple[str, ...] = (); uncertainty: str = "deterministic analysis; context may change interpretation"
@dataclass(frozen=True, slots=True)
class MinimumInformationNeed:
    finding_kind: AmbiguityKind; needed: str; blocking: bool = False
@dataclass(frozen=True, slots=True)
class AmbiguityReport:
    version: str; findings: tuple[AmbiguityFinding, ...]; minimum_information: tuple[MinimumInformationNeed, ...]

_REFERENTS = re.compile(r"\b(this|that|it|they|them|those)\b", re.I)
def analyze_ambiguity(contract: IntentContract, *, repository_resolutions: dict[str, tuple[str, ...]] | None = None, steering_resolved: frozenset[str] = frozenset()) -> AmbiguityReport:
    repository_resolutions = repository_resolutions or {}; findings: list[AmbiguityFinding] = []
    elements = contract.elements
    for index, item in enumerate(elements):
        if _REFERENTS.search(item.text) and not any(previous.kind is IntentKind.REFERENCE for previous in elements[:index]):
            status = ResolutionStatus.CHANGED_BY_STEERING if item.id in steering_resolved else ResolutionStatus.OPEN
            evidence = repository_resolutions.get(item.id, ())
            if evidence: status = ResolutionStatus.RESOLVED
            findings.append(AmbiguityFinding(AmbiguityKind.UNRESOLVED_REFERENT, (item.id,), (item.span,), "referent has no deterministic antecedent", ClaimKind.DERIVED, status, evidence))
    constraints = [item for item in elements if item.kind is IntentKind.CONSTRAINT]
    for left_index, left in enumerate(constraints):
        for right in constraints[left_index + 1:]:
            words = set(re.findall(r"[a-z]{4,}", left.text.lower())) & set(re.findall(r"[a-z]{4,}", right.text.lower()))
            opposite = ("do not" in left.text.lower()) != ("do not" in right.text.lower())
            if words and opposite:
                findings.append(AmbiguityFinding(AmbiguityKind.CONFLICT, (left.id, right.id), (left.span, right.span), "constraints share subject terms with opposing polarity", ClaimKind.DERIVED))
    goals = [item for item in elements if item.kind is IntentKind.GOAL]
    has_acceptance = any(item.kind is IntentKind.ACCEPTANCE for item in elements)
    has_verification = any(item.kind is IntentKind.VERIFICATION for item in elements)
    if goals and not has_acceptance:
        findings.append(AmbiguityFinding(AmbiguityKind.MISSING_ACCEPTANCE, tuple(item.id for item in goals), tuple(item.span for item in goals), "goals have no explicit acceptance condition", ClaimKind.UNKNOWN))
    if goals and not has_verification:
        findings.append(AmbiguityFinding(AmbiguityKind.MISSING_VERIFICATION_ORACLE, tuple(item.id for item in goals), tuple(item.span for item in goals), "goals have no explicit verification oracle", ClaimKind.UNKNOWN))
    needs = tuple(MinimumInformationNeed(item.kind, item.message) for item in findings if item.status is ResolutionStatus.OPEN)
    return AmbiguityReport(AMBIGUITY_ANALYSIS_VERSION, tuple(findings), needs)
