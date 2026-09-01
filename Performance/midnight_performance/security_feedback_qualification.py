"""Qualification projections for Security references and revisable user feedback.

Inputs are supplied references/records.  These projections neither query nor
copy Security findings, and never turn a user label into unquestioned truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .associations import AssociationKind, OutcomeAssociation
from .contracts import ClaimKind
from .feedback import FeedbackRecord
from .learning import MultiSignalLabel, QuestionCandidate, select_question
from .outcomes import OutcomeProvider, OutcomeReference

_VERSION = "1"


class SecurityFeedbackQualificationState(str, Enum):
    QUALIFIED = "qualified"
    DEGRADED = "degraded"
    REJECTED = "rejected"


class SecurityFailure(str, Enum):
    SECURITY_UNAVAILABLE = "security_unavailable"
    MULTIPLE_CANDIDATE_CHANGE_SETS = "multiple_candidate_change_sets"
    FAILED_REMEDIATION = "failed_remediation"
    FINDING_REINTRODUCED = "finding_reintroduced"
    REMEDIATION_UNCONFIRMED = "remediation_unconfirmed"


@dataclass(frozen=True, slots=True)
class SecurityQualificationInput:
    prompt_run_id: str
    episode_id: str
    finding: OutcomeReference
    candidate_change_set_ids: tuple[str, ...]
    remediation: OutcomeReference | None
    failed_verification_ids: tuple[str, ...] = ()
    finding_reintroduced: bool = False
    security_available: bool = True

    def __post_init__(self) -> None:
        if not self.prompt_run_id.strip() or not self.episode_id.strip():
            raise ValueError("security qualification requires prompt run and episode identities")
        if self.finding.provider is not OutcomeProvider.SECURITY:
            raise ValueError("security qualification requires a Security finding reference")
        if self.remediation is not None and self.remediation.provider is not OutcomeProvider.SECURITY:
            raise ValueError("Security must authoritatively report remediation outcomes")
        if len(set(self.candidate_change_set_ids)) != len(self.candidate_change_set_ids):
            raise ValueError("candidate change-set ids must be unique")


@dataclass(frozen=True, slots=True)
class SecurityDevelopmentContext:
    """Bounded, reference-only history that can be passed back to Security."""
    episode_id: str
    prompt_run_id: str
    change_set_ids: tuple[str, ...]
    truncated: bool
    claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = "bounded development-history context; it is not a Security finding or remediation verdict"


def bounded_security_context(value: SecurityQualificationInput, *, maximum_change_sets: int = 20) -> SecurityDevelopmentContext:
    if maximum_change_sets < 1:
        raise ValueError("maximum change sets must be positive")
    ids = value.candidate_change_set_ids[:maximum_change_sets]
    return SecurityDevelopmentContext(value.episode_id, value.prompt_run_id, ids, len(value.candidate_change_set_ids) > len(ids))


@dataclass(frozen=True, slots=True)
class SecurityQualification:
    input: SecurityQualificationInput
    state: SecurityFeedbackQualificationState
    association: OutcomeAssociation | None
    context: SecurityDevelopmentContext
    failures: tuple[SecurityFailure, ...]
    claim_kind: ClaimKind
    uncertainty: str


def qualify_security(value: SecurityQualificationInput, *, maximum_context_change_sets: int = 20) -> SecurityQualification:
    """Link Security-owned references to an episode without asserting Security truth."""
    failures: list[SecurityFailure] = []
    if not value.security_available: failures.append(SecurityFailure.SECURITY_UNAVAILABLE)
    if len(value.candidate_change_set_ids) > 1: failures.append(SecurityFailure.MULTIPLE_CANDIDATE_CHANGE_SETS)
    if value.failed_verification_ids: failures.append(SecurityFailure.FAILED_REMEDIATION)
    if value.finding_reintroduced: failures.append(SecurityFailure.FINDING_REINTRODUCED)
    if value.remediation is None or value.remediation.kind != "remediation_verified": failures.append(SecurityFailure.REMEDIATION_UNCONFIRMED)
    rejected = SecurityFailure.SECURITY_UNAVAILABLE in failures
    state = SecurityFeedbackQualificationState.REJECTED if rejected else SecurityFeedbackQualificationState.DEGRADED if failures else SecurityFeedbackQualificationState.QUALIFIED
    association = None
    if not rejected:
        evidence = (f"episode:{value.episode_id}", f"security:{value.finding.external_id}", *(f"change:{item}" for item in value.candidate_change_set_ids), *(f"verification:{item}" for item in value.failed_verification_ids))
        association = OutcomeAssociation(value.prompt_run_id, value.finding, AssociationKind.SECURITY, "security-episode-link", _VERSION, .8 if not failures else .4, evidence, (), "Security remains authoritative for finding/remediation state; this is a non-causal development-history correlation")
    return SecurityQualification(value, state, association, bounded_security_context(value, maximum_change_sets=maximum_context_change_sets), tuple(failures), ClaimKind.INFERRED if association else ClaimKind.UNKNOWN, "multiple candidates, failed remediation, reintroduction, absence, and downtime prevent Performance from claiming Security outcome truth")


class FeedbackFailure(str, Enum):
    NO_FEEDBACK = "no_feedback"
    MISSING_REVISION_TARGET = "missing_revision_target"
    CROSS_RUN_REVISION = "cross_run_revision"
    REVISION_CYCLE = "revision_cycle"
    SIGNAL_DISAGREEMENT = "signal_disagreement"


@dataclass(frozen=True, slots=True)
class FeedbackQualification:
    prompt_run_id: str
    current_feedback: tuple[FeedbackRecord, ...]
    active_question: QuestionCandidate | None
    disagreements: tuple[MultiSignalLabel, ...]
    failures: tuple[FeedbackFailure, ...]
    state: SecurityFeedbackQualificationState
    claim_kind: ClaimKind
    uncertainty: str


def qualify_feedback(prompt_run_id: str, records: tuple[FeedbackRecord, ...], candidates: tuple[QuestionCandidate, ...] = (), signals: tuple[MultiSignalLabel, ...] = (), *, threshold: float = .5) -> FeedbackQualification:
    """Check revision lineage and surface labels as observations, never ground truth."""
    if not prompt_run_id.strip():
        raise ValueError("prompt run id is required")
    relevant = tuple(record for record in records if record.prompt_run_id == prompt_run_id)
    by_id = {record.id: record for record in records}
    failures: list[FeedbackFailure] = []
    if not relevant: failures.append(FeedbackFailure.NO_FEEDBACK)
    for record in relevant:
        if record.revises_id is None: continue
        parent = by_id.get(record.revises_id)
        if parent is None:
            failures.append(FeedbackFailure.MISSING_REVISION_TARGET); continue
        if parent.prompt_run_id != prompt_run_id:
            failures.append(FeedbackFailure.CROSS_RUN_REVISION)
    for record in relevant:
        seen: set[str] = set(); cursor = record
        while cursor.revises_id is not None and cursor.revises_id in by_id:
            if cursor.id in seen:
                failures.append(FeedbackFailure.REVISION_CYCLE); break
            seen.add(cursor.id); cursor = by_id[cursor.revises_id]
    disagreement = tuple(signal for signal in signals if signal.disagreement)
    if disagreement: failures.append(FeedbackFailure.SIGNAL_DISAGREEMENT)
    current = tuple(sorted((record for record in relevant if not any(other.revises_id == record.id for other in relevant)), key=lambda item: (item.submitted_at, item.id)))
    question = select_question(tuple(item for item in candidates if item.prompt_run_id == prompt_run_id), threshold)
    unique_failures = tuple(dict.fromkeys(failures))
    state = SecurityFeedbackQualificationState.DEGRADED if unique_failures else SecurityFeedbackQualificationState.QUALIFIED
    return FeedbackQualification(prompt_run_id, current, question, disagreement, unique_failures, state, ClaimKind.DERIVED if relevant else ClaimKind.UNKNOWN, "feedback is a revisable user observation; disagreement and uncertainty remain visible and no label is treated as ground truth")
