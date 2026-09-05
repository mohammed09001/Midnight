"""Typed, versioned contracts for Repo Intelligent derived state.

Every record is project-scoped, carries provenance and uncertainty, and
never upgrades claim strength.  Serialization is deterministic and
fail-closed: unknown fields and unsupported schema versions are rejected
on read.  Records own no persistence and open no sibling databases.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from ..contracts import ClaimKind, EntityKind, ExternalReference, Identity
from .identities import (
    REPO_INTELLIGENCE_CONTRACT_VERSION,
    RepoIdentity,
    RepoIntelligenceKind,
    deterministic_repo_identity,
    is_performance_canonical,
    is_repo_intelligence_canonical,
)
from .sources import (
    AUTHORITATIVE_TRUST,
    DEFAULT_SOURCE_TRUST,
    EXTERNAL_SOURCE_CLASSES,
    EXTERNAL_TEXT_POLICY,
    EvidenceSide,
    Freshness,
    SourceClass,
    TrustClass,
    SOURCE_SIDE,
)

_MAX_SUMMARY_CHARS = 280
_MAX_STATEMENT_CHARS = 500
_MAX_QUESTION_CHARS = 500
_HEX_DIGEST_CHARS = 64

_PRIVACY_DECISIONS = frozenset({"local_only", "abstracted_external", "denied"})


class UnsupportedSchemaVersionError(ValueError):
    """A record was written by an incompatible schema version."""

    def __init__(self, record_type: str, found: object, supported: int) -> None:
        super().__init__(
            f"{record_type}: schema version {found!r} is not supported (supported: {supported})"
        )
        self.record_type = record_type
        self.found = found
        self.supported = supported


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _require_schema_version(raw: Mapping[str, Any], record_type: str) -> None:
    found = raw.get("schema_version")
    if found != REPO_INTELLIGENCE_CONTRACT_VERSION:
        raise UnsupportedSchemaVersionError(record_type, found, REPO_INTELLIGENCE_CONTRACT_VERSION)


def _reject_unknown_fields(raw: Mapping[str, Any], known: frozenset[str], record_type: str) -> None:
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"{record_type}: unknown fields {unknown} (fail-closed)")


def _require_tz_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_non_blank(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


def _require_hex_digest(value: str, label: str) -> None:
    if len(value) != _HEX_DIGEST_CHARS or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase {_HEX_DIGEST_CHARS}-char hex digest")


def _require_confidence(value: float | None, label: str) -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be between zero and one")


def _parse_datetime(raw: Any, label: str) -> datetime:
    value = datetime.fromisoformat(raw)
    _require_tz_aware(value, label)
    return value


def _dump_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _dump_enum(value: Enum | None) -> str | None:
    return None if value is None else value.value


def _dump_identity(value: RepoIdentity | None) -> str | None:
    return None if value is None else value.canonical


def _require_kind(identity: RepoIdentity, kind: Any, label: str) -> None:
    if identity.kind is not kind:
        raise ValueError(f"{label} must be a {kind.value} identity")


def _require_canonical(raw: str, label: str) -> None:
    if not (is_performance_canonical(raw) or is_repo_intelligence_canonical(raw)):
        raise ValueError(f"{label} must be a canonical mp: or ri: identity")


def _require_performance_canonical(raw: str, label: str) -> None:
    if not is_performance_canonical(raw):
        raise ValueError(f"{label} must be a canonical mp: identity")


def _require_performance_project(identity: Identity, label: str) -> None:
    if identity.kind is not EntityKind.PROJECT:
        raise ValueError(f"{label} must be a Performance project identity")


def _content_digest_of(*parts: str) -> str:
    payload = json.dumps(list(parts), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_BUDGET_FIELDS = frozenset(
    {"max_model_calls", "max_network_requests", "max_cost_micros", "max_seconds"}
)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobTrigger(str, Enum):
    USER_PULL = "user_pull"
    PROACTIVE = "proactive"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True, slots=True)
class BudgetCeiling:
    """Per-job ceilings; at least one must be set, so no job is unbounded."""

    max_model_calls: int | None = None
    max_network_requests: int | None = None
    max_cost_micros: int | None = None
    max_seconds: float | None = None

    def __post_init__(self) -> None:
        for label, bound in (
            ("max_model_calls", self.max_model_calls),
            ("max_network_requests", self.max_network_requests),
            ("max_cost_micros", self.max_cost_micros),
            ("max_seconds", self.max_seconds),
        ):
            if bound is not None and bound < 0:
                raise ValueError(f"{label} must not be negative")
        if all(
            bound is None
            for bound in (
                self.max_model_calls,
                self.max_network_requests,
                self.max_cost_micros,
                self.max_seconds,
            )
        ):
            raise ValueError("budget ceilings require at least one bound")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_model_calls": self.max_model_calls,
            "max_network_requests": self.max_network_requests,
            "max_cost_micros": self.max_cost_micros,
            "max_seconds": self.max_seconds,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BudgetCeiling":
        _reject_unknown_fields(raw, _BUDGET_FIELDS, "BudgetCeiling")
        return cls(
            max_model_calls=raw.get("max_model_calls"),
            max_network_requests=raw.get("max_network_requests"),
            max_cost_micros=raw.get("max_cost_micros"),
            max_seconds=raw.get("max_seconds"),
        )


def project_intelligence_job_identity(
    project: Identity, job_kind: str, idempotency_key: str
) -> RepoIdentity:
    _require_performance_project(project, "project")
    _require_non_blank(job_kind, "job_kind")
    _require_non_blank(idempotency_key, "idempotency_key")
    return deterministic_repo_identity(
        RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB,
        f"{project.canonical}|{job_kind}|{idempotency_key}",
    )


@dataclass(frozen=True, slots=True)
class ProjectIntelligenceJob:
    """A replayable unit of project intelligence work with explicit stop conditions."""

    identity: RepoIdentity
    project: Identity
    job_kind: str
    idempotency_key: str
    trigger: JobTrigger
    status: JobStatus
    stop_condition: str
    budget: BudgetCeiling
    derivation_method: str
    derivation_version: str
    requested_at: datetime = field(default_factory=_now_utc)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    subject: str | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB, "identity")
        _require_performance_project(self.project, "project")
        _require_non_blank(self.job_kind, "job_kind")
        _require_non_blank(self.idempotency_key, "idempotency_key")
        _require_non_blank(self.stop_condition, "stop_condition")
        _require_non_blank(self.derivation_method, "derivation_method")
        _require_non_blank(self.derivation_version, "derivation_version")
        _require_tz_aware(self.requested_at, "requested_at")
        if self.status is not JobStatus.PENDING and self.started_at is None:
            raise ValueError("started_at is required once a job leaves pending")
        if self.status in (JobStatus.COMPLETED, JobStatus.FAILED) and self.completed_at is None:
            raise ValueError("completed_at is required for completed or failed jobs")
        if self.status is JobStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValueError("failure_reason is required for failed jobs")
        if self.status is not JobStatus.FAILED and self.failure_reason is not None:
            raise ValueError("failure_reason is only allowed on failed jobs")
        if self.subject is not None:
            _require_non_blank(self.subject, "subject")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "job_kind": self.job_kind,
            "idempotency_key": self.idempotency_key,
            "trigger": _dump_enum(self.trigger),
            "status": _dump_enum(self.status),
            "stop_condition": self.stop_condition,
            "budget": self.budget.to_dict(),
            "derivation_method": self.derivation_method,
            "derivation_version": self.derivation_version,
            "requested_at": _dump_datetime(self.requested_at),
            "started_at": _dump_datetime(self.started_at),
            "completed_at": _dump_datetime(self.completed_at),
            "failure_reason": self.failure_reason,
            "subject": self.subject,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProjectIntelligenceJob":
        _require_schema_version(raw, "ProjectIntelligenceJob")
        _reject_unknown_fields(raw, _JOB_FIELDS, "ProjectIntelligenceJob")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            job_kind=raw["job_kind"],
            idempotency_key=raw["idempotency_key"],
            trigger=JobTrigger(raw["trigger"]),
            status=JobStatus(raw["status"]),
            stop_condition=raw["stop_condition"],
            budget=BudgetCeiling.from_dict(raw["budget"]),
            derivation_method=raw["derivation_method"],
            derivation_version=raw["derivation_version"],
            requested_at=_parse_datetime(raw["requested_at"], "requested_at"),
            started_at=_parse_datetime(raw["started_at"], "started_at") if raw.get("started_at") else None,
            completed_at=_parse_datetime(raw["completed_at"], "completed_at") if raw.get("completed_at") else None,
            failure_reason=raw.get("failure_reason"),
            subject=raw.get("subject"),
            schema_version=raw["schema_version"],
        )


_JOB_FIELDS = frozenset(
    {
        "identity",
        "project",
        "job_kind",
        "idempotency_key",
        "trigger",
        "status",
        "stop_condition",
        "budget",
        "derivation_method",
        "derivation_version",
        "requested_at",
        "started_at",
        "completed_at",
        "failure_reason",
        "subject",
        "schema_version",
    }
)


class PressureDimension(str, Enum):
    """Independent learning-pressure dimensions; a prioritization aid, never quality."""

    ATTENTION = "attention"
    FRICTION = "friction"
    RECURRENCE = "recurrence"
    UNCERTAINTY = "uncertainty"
    IMPACT = "impact"
    KNOWLEDGE_DEFICIT = "knowledge_deficit"
    FRESHNESS = "freshness"


_SIGNAL_CLAIM_KINDS = frozenset(
    {
        ClaimKind.DERIVED,
        ClaimKind.INFERRED,
        ClaimKind.STATISTICAL,
        ClaimKind.PREDICTED,
        ClaimKind.UNKNOWN,
    }
)
_WEAK_CLAIM_KINDS = frozenset(
    {ClaimKind.INFERRED, ClaimKind.STATISTICAL, ClaimKind.PREDICTED}
)


@dataclass(frozen=True, slots=True)
class InternalSignal:
    """A bounded internal learning-need signal derived from project evidence."""

    identity: RepoIdentity
    project: Identity
    signal_kind: str
    dimensions: tuple[PressureDimension, ...]
    window_start: datetime
    window_end: datetime
    claim_kind: ClaimKind
    method: str
    method_version: str
    uncertainty: str
    summary: str
    performance_refs: tuple[str, ...] = ()
    entity_refs: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    confidence: float | None = None
    gaps: tuple[str, ...] = ()
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.INTERNAL_SIGNAL, "identity")
        _require_performance_project(self.project, "project")
        _require_non_blank(self.signal_kind, "signal_kind")
        if not self.dimensions:
            raise ValueError("internal signals require at least one pressure dimension")
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("signal window must be timezone-aware")
        if self.window_start > self.window_end:
            raise ValueError("signal window_start must not be after window_end")
        if self.claim_kind not in _SIGNAL_CLAIM_KINDS:
            raise ValueError("internal signals are projections and cannot carry observed or recommended claims")
        _require_non_blank(self.method, "method")
        _require_non_blank(self.method_version, "method_version")
        _require_non_blank(self.uncertainty, "uncertainty")
        _require_confidence(self.confidence, "confidence")
        if self.claim_kind in _WEAK_CLAIM_KINDS and self.confidence is None:
            raise ValueError("weak claim kinds require explicit confidence")
        if len(self.summary) > _MAX_SUMMARY_CHARS:
            raise ValueError(f"summary must not exceed {_MAX_SUMMARY_CHARS} chars")
        _require_non_blank(self.summary, "summary")
        for ref in self.performance_refs:
            _require_performance_canonical(ref, "performance_refs entry")
        for ref in self.entity_refs:
            if not is_repo_intelligence_canonical(ref):
                raise ValueError("entity_refs entries must be canonical ri: identities")
        for ref in self.evidence_ids:
            _require_canonical(ref, "evidence_ids entry")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "signal_kind": self.signal_kind,
            "dimensions": [d.value for d in self.dimensions],
            "window_start": _dump_datetime(self.window_start),
            "window_end": _dump_datetime(self.window_end),
            "claim_kind": _dump_enum(self.claim_kind),
            "method": self.method,
            "method_version": self.method_version,
            "uncertainty": self.uncertainty,
            "summary": self.summary,
            "performance_refs": list(self.performance_refs),
            "entity_refs": list(self.entity_refs),
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "gaps": list(self.gaps),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "InternalSignal":
        _require_schema_version(raw, "InternalSignal")
        _reject_unknown_fields(raw, _SIGNAL_FIELDS, "InternalSignal")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            signal_kind=raw["signal_kind"],
            dimensions=tuple(PressureDimension(d) for d in raw["dimensions"]),
            window_start=_parse_datetime(raw["window_start"], "window_start"),
            window_end=_parse_datetime(raw["window_end"], "window_end"),
            claim_kind=ClaimKind(raw["claim_kind"]),
            method=raw["method"],
            method_version=raw["method_version"],
            uncertainty=raw["uncertainty"],
            summary=raw["summary"],
            performance_refs=tuple(raw.get("performance_refs", ())),
            entity_refs=tuple(raw.get("entity_refs", ())),
            evidence_ids=tuple(raw.get("evidence_ids", ())),
            confidence=raw.get("confidence"),
            gaps=tuple(raw.get("gaps", ())),
            schema_version=raw["schema_version"],
        )


_SIGNAL_FIELDS = frozenset(
    {
        "identity",
        "project",
        "signal_kind",
        "dimensions",
        "window_start",
        "window_end",
        "claim_kind",
        "method",
        "method_version",
        "uncertainty",
        "summary",
        "performance_refs",
        "entity_refs",
        "evidence_ids",
        "confidence",
        "gaps",
        "schema_version",
    }
)


def internal_signal_identity(
    project: Identity, signal_kind: str, window_start: datetime, evidence_digest: str
) -> RepoIdentity:
    _require_performance_project(project, "project")
    _require_non_blank(signal_kind, "signal_kind")
    _require_tz_aware(window_start, "window_start")
    _require_non_blank(evidence_digest, "evidence_digest")
    return deterministic_repo_identity(
        RepoIntelligenceKind.INTERNAL_SIGNAL,
        f"{project.canonical}|{signal_kind}|{window_start.isoformat()}|{evidence_digest}",
    )


class ProjectEntityRefKind(str, Enum):
    REPOSITORY = "repository"
    PACKAGE = "package"
    MODULE = "module"
    FILE = "file"
    SYMBOL = "symbol"
    CODE_REGION = "code_region"
    TEST = "test"
    CONFIG = "config"
    DOC = "doc"


def project_entity_ref_identity(
    repository_key: str,
    ref_kind: ProjectEntityRefKind,
    path: str | None,
    qualified_name: str | None,
    resolver_tool: str,
    resolver_version: str,
) -> RepoIdentity:
    _require_non_blank(repository_key, "repository_key")
    _require_non_blank(resolver_tool, "resolver_tool")
    _require_non_blank(resolver_version, "resolver_version")
    if not (path or qualified_name):
        raise ValueError("project entity references require a path or a qualified name")
    stable_key = (
        f"{repository_key}|{ref_kind.value}|{path or ''}|{qualified_name or ''}"
        f"|{resolver_tool}:{resolver_version}"
    )
    return deterministic_repo_identity(RepoIntelligenceKind.PROJECT_ENTITY_REF, stable_key)


@dataclass(frozen=True, slots=True)
class ProjectEntityRef:
    """A stable reference to a repository entity across edits.

    Identity is deliberately content-independent (path/qualified-name plus
    resolver) so small edits keep the same reference; ``content_digest``
    records the last-seen content and ``rename_uncertainty`` carries the
    resolver's honest rename/move continuity note.
    """

    identity: RepoIdentity
    project: Identity
    ref_kind: ProjectEntityRefKind
    repository_key: str
    resolver_tool: str
    resolver_version: str
    first_seen_at: datetime
    last_seen_at: datetime
    path: str | None = None
    qualified_name: str | None = None
    content_digest: str | None = None
    rename_uncertainty: str | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.PROJECT_ENTITY_REF, "identity")
        _require_performance_project(self.project, "project")
        _require_non_blank(self.repository_key, "repository_key")
        _require_non_blank(self.resolver_tool, "resolver_tool")
        _require_non_blank(self.resolver_version, "resolver_version")
        if not (self.path or self.qualified_name):
            raise ValueError("project entity references require a path or a qualified name")
        if self.path is not None:
            _require_non_blank(self.path, "path")
        if self.qualified_name is not None:
            _require_non_blank(self.qualified_name, "qualified_name")
        if self.content_digest is not None:
            _require_hex_digest(self.content_digest, "content_digest")
        _require_tz_aware(self.first_seen_at, "first_seen_at")
        _require_tz_aware(self.last_seen_at, "last_seen_at")
        if self.first_seen_at > self.last_seen_at:
            raise ValueError("first_seen_at must not be after last_seen_at")
        if self.rename_uncertainty is not None:
            _require_non_blank(self.rename_uncertainty, "rename_uncertainty")
        expected = project_entity_ref_identity(
            self.repository_key,
            self.ref_kind,
            self.path,
            self.qualified_name,
            self.resolver_tool,
            self.resolver_version,
        )
        if self.identity != expected:
            raise ValueError("identity does not match the deterministic entity reference key")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "ref_kind": _dump_enum(self.ref_kind),
            "repository_key": self.repository_key,
            "resolver_tool": self.resolver_tool,
            "resolver_version": self.resolver_version,
            "first_seen_at": _dump_datetime(self.first_seen_at),
            "last_seen_at": _dump_datetime(self.last_seen_at),
            "path": self.path,
            "qualified_name": self.qualified_name,
            "content_digest": self.content_digest,
            "rename_uncertainty": self.rename_uncertainty,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProjectEntityRef":
        _require_schema_version(raw, "ProjectEntityRef")
        _reject_unknown_fields(raw, _ENTITY_REF_FIELDS, "ProjectEntityRef")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            ref_kind=ProjectEntityRefKind(raw["ref_kind"]),
            repository_key=raw["repository_key"],
            resolver_tool=raw["resolver_tool"],
            resolver_version=raw["resolver_version"],
            first_seen_at=_parse_datetime(raw["first_seen_at"], "first_seen_at"),
            last_seen_at=_parse_datetime(raw["last_seen_at"], "last_seen_at"),
            path=raw.get("path"),
            qualified_name=raw.get("qualified_name"),
            content_digest=raw.get("content_digest"),
            rename_uncertainty=raw.get("rename_uncertainty"),
            schema_version=raw["schema_version"],
        )


_ENTITY_REF_FIELDS = frozenset(
    {
        "identity",
        "project",
        "ref_kind",
        "repository_key",
        "resolver_tool",
        "resolver_version",
        "first_seen_at",
        "last_seen_at",
        "path",
        "qualified_name",
        "content_digest",
        "rename_uncertainty",
        "schema_version",
    }
)


def external_source_ref_identity(provider: str, locator: str, content_digest: str) -> RepoIdentity:
    _require_non_blank(provider, "provider")
    _require_non_blank(locator, "locator")
    _require_hex_digest(content_digest, "content_digest")
    return deterministic_repo_identity(
        RepoIntelligenceKind.EXTERNAL_SOURCE_REF,
        f"{provider}|{locator}|{content_digest}",
    )


@dataclass(frozen=True, slots=True)
class ExternalSourceRef:
    """A captured external source record: evidence, never trusted knowledge."""

    identity: RepoIdentity
    project: Identity
    source_class: SourceClass
    provider: str
    locator: str
    title: str
    content_digest: str
    captured_at: datetime
    retrieval_method: str
    retrieval_version: str
    published_at: datetime | None = None
    license: str | None = None
    trust_class: TrustClass | None = None
    uncertainty: str = EXTERNAL_TEXT_POLICY
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.EXTERNAL_SOURCE_REF, "identity")
        _require_performance_project(self.project, "project")
        if self.source_class not in EXTERNAL_SOURCE_CLASSES:
            raise ValueError("external source refs require an external source class")
        _require_non_blank(self.provider, "provider")
        _require_non_blank(self.locator, "locator")
        _require_non_blank(self.title, "title")
        _require_hex_digest(self.content_digest, "content_digest")
        _require_tz_aware(self.captured_at, "captured_at")
        if self.published_at is not None:
            _require_tz_aware(self.published_at, "published_at")
        _require_non_blank(self.retrieval_method, "retrieval_method")
        _require_non_blank(self.retrieval_version, "retrieval_version")
        _require_non_blank(self.uncertainty, "uncertainty")
        if self.trust_class is None:
            object.__setattr__(self, "trust_class", DEFAULT_SOURCE_TRUST[self.source_class])

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "source_class": _dump_enum(self.source_class),
            "provider": self.provider,
            "locator": self.locator,
            "title": self.title,
            "content_digest": self.content_digest,
            "captured_at": _dump_datetime(self.captured_at),
            "retrieval_method": self.retrieval_method,
            "retrieval_version": self.retrieval_version,
            "published_at": _dump_datetime(self.published_at),
            "license": self.license,
            "trust_class": _dump_enum(self.trust_class),
            "uncertainty": self.uncertainty,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ExternalSourceRef":
        _require_schema_version(raw, "ExternalSourceRef")
        _reject_unknown_fields(raw, _EXTERNAL_REF_FIELDS, "ExternalSourceRef")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            source_class=SourceClass(raw["source_class"]),
            provider=raw["provider"],
            locator=raw["locator"],
            title=raw["title"],
            content_digest=raw["content_digest"],
            captured_at=_parse_datetime(raw["captured_at"], "captured_at"),
            retrieval_method=raw["retrieval_method"],
            retrieval_version=raw["retrieval_version"],
            published_at=_parse_datetime(raw["published_at"], "published_at") if raw.get("published_at") else None,
            license=raw.get("license"),
            trust_class=TrustClass(raw["trust_class"]) if raw.get("trust_class") else None,
            uncertainty=raw.get("uncertainty", EXTERNAL_TEXT_POLICY),
            schema_version=raw["schema_version"],
        )


_EXTERNAL_REF_FIELDS = frozenset(
    {
        "identity",
        "project",
        "source_class",
        "provider",
        "locator",
        "title",
        "content_digest",
        "captured_at",
        "retrieval_method",
        "retrieval_version",
        "published_at",
        "license",
        "trust_class",
        "uncertainty",
        "schema_version",
    }
)


class InternalAnswerStatus(str, Enum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    ABSENT = "absent"


class QuestionStatus(str, Enum):
    OPEN = "open"
    RESEARCHING = "researching"
    ANSWERED_INTERNAL = "answered_internal"
    ANSWERED_EXTERNAL = "answered_external"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


_ACTIVE_QUESTION_STATUSES = frozenset({QuestionStatus.OPEN, QuestionStatus.RESEARCHING})


@dataclass(frozen=True, slots=True)
class ResearchQuestion:
    """A privacy-minimized research question compiled from Performance evidence.

    Every compiler field is required; a question that cannot state why now,
    what triggered it, what is already known, what is unknown, what external
    evidence would change the answer, its stop condition, and its budget is
    not eligible to launch research.
    """

    identity: RepoIdentity
    project: Identity
    question_text: str
    privacy_minimized: bool
    why_now: str
    triggered_by: tuple[str, ...]
    what_is_already_known: str
    what_is_unknown: str
    what_external_evidence_would_change: str
    stop_condition: str
    budget: BudgetCeiling
    internal_answer_status: InternalAnswerStatus
    dedup_key: str
    status: QuestionStatus
    created_at: datetime
    internal_answer_refs: tuple[str, ...] = ()
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.RESEARCH_QUESTION, "identity")
        _require_performance_project(self.project, "project")
        _require_non_blank(self.question_text, "question_text")
        if len(self.question_text) > _MAX_QUESTION_CHARS:
            raise ValueError(f"question_text must not exceed {_MAX_QUESTION_CHARS} chars")
        if not self.privacy_minimized:
            raise ValueError("research questions must be privacy-minimized")
        for label, value in (
            ("why_now", self.why_now),
            ("what_is_already_known", self.what_is_already_known),
            ("what_is_unknown", self.what_is_unknown),
            ("what_external_evidence_would_change", self.what_external_evidence_would_change),
            ("stop_condition", self.stop_condition),
            ("dedup_key", self.dedup_key),
        ):
            _require_non_blank(value, label)
        if not self.triggered_by:
            raise ValueError("research questions require at least one triggering evidence reference")
        for ref in self.triggered_by:
            _require_canonical(ref, "triggered_by entry")
        for ref in self.internal_answer_refs:
            _require_canonical(ref, "internal_answer_refs entry")
        _require_tz_aware(self.created_at, "created_at")
        if self.internal_answer_status is InternalAnswerStatus.SUFFICIENT and self.status in _ACTIVE_QUESTION_STATUSES:
            raise ValueError(
                "internal/Memory knowledge already answers this question; no external research may be launched"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "question_text": self.question_text,
            "privacy_minimized": self.privacy_minimized,
            "why_now": self.why_now,
            "triggered_by": list(self.triggered_by),
            "what_is_already_known": self.what_is_already_known,
            "what_is_unknown": self.what_is_unknown,
            "what_external_evidence_would_change": self.what_external_evidence_would_change,
            "stop_condition": self.stop_condition,
            "budget": self.budget.to_dict(),
            "internal_answer_status": _dump_enum(self.internal_answer_status),
            "dedup_key": self.dedup_key,
            "status": _dump_enum(self.status),
            "created_at": _dump_datetime(self.created_at),
            "internal_answer_refs": list(self.internal_answer_refs),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchQuestion":
        _require_schema_version(raw, "ResearchQuestion")
        _reject_unknown_fields(raw, _QUESTION_FIELDS, "ResearchQuestion")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            question_text=raw["question_text"],
            privacy_minimized=raw["privacy_minimized"],
            why_now=raw["why_now"],
            triggered_by=tuple(raw["triggered_by"]),
            what_is_already_known=raw["what_is_already_known"],
            what_is_unknown=raw["what_is_unknown"],
            what_external_evidence_would_change=raw["what_external_evidence_would_change"],
            stop_condition=raw["stop_condition"],
            budget=BudgetCeiling.from_dict(raw["budget"]),
            internal_answer_status=InternalAnswerStatus(raw["internal_answer_status"]),
            dedup_key=raw["dedup_key"],
            status=QuestionStatus(raw["status"]),
            created_at=_parse_datetime(raw["created_at"], "created_at"),
            internal_answer_refs=tuple(raw.get("internal_answer_refs", ())),
            schema_version=raw["schema_version"],
        )


_QUESTION_FIELDS = frozenset(
    {
        "identity",
        "project",
        "question_text",
        "privacy_minimized",
        "why_now",
        "triggered_by",
        "what_is_already_known",
        "what_is_unknown",
        "what_external_evidence_would_change",
        "stop_condition",
        "budget",
        "internal_answer_status",
        "dedup_key",
        "status",
        "created_at",
        "internal_answer_refs",
        "schema_version",
    }
)


def research_question_identity(project: Identity, dedup_key: str) -> RepoIdentity:
    _require_performance_project(project, "project")
    _require_non_blank(dedup_key, "dedup_key")
    return deterministic_repo_identity(
        RepoIntelligenceKind.RESEARCH_QUESTION, f"{project.canonical}|{dedup_key}"
    )


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One evidence pointer inside a bundle, with class, trust, and freshness."""

    ref: str
    source_class: SourceClass
    trust_class: TrustClass
    captured_at: datetime
    content_digest: str | None = None

    def __post_init__(self) -> None:
        _require_canonical(self.ref, "evidence item ref")
        _require_non_blank(self.source_class.value, "source_class")
        if self.content_digest is not None:
            _require_hex_digest(self.content_digest, "content_digest")
        _require_tz_aware(self.captured_at, "captured_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "source_class": _dump_enum(self.source_class),
            "trust_class": _dump_enum(self.trust_class),
            "captured_at": _dump_datetime(self.captured_at),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EvidenceItem":
        _reject_unknown_fields(raw, _EVIDENCE_ITEM_FIELDS, "EvidenceItem")
        return cls(
            ref=raw["ref"],
            source_class=SourceClass(raw["source_class"]),
            trust_class=TrustClass(raw["trust_class"]),
            captured_at=_parse_datetime(raw["captured_at"], "captured_at"),
            content_digest=raw.get("content_digest"),
        )


_EVIDENCE_ITEM_FIELDS = frozenset(
    {"ref", "source_class", "trust_class", "captured_at", "content_digest"}
)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """A triangle-side-aware collection of evidence pointers."""

    identity: RepoIdentity
    project: Identity
    items: tuple[EvidenceItem, ...]
    created_at: datetime = field(default_factory=_now_utc)
    gaps: tuple[str, ...] = ()
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.EVIDENCE_BUNDLE, "identity")
        _require_performance_project(self.project, "project")
        if not self.items:
            raise ValueError("evidence bundles require at least one item")
        _require_tz_aware(self.created_at, "created_at")

    def sides_covered(self) -> frozenset[EvidenceSide]:
        return frozenset(SOURCE_SIDE[item.source_class] for item in self.items)

    def external_only(self) -> bool:
        return all(item.source_class in EXTERNAL_SOURCE_CLASSES for item in self.items)

    def one_sided_external(self) -> bool:
        return self.sides_covered() == frozenset({EvidenceSide.EXTERNAL_KNOWLEDGE})

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "items": [item.to_dict() for item in self.items],
            "created_at": _dump_datetime(self.created_at),
            "gaps": list(self.gaps),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EvidenceBundle":
        _require_schema_version(raw, "EvidenceBundle")
        _reject_unknown_fields(raw, _BUNDLE_FIELDS, "EvidenceBundle")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            items=tuple(EvidenceItem.from_dict(item) for item in raw["items"]),
            created_at=_parse_datetime(raw["created_at"], "created_at"),
            gaps=tuple(raw.get("gaps", ())),
            schema_version=raw["schema_version"],
        )


_BUNDLE_FIELDS = frozenset(
    {"identity", "project", "items", "created_at", "gaps", "schema_version"}
)


def evidence_bundle_identity(project: Identity, items: tuple[EvidenceItem, ...]) -> RepoIdentity:
    _require_performance_project(project, "project")
    if not items:
        raise ValueError("evidence bundle identities require at least one item")
    anchors = sorted(f"{item.ref}|{item.content_digest or ''}" for item in items)
    return deterministic_repo_identity(
        RepoIntelligenceKind.EVIDENCE_BUNDLE, f"{project.canonical}|{';'.join(anchors)}"
    )


@dataclass(frozen=True, slots=True)
class ProjectInsight:
    """A bounded knowledge claim derived from bundled evidence.

    Insights are projections: they can never carry ``observed`` claims.
    External-only evidence supports only weak claim kinds; a one-sided
    external insight additionally requires authoritative sources and an
    explicit disclosure.  Proactive exposure additionally requires a
    lineage receipt.
    """

    identity: RepoIdentity
    project: Identity
    statement: str
    claim_kind: ClaimKind
    method: str
    method_version: str
    uncertainty: str
    evidence_bundle: RepoIdentity
    confidence: float | None = None
    lineage_receipt: RepoIdentity | None = None
    requires_user_action: bool = False
    disclosure: str | None = None
    valid_from: datetime = field(default_factory=_now_utc)
    valid_to: datetime | None = None
    superseded_by: RepoIdentity | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.PROJECT_INSIGHT, "identity")
        _require_performance_project(self.project, "project")
        _require_non_blank(self.statement, "statement")
        if len(self.statement) > _MAX_STATEMENT_CHARS:
            raise ValueError(f"statement must not exceed {_MAX_STATEMENT_CHARS} chars")
        if self.claim_kind is ClaimKind.OBSERVED:
            raise ValueError("insights are derived projections and can never claim observed evidence")
        _require_non_blank(self.method, "method")
        _require_non_blank(self.method_version, "method_version")
        _require_non_blank(self.uncertainty, "uncertainty")
        _require_confidence(self.confidence, "confidence")
        if self.claim_kind in _WEAK_CLAIM_KINDS | {ClaimKind.RECOMMENDED} and self.confidence is None:
            raise ValueError("weak claim kinds require explicit confidence")
        _require_kind(self.evidence_bundle, RepoIntelligenceKind.EVIDENCE_BUNDLE, "evidence_bundle")
        if self.lineage_receipt is not None:
            _require_kind(self.lineage_receipt, RepoIntelligenceKind.LINEAGE_RECEIPT, "lineage_receipt")
        if self.claim_kind is ClaimKind.RECOMMENDED and not self.requires_user_action:
            raise ValueError("recommended insights require an explicit user action")
        if self.requires_user_action and self.claim_kind is not ClaimKind.RECOMMENDED:
            raise ValueError("only recommended insights may require a user action")
        if self.disclosure is not None:
            _require_non_blank(self.disclosure, "disclosure")
        _require_tz_aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _require_tz_aware(self.valid_to, "valid_to")
            if self.valid_from > self.valid_to:
                raise ValueError("valid_from must not be after valid_to")
        if self.superseded_by is not None:
            _require_kind(self.superseded_by, RepoIntelligenceKind.PROJECT_INSIGHT, "superseded_by")

    def is_superseded(self) -> bool:
        return self.superseded_by is not None or self.valid_to is not None

    def proactively_exposable(self) -> bool:
        """Lineage-gated, freshness-gated proactive exposure eligibility.

        Evidence-composition rules (one-sided external authority and
        disclosure) are enforced at creation time by
        ``validate_insight_against_bundle`` and are not re-checkable here
        because insights store the bundle identity, not its contents.
        """
        return self.lineage_receipt is not None and not self.is_superseded()

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "statement": self.statement,
            "claim_kind": _dump_enum(self.claim_kind),
            "method": self.method,
            "method_version": self.method_version,
            "uncertainty": self.uncertainty,
            "evidence_bundle": self.evidence_bundle.canonical,
            "confidence": self.confidence,
            "lineage_receipt": _dump_identity(self.lineage_receipt),
            "requires_user_action": self.requires_user_action,
            "disclosure": self.disclosure,
            "valid_from": _dump_datetime(self.valid_from),
            "valid_to": _dump_datetime(self.valid_to),
            "superseded_by": _dump_identity(self.superseded_by),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProjectInsight":
        _require_schema_version(raw, "ProjectInsight")
        _reject_unknown_fields(raw, _INSIGHT_FIELDS, "ProjectInsight")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            statement=raw["statement"],
            claim_kind=ClaimKind(raw["claim_kind"]),
            method=raw["method"],
            method_version=raw["method_version"],
            uncertainty=raw["uncertainty"],
            evidence_bundle=RepoIdentity.parse(raw["evidence_bundle"]),
            confidence=raw.get("confidence"),
            lineage_receipt=RepoIdentity.parse(raw["lineage_receipt"]) if raw.get("lineage_receipt") else None,
            requires_user_action=raw.get("requires_user_action", False),
            disclosure=raw.get("disclosure"),
            valid_from=_parse_datetime(raw["valid_from"], "valid_from"),
            valid_to=_parse_datetime(raw["valid_to"], "valid_to") if raw.get("valid_to") else None,
            superseded_by=RepoIdentity.parse(raw["superseded_by"]) if raw.get("superseded_by") else None,
            schema_version=raw["schema_version"],
        )


_INSIGHT_FIELDS = frozenset(
    {
        "identity",
        "project",
        "statement",
        "claim_kind",
        "method",
        "method_version",
        "uncertainty",
        "evidence_bundle",
        "confidence",
        "lineage_receipt",
        "requires_user_action",
        "disclosure",
        "valid_from",
        "valid_to",
        "superseded_by",
        "schema_version",
    }
)


def project_insight_identity(
    project: Identity, evidence_bundle: RepoIdentity, method: str, method_version: str, statement: str
) -> RepoIdentity:
    _require_performance_project(project, "project")
    _require_kind(evidence_bundle, RepoIntelligenceKind.EVIDENCE_BUNDLE, "evidence_bundle")
    _require_non_blank(method, "method")
    _require_non_blank(method_version, "method_version")
    _require_non_blank(statement, "statement")
    statement_digest = hashlib.sha256(statement.encode("utf-8")).hexdigest()
    return deterministic_repo_identity(
        RepoIntelligenceKind.PROJECT_INSIGHT,
        f"{project.canonical}|{evidence_bundle.canonical}|{method}|{method_version}|{statement_digest}",
    )


def validate_insight_against_bundle(insight: ProjectInsight, bundle: EvidenceBundle) -> None:
    """Enforce evidence-composition claim rules the insight cannot self-check."""
    if insight.evidence_bundle != bundle.identity:
        raise ValueError("insight references a different evidence bundle")
    if bundle.one_sided_external():
        if insight.claim_kind in (ClaimKind.OBSERVED, ClaimKind.DERIVED):
            raise ValueError(
                "external-only evidence cannot support observed or derived claims; "
                "external records remain evidence, never automatically trusted knowledge"
            )
        unauthoritative = [
            item.ref for item in bundle.items if item.trust_class not in AUTHORITATIVE_TRUST
        ]
        if unauthoritative:
            raise ValueError(
                f"one-sided external insights require authoritative sources; weak: {unauthoritative}"
            )
        if insight.disclosure is None or not insight.disclosure.strip():
            raise ValueError("one-sided external insights require explicit disclosure")


class GraphRelation(str, Enum):
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    CALLS_OR_REFERENCES = "calls_or_references"
    CHANGED_IN = "changed_in"
    DISCUSSED_IN = "discussed_in"
    VERIFIED_BY = "verified_by"
    FAILED_IN = "failed_in"
    RELATED_TO = "related_to"
    SIMILAR_TO = "similar_to"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    SUPPORTED_BY = "supported_by"
    DERIVED_FROM = "derived_from"
    ABOUT = "about"
    RELEVANT_TO = "relevant_to"
    EXTERNAL_ANALOGUE_OF = "external_analogue_of"
    LEARNED_FROM = "learned_from"
    EXPOSED_AS = "exposed_as"


class EdgeClass(str, Enum):
    """Exact structural edges are separate from probabilistic semantic edges."""

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"


_GRAPH_CLAIM_KINDS = frozenset(
    {
        ClaimKind.DERIVED,
        ClaimKind.INFERRED,
        ClaimKind.STATISTICAL,
        ClaimKind.PREDICTED,
        ClaimKind.UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class GraphLink:
    """A temporal, provenance-carrying overlay edge; rebuildable, never raw truth."""

    identity: RepoIdentity
    project: Identity
    source: str
    target: str
    relation: GraphRelation
    edge_class: EdgeClass
    claim_kind: ClaimKind
    method: str
    method_version: str
    uncertainty: str
    evidence_ids: tuple[str, ...]
    first_seen: datetime
    last_seen: datetime
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    superseded_by: RepoIdentity | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.GRAPH_LINK, "identity")
        _require_performance_project(self.project, "project")
        _require_canonical(self.source, "source")
        _require_canonical(self.target, "target")
        if self.source == self.target:
            raise ValueError("graph links reject self-edges")
        if self.claim_kind not in _GRAPH_CLAIM_KINDS:
            raise ValueError("graph links are projections and cannot carry observed or recommended claims")
        _require_non_blank(self.method, "method")
        _require_non_blank(self.method_version, "method_version")
        _require_non_blank(self.uncertainty, "uncertainty")
        if not self.evidence_ids:
            raise ValueError("graph links must cite at least one underlying evidence id")
        for ref in self.evidence_ids:
            _require_canonical(ref, "evidence_ids entry")
        _require_confidence(self.confidence, "confidence")
        if self.edge_class is EdgeClass.SEMANTIC and self.confidence is None:
            raise ValueError("semantic edges require explicit confidence")
        _require_tz_aware(self.first_seen, "first_seen")
        _require_tz_aware(self.last_seen, "last_seen")
        if self.first_seen > self.last_seen:
            raise ValueError("first_seen must not be after last_seen")
        if self.valid_from is not None:
            _require_tz_aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _require_tz_aware(self.valid_to, "valid_to")
            if self.valid_from is not None and self.valid_from > self.valid_to:
                raise ValueError("valid_from must not be after valid_to")
        if self.superseded_by is not None:
            _require_kind(self.superseded_by, RepoIntelligenceKind.GRAPH_LINK, "superseded_by")

    def is_stale(self, now: datetime) -> bool:
        _require_tz_aware(now, "now")
        if self.superseded_by is not None:
            return True
        if self.valid_to is not None and now > self.valid_to:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "source": self.source,
            "target": self.target,
            "relation": _dump_enum(self.relation),
            "edge_class": _dump_enum(self.edge_class),
            "claim_kind": _dump_enum(self.claim_kind),
            "method": self.method,
            "method_version": self.method_version,
            "uncertainty": self.uncertainty,
            "evidence_ids": list(self.evidence_ids),
            "first_seen": _dump_datetime(self.first_seen),
            "last_seen": _dump_datetime(self.last_seen),
            "confidence": self.confidence,
            "valid_from": _dump_datetime(self.valid_from),
            "valid_to": _dump_datetime(self.valid_to),
            "superseded_by": _dump_identity(self.superseded_by),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GraphLink":
        _require_schema_version(raw, "GraphLink")
        _reject_unknown_fields(raw, _GRAPH_LINK_FIELDS, "GraphLink")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            source=raw["source"],
            target=raw["target"],
            relation=GraphRelation(raw["relation"]),
            edge_class=EdgeClass(raw["edge_class"]),
            claim_kind=ClaimKind(raw["claim_kind"]),
            method=raw["method"],
            method_version=raw["method_version"],
            uncertainty=raw["uncertainty"],
            evidence_ids=tuple(raw["evidence_ids"]),
            first_seen=_parse_datetime(raw["first_seen"], "first_seen"),
            last_seen=_parse_datetime(raw["last_seen"], "last_seen"),
            confidence=raw.get("confidence"),
            valid_from=_parse_datetime(raw["valid_from"], "valid_from") if raw.get("valid_from") else None,
            valid_to=_parse_datetime(raw["valid_to"], "valid_to") if raw.get("valid_to") else None,
            superseded_by=RepoIdentity.parse(raw["superseded_by"]) if raw.get("superseded_by") else None,
            schema_version=raw["schema_version"],
        )


_GRAPH_LINK_FIELDS = frozenset(
    {
        "identity",
        "project",
        "source",
        "target",
        "relation",
        "edge_class",
        "claim_kind",
        "method",
        "method_version",
        "uncertainty",
        "evidence_ids",
        "first_seen",
        "last_seen",
        "confidence",
        "valid_from",
        "valid_to",
        "superseded_by",
        "schema_version",
    }
)


def graph_link_identity(
    project: Identity, relation: GraphRelation, source: str, target: str, method: str, method_version: str
) -> RepoIdentity:
    _require_performance_project(project, "project")
    _require_canonical(source, "source")
    _require_canonical(target, "target")
    _require_non_blank(method, "method")
    _require_non_blank(method_version, "method_version")
    return deterministic_repo_identity(
        RepoIntelligenceKind.GRAPH_LINK,
        f"{project.canonical}|{relation.value}|{source}|{target}|{method}|{method_version}",
    )


class AnalogyDimension(str, Enum):
    """The explicit structural dimensions Execution RI-14 requires per comparison."""

    ARCHITECTURAL_ROLE = "architectural_role"
    DEPENDENCY_PROTOCOL_OVERLAP = "dependency_protocol_overlap"
    COMPONENT_DATA_FLOW_PATTERN = "component_data_flow_pattern"
    FAILURE_RELIABILITY_PROBLEM = "failure_reliability_problem"
    TEST_STRATEGY = "test_strategy"
    SCALE_MATURITY_CONSTRAINTS = "scale_maturity_constraints"


_ALL_ANALOGY_DIMENSIONS = frozenset(AnalogyDimension)
_DIMENSION_FIELDS = frozenset({"dimension", "comparable", "similarity", "basis", "evidence_ids"})


@dataclass(frozen=True, slots=True)
class DimensionComparison:
    """One explicit structural dimension comparison; never a keyword match.

    A comparable dimension requires a similarity score and at least one
    evidence id; a non-comparable one requires neither, so "we don't have
    evidence for this" can never be silently scored as similar or
    dissimilar.
    """

    dimension: AnalogyDimension
    comparable: bool
    similarity: float | None
    basis: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_blank(self.basis, "basis")
        if self.comparable:
            if self.similarity is None:
                raise ValueError("a comparable dimension requires a similarity score")
            if not 0.0 <= self.similarity <= 1.0:
                raise ValueError("similarity must be between zero and one")
            if not self.evidence_ids:
                raise ValueError("a comparable dimension requires at least one evidence id")
        elif self.similarity is not None:
            raise ValueError("a non-comparable dimension must not carry a similarity score")
        for ref in self.evidence_ids:
            _require_canonical(ref, "evidence_ids entry")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": _dump_enum(self.dimension),
            "comparable": self.comparable,
            "similarity": self.similarity,
            "basis": self.basis,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DimensionComparison":
        _reject_unknown_fields(raw, _DIMENSION_FIELDS, "DimensionComparison")
        return cls(
            dimension=AnalogyDimension(raw["dimension"]),
            comparable=raw["comparable"],
            similarity=raw.get("similarity"),
            basis=raw["basis"],
            evidence_ids=tuple(raw.get("evidence_ids", ())),
        )


def analogy_record_identity(
    project: Identity,
    external_repository: RepoIdentity,
    internal_entity_ref: RepoIdentity,
    method: str,
    method_version: str,
    comparisons: "tuple[DimensionComparison, ...]",
) -> RepoIdentity:
    """Content-addressed like ``project_insight_identity``: a changed verdict is a new record.

    Re-running the comparison with the same facts (same comparisons) is
    idempotent; a genuinely different verdict for the same
    (project, external repository, internal entity, method) gets its own
    identity, so the earlier record can be ``superseded_by``-linked to it
    instead of being silently overwritten.
    """
    _require_performance_project(project, "project")
    _require_kind(external_repository, RepoIntelligenceKind.EXTERNAL_SOURCE_REF, "external_repository")
    _require_kind(internal_entity_ref, RepoIntelligenceKind.PROJECT_ENTITY_REF, "internal_entity_ref")
    _require_non_blank(method, "method")
    _require_non_blank(method_version, "method_version")
    verdict_digest = _content_digest_of(
        json.dumps([c.to_dict() for c in comparisons], sort_keys=True, separators=(",", ":"))
    )
    return deterministic_repo_identity(
        RepoIntelligenceKind.ANALOGY_RECORD,
        f"{project.canonical}|{external_repository.canonical}|{internal_entity_ref.canonical}"
        f"|{method}|{method_version}|{verdict_digest}",
    )


@dataclass(frozen=True, slots=True)
class AnalogyRecord:
    """A structural comparison between one project entity and one external repository.

    Every one of the six explicit dimensions must be addressed, comparable
    or explicitly not, so a keyword-only "this looks similar" can never
    stand in for a real comparison (``__post_init__`` fails closed if any
    dimension is missing or repeated).  ``meaningful_differences`` is
    required and non-empty: even a strong analogy must state what does not
    transfer.  Temporal decay reuses the same shape as ``GraphLink``:
    ``freshness`` bounds the comparison's validity window and
    ``superseded_by`` records a later, superseding comparison without
    deleting this one's historical truth -- e.g. two analogies for the
    same internal entity with divergent verdicts stay both on record, and
    ``project_graph._add_analogies`` links them ``CONTRADICTS`` rather
    than silently preferring one.
    """

    identity: RepoIdentity
    project: Identity
    external_repository: RepoIdentity
    internal_entity_ref: RepoIdentity
    comparisons: tuple[DimensionComparison, ...]
    meaningful_differences: tuple[str, ...]
    confidence: float
    why_it_matters_now: str
    freshness: Freshness
    method: str
    method_version: str
    evidence_ids: tuple[str, ...]
    cost_ref: RepoIdentity | None = None
    created_at: datetime = field(default_factory=_now_utc)
    superseded_by: RepoIdentity | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.ANALOGY_RECORD, "identity")
        _require_performance_project(self.project, "project")
        _require_kind(self.external_repository, RepoIntelligenceKind.EXTERNAL_SOURCE_REF, "external_repository")
        _require_kind(self.internal_entity_ref, RepoIntelligenceKind.PROJECT_ENTITY_REF, "internal_entity_ref")
        covered = tuple(c.dimension for c in self.comparisons)
        if len(set(covered)) != len(covered):
            raise ValueError("analogy records must not repeat a dimension")
        missing = _ALL_ANALOGY_DIMENSIONS - set(covered)
        if missing:
            raise ValueError(
                f"analogy records must address every dimension; missing {sorted(m.value for m in missing)}"
            )
        if not any(c.comparable for c in self.comparisons):
            raise ValueError("an analogy record requires at least one comparable dimension")
        if not self.meaningful_differences:
            raise ValueError("analogy records require at least one stated meaningful difference")
        for text in self.meaningful_differences:
            _require_non_blank(text, "meaningful_differences entry")
        if self.confidence is None:
            raise ValueError("analogy records require an explicit confidence")
        _require_confidence(self.confidence, "confidence")
        _require_non_blank(self.why_it_matters_now, "why_it_matters_now")
        _require_non_blank(self.method, "method")
        _require_non_blank(self.method_version, "method_version")
        if not self.evidence_ids:
            raise ValueError("analogy records must cite at least one underlying evidence id")
        for ref in self.evidence_ids:
            _require_canonical(ref, "evidence_ids entry")
        if self.cost_ref is not None:
            _require_kind(self.cost_ref, RepoIntelligenceKind.COST_RECORD, "cost_ref")
        _require_tz_aware(self.created_at, "created_at")
        if self.superseded_by is not None:
            _require_kind(self.superseded_by, RepoIntelligenceKind.ANALOGY_RECORD, "superseded_by")

    def comparable_dimensions(self) -> tuple[DimensionComparison, ...]:
        return tuple(c for c in self.comparisons if c.comparable)

    def non_comparable_dimensions(self) -> tuple[DimensionComparison, ...]:
        return tuple(c for c in self.comparisons if not c.comparable)

    def is_stale(self, now: datetime) -> bool:
        if self.superseded_by is not None:
            return True
        return not self.freshness.is_current(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "external_repository": self.external_repository.canonical,
            "internal_entity_ref": self.internal_entity_ref.canonical,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "meaningful_differences": list(self.meaningful_differences),
            "confidence": self.confidence,
            "why_it_matters_now": self.why_it_matters_now,
            "freshness": {
                "captured_at": _dump_datetime(self.freshness.captured_at),
                "valid_from": _dump_datetime(self.freshness.valid_from),
                "valid_to": _dump_datetime(self.freshness.valid_to),
            },
            "method": self.method,
            "method_version": self.method_version,
            "evidence_ids": list(self.evidence_ids),
            "cost_ref": _dump_identity(self.cost_ref),
            "created_at": _dump_datetime(self.created_at),
            "superseded_by": _dump_identity(self.superseded_by),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AnalogyRecord":
        _require_schema_version(raw, "AnalogyRecord")
        _reject_unknown_fields(raw, _ANALOGY_FIELDS, "AnalogyRecord")
        freshness_raw = raw["freshness"]
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            external_repository=RepoIdentity.parse(raw["external_repository"]),
            internal_entity_ref=RepoIdentity.parse(raw["internal_entity_ref"]),
            comparisons=tuple(DimensionComparison.from_dict(c) for c in raw["comparisons"]),
            meaningful_differences=tuple(raw["meaningful_differences"]),
            confidence=raw["confidence"],
            why_it_matters_now=raw["why_it_matters_now"],
            freshness=Freshness(
                captured_at=_parse_datetime(freshness_raw["captured_at"], "freshness.captured_at"),
                valid_from=_parse_datetime(freshness_raw["valid_from"], "freshness.valid_from")
                if freshness_raw.get("valid_from") else None,
                valid_to=_parse_datetime(freshness_raw["valid_to"], "freshness.valid_to")
                if freshness_raw.get("valid_to") else None,
            ),
            method=raw["method"],
            method_version=raw["method_version"],
            evidence_ids=tuple(raw["evidence_ids"]),
            cost_ref=RepoIdentity.parse(raw["cost_ref"]) if raw.get("cost_ref") else None,
            created_at=_parse_datetime(raw["created_at"], "created_at"),
            superseded_by=RepoIdentity.parse(raw["superseded_by"]) if raw.get("superseded_by") else None,
            schema_version=raw["schema_version"],
        )


_ANALOGY_FIELDS = frozenset(
    {
        "identity",
        "project",
        "external_repository",
        "internal_entity_ref",
        "comparisons",
        "meaningful_differences",
        "confidence",
        "why_it_matters_now",
        "freshness",
        "method",
        "method_version",
        "evidence_ids",
        "cost_ref",
        "created_at",
        "superseded_by",
        "schema_version",
    }
)


class ExposureChannel(str, Enum):
    PROACTIVE_PUSH = "proactive_push"
    USER_PULL = "user_pull"
    QUIET_QUEUE = "quiet_queue"
    DIGEST = "digest"


class ExposureOutcome(str, Enum):
    OFFERED = "offered"
    OPENED = "opened"
    SAVED = "saved"
    DISMISSED = "dismissed"
    USED = "used"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True, slots=True)
class Exposure:
    """One insight-exposure event with attention-budget context."""

    identity: RepoIdentity
    project: Identity
    insight: RepoIdentity
    channel: ExposureChannel
    outcome: ExposureOutcome
    surface: str
    occurred_at: datetime
    relevance_justification: str | None = None
    focus_protected: bool = False
    attention_cooldown_active: bool = False
    novelty_score: float | None = None
    suppression_reason: str | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.EXPOSURE, "identity")
        _require_performance_project(self.project, "project")
        _require_kind(self.insight, RepoIntelligenceKind.PROJECT_INSIGHT, "insight")
        _require_non_blank(self.surface, "surface")
        _require_tz_aware(self.occurred_at, "occurred_at")
        _require_confidence(self.novelty_score, "novelty_score")
        if self.channel is ExposureChannel.PROACTIVE_PUSH:
            if self.focus_protected:
                raise ValueError("proactive exposure during protected focus is rejected")
            if not (self.relevance_justification or "").strip():
                raise ValueError(
                    "proactive push requires a counterfactual relevance justification: "
                    "what the user would lose if this insight were hidden"
                )
        if self.channel is not ExposureChannel.PROACTIVE_PUSH and self.relevance_justification is not None:
            raise ValueError("relevance_justification is only required for proactive push")
        if self.outcome is ExposureOutcome.SUPPRESSED:
            if not (self.suppression_reason or "").strip():
                raise ValueError("suppressed exposures require a suppression reason")
        elif self.suppression_reason is not None:
            raise ValueError("suppression_reason is only allowed on suppressed exposures")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "insight": self.insight.canonical,
            "channel": _dump_enum(self.channel),
            "outcome": _dump_enum(self.outcome),
            "surface": self.surface,
            "occurred_at": _dump_datetime(self.occurred_at),
            "relevance_justification": self.relevance_justification,
            "focus_protected": self.focus_protected,
            "attention_cooldown_active": self.attention_cooldown_active,
            "novelty_score": self.novelty_score,
            "suppression_reason": self.suppression_reason,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Exposure":
        _require_schema_version(raw, "Exposure")
        _reject_unknown_fields(raw, _EXPOSURE_FIELDS, "Exposure")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            insight=RepoIdentity.parse(raw["insight"]),
            channel=ExposureChannel(raw["channel"]),
            outcome=ExposureOutcome(raw["outcome"]),
            surface=raw["surface"],
            occurred_at=_parse_datetime(raw["occurred_at"], "occurred_at"),
            relevance_justification=raw.get("relevance_justification"),
            focus_protected=raw.get("focus_protected", False),
            attention_cooldown_active=raw.get("attention_cooldown_active", False),
            novelty_score=raw.get("novelty_score"),
            suppression_reason=raw.get("suppression_reason"),
            schema_version=raw["schema_version"],
        )


_EXPOSURE_FIELDS = frozenset(
    {
        "identity",
        "project",
        "insight",
        "channel",
        "outcome",
        "surface",
        "occurred_at",
        "relevance_justification",
        "focus_protected",
        "attention_cooldown_active",
        "novelty_score",
        "suppression_reason",
        "schema_version",
    }
)


class AssociationKind(str, Enum):
    NONE = "none"
    POSITIVE_ASSOCIATION = "positive_association"
    NEGATIVE_ASSOCIATION = "negative_association"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class LearningOutcome:
    """A later Performance association with an exposure; association is not causality."""

    identity: RepoIdentity
    project: Identity
    exposure: RepoIdentity
    insight: RepoIdentity
    association: AssociationKind
    claim_kind: ClaimKind
    method: str
    method_version: str
    uncertainty: str
    window_start: datetime
    window_end: datetime
    created_at: datetime = field(default_factory=_now_utc)
    associated_performance_refs: tuple[str, ...] = ()
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.LEARNING_OUTCOME, "identity")
        _require_performance_project(self.project, "project")
        _require_kind(self.exposure, RepoIntelligenceKind.EXPOSURE, "exposure")
        _require_kind(self.insight, RepoIntelligenceKind.PROJECT_INSIGHT, "insight")
        if self.claim_kind not in (ClaimKind.STATISTICAL, ClaimKind.UNKNOWN):
            raise ValueError(
                "learning outcomes may only claim statistical or unknown strength; "
                "later improvement is never causal proof"
            )
        _require_non_blank(self.method, "method")
        _require_non_blank(self.method_version, "method_version")
        _require_non_blank(self.uncertainty, "uncertainty")
        _require_tz_aware(self.window_start, "window_start")
        _require_tz_aware(self.window_end, "window_end")
        if self.window_start > self.window_end:
            raise ValueError("window_start must not be after window_end")
        _require_tz_aware(self.created_at, "created_at")
        for ref in self.associated_performance_refs:
            _require_performance_canonical(ref, "associated_performance_refs entry")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "exposure": self.exposure.canonical,
            "insight": self.insight.canonical,
            "association": _dump_enum(self.association),
            "claim_kind": _dump_enum(self.claim_kind),
            "method": self.method,
            "method_version": self.method_version,
            "uncertainty": self.uncertainty,
            "window_start": _dump_datetime(self.window_start),
            "window_end": _dump_datetime(self.window_end),
            "created_at": _dump_datetime(self.created_at),
            "associated_performance_refs": list(self.associated_performance_refs),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LearningOutcome":
        _require_schema_version(raw, "LearningOutcome")
        _reject_unknown_fields(raw, _OUTCOME_FIELDS, "LearningOutcome")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            exposure=RepoIdentity.parse(raw["exposure"]),
            insight=RepoIdentity.parse(raw["insight"]),
            association=AssociationKind(raw["association"]),
            claim_kind=ClaimKind(raw["claim_kind"]),
            method=raw["method"],
            method_version=raw["method_version"],
            uncertainty=raw["uncertainty"],
            window_start=_parse_datetime(raw["window_start"], "window_start"),
            window_end=_parse_datetime(raw["window_end"], "window_end"),
            created_at=_parse_datetime(raw["created_at"], "created_at"),
            associated_performance_refs=tuple(raw.get("associated_performance_refs", ())),
            schema_version=raw["schema_version"],
        )


_OUTCOME_FIELDS = frozenset(
    {
        "identity",
        "project",
        "exposure",
        "insight",
        "association",
        "claim_kind",
        "method",
        "method_version",
        "uncertainty",
        "window_start",
        "window_end",
        "created_at",
        "associated_performance_refs",
        "schema_version",
    }
)


class CostResourceKind(str, Enum):
    MODEL_INFERENCE = "model_inference"
    EMBEDDING = "embedding"
    EXTERNAL_SEARCH = "external_search"
    EXTERNAL_FETCH = "external_fetch"
    RERANK = "rerank"
    LOCAL_COMPUTE = "local_compute"


class CacheStatus(str, Enum):
    MISS = "miss"
    HIT = "hit"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class CostRecord:
    """One accounted spend against a job's budget; extends Performance accounting."""

    identity: RepoIdentity
    project: Identity
    job: RepoIdentity
    resource: CostResourceKind
    provider: str
    latency_ms: float
    occurred_at: datetime
    cache_status: CacheStatus = CacheStatus.MISS
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_micros: int | None = None
    cache_key: str | None = None
    budget_authorized: bool = True
    performance_accounting_ref: str | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.COST_RECORD, "identity")
        _require_performance_project(self.project, "project")
        _require_kind(self.job, RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB, "job")
        _require_non_blank(self.provider, "provider")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        for label, value in (
            ("tokens_in", self.tokens_in),
            ("tokens_out", self.tokens_out),
            ("cost_micros", self.cost_micros),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} must not be negative")
        _require_tz_aware(self.occurred_at, "occurred_at")
        if self.cache_status in (CacheStatus.HIT, CacheStatus.WRITE) and not (self.cache_key or "").strip():
            raise ValueError(f"{self.cache_status.value} cache status requires a cache key")
        if self.cache_status is CacheStatus.MISS and self.cache_key is not None:
            raise ValueError("cache_key on a miss record would misattribute cache behavior")
        if self.performance_accounting_ref is not None:
            _require_performance_canonical(
                self.performance_accounting_ref, "performance_accounting_ref"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "job": self.job.canonical,
            "resource": _dump_enum(self.resource),
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "occurred_at": _dump_datetime(self.occurred_at),
            "cache_status": _dump_enum(self.cache_status),
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_micros": self.cost_micros,
            "cache_key": self.cache_key,
            "budget_authorized": self.budget_authorized,
            "performance_accounting_ref": self.performance_accounting_ref,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CostRecord":
        _require_schema_version(raw, "CostRecord")
        _reject_unknown_fields(raw, _COST_FIELDS, "CostRecord")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            job=RepoIdentity.parse(raw["job"]),
            resource=CostResourceKind(raw["resource"]),
            provider=raw["provider"],
            latency_ms=raw["latency_ms"],
            occurred_at=_parse_datetime(raw["occurred_at"], "occurred_at"),
            cache_status=CacheStatus(raw.get("cache_status", "miss")),
            model=raw.get("model"),
            tokens_in=raw.get("tokens_in"),
            tokens_out=raw.get("tokens_out"),
            cost_micros=raw.get("cost_micros"),
            cache_key=raw.get("cache_key"),
            budget_authorized=raw.get("budget_authorized", True),
            performance_accounting_ref=raw.get("performance_accounting_ref"),
            schema_version=raw["schema_version"],
        )


_COST_FIELDS = frozenset(
    {
        "identity",
        "project",
        "job",
        "resource",
        "provider",
        "latency_ms",
        "occurred_at",
        "cache_status",
        "model",
        "tokens_in",
        "tokens_out",
        "cost_micros",
        "cache_key",
        "budget_authorized",
        "performance_accounting_ref",
        "schema_version",
    }
)


@dataclass(frozen=True, slots=True)
class LineageReceipt:
    """Performance Lineage Receipt: provenance for one derived intelligence artifact.

    An insight with no lineage receipt is not eligible for proactive
    exposure.  Source provenance, capture window, derivation method, gaps,
    claim strength, privacy decision, and cost linkage survive synthesis.
    """

    identity: RepoIdentity
    project: Identity
    derivation_method: str
    derivation_version: str
    window_start: datetime
    window_end: datetime
    claim_kind: ClaimKind
    privacy_decision: str
    created_at: datetime = field(default_factory=_now_utc)
    performance_evidence_ids: tuple[str, ...] = ()
    repository_change_refs: tuple[str, ...] = ()
    memory_refs: tuple[ExternalReference, ...] = ()
    gaps: tuple[str, ...] = ()
    confidence: float | None = None
    cost_ref: RepoIdentity | None = None
    schema_version: int = REPO_INTELLIGENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_kind(self.identity, RepoIntelligenceKind.LINEAGE_RECEIPT, "identity")
        _require_performance_project(self.project, "project")
        _require_non_blank(self.derivation_method, "derivation_method")
        _require_non_blank(self.derivation_version, "derivation_version")
        _require_tz_aware(self.window_start, "window_start")
        _require_tz_aware(self.window_end, "window_end")
        if self.window_start > self.window_end:
            raise ValueError("window_start must not be after window_end")
        if self.claim_kind not in (
            ClaimKind.DERIVED,
            ClaimKind.INFERRED,
            ClaimKind.STATISTICAL,
            ClaimKind.UNKNOWN,
        ):
            raise ValueError("lineage receipts cannot carry observed, predicted, or recommended claims")
        if self.privacy_decision not in _PRIVACY_DECISIONS:
            raise ValueError(f"privacy_decision must be one of {sorted(_PRIVACY_DECISIONS)}")
        _require_tz_aware(self.created_at, "created_at")
        for ref in self.performance_evidence_ids:
            _require_performance_canonical(ref, "performance_evidence_ids entry")
        for ref in self.repository_change_refs:
            _require_non_blank(ref, "repository_change_refs entry")
        pointer_count = (
            len(self.performance_evidence_ids)
            + len(self.repository_change_refs)
            + len(self.memory_refs)
        )
        if pointer_count < 1:
            raise ValueError("lineage receipts require at least one source pointer")
        _require_confidence(self.confidence, "confidence")
        if self.cost_ref is not None:
            _require_kind(self.cost_ref, RepoIntelligenceKind.COST_RECORD, "cost_ref")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.canonical,
            "project": self.project.canonical,
            "derivation_method": self.derivation_method,
            "derivation_version": self.derivation_version,
            "window_start": _dump_datetime(self.window_start),
            "window_end": _dump_datetime(self.window_end),
            "claim_kind": _dump_enum(self.claim_kind),
            "privacy_decision": self.privacy_decision,
            "created_at": _dump_datetime(self.created_at),
            "performance_evidence_ids": list(self.performance_evidence_ids),
            "repository_change_refs": list(self.repository_change_refs),
            "memory_refs": [asdict(ref) for ref in self.memory_refs],
            "gaps": list(self.gaps),
            "confidence": self.confidence,
            "cost_ref": _dump_identity(self.cost_ref),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LineageReceipt":
        _require_schema_version(raw, "LineageReceipt")
        _reject_unknown_fields(raw, _LINEAGE_FIELDS, "LineageReceipt")
        return cls(
            identity=RepoIdentity.parse(raw["identity"]),
            project=Identity.parse(raw["project"]),
            derivation_method=raw["derivation_method"],
            derivation_version=raw["derivation_version"],
            window_start=_parse_datetime(raw["window_start"], "window_start"),
            window_end=_parse_datetime(raw["window_end"], "window_end"),
            claim_kind=ClaimKind(raw["claim_kind"]),
            privacy_decision=raw["privacy_decision"],
            created_at=_parse_datetime(raw["created_at"], "created_at"),
            performance_evidence_ids=tuple(raw.get("performance_evidence_ids", ())),
            repository_change_refs=tuple(raw.get("repository_change_refs", ())),
            memory_refs=tuple(
                ExternalReference(
                    provider=item["provider"], kind=item["kind"], value=item["value"]
                )
                for item in raw.get("memory_refs", ())
            ),
            gaps=tuple(raw.get("gaps", ())),
            confidence=raw.get("confidence"),
            cost_ref=RepoIdentity.parse(raw["cost_ref"]) if raw.get("cost_ref") else None,
            schema_version=raw["schema_version"],
        )


_LINEAGE_FIELDS = frozenset(
    {
        "identity",
        "project",
        "derivation_method",
        "derivation_version",
        "window_start",
        "window_end",
        "claim_kind",
        "privacy_decision",
        "created_at",
        "performance_evidence_ids",
        "repository_change_refs",
        "memory_refs",
        "gaps",
        "confidence",
        "cost_ref",
        "schema_version",
    }
)


def lineage_receipt_identity(
    project: Identity,
    derivation_method: str,
    derivation_version: str,
    window_start: datetime,
    window_end: datetime,
    performance_evidence_ids: tuple[str, ...],
    repository_change_refs: tuple[str, ...],
    memory_refs: tuple[ExternalReference, ...],
) -> RepoIdentity:
    _require_performance_project(project, "project")
    _require_non_blank(derivation_method, "derivation_method")
    _require_non_blank(derivation_version, "derivation_version")
    _require_tz_aware(window_start, "window_start")
    _require_tz_aware(window_end, "window_end")
    anchors = json.dumps(
        [
            sorted(performance_evidence_ids),
            sorted(repository_change_refs),
            sorted(f"{ref.provider}:{ref.kind}:{ref.value}" for ref in memory_refs),
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = _content_digest_of(anchors)
    return deterministic_repo_identity(
        RepoIntelligenceKind.LINEAGE_RECEIPT,
        f"{project.canonical}|{derivation_method}|{derivation_version}"
        f"|{window_start.isoformat()}|{window_end.isoformat()}|{digest}",
    )


def new_event_identity(kind: Any) -> RepoIdentity:
    """Random identity for one-off event records (exposures, cost events)."""
    if kind not in RepoIntelligenceKind:
        raise ValueError("event identities require a RepoIntelligenceKind")
    return RepoIdentity(kind=kind, value=uuid4())


__all__ = [
    "REPO_INTELLIGENCE_CONTRACT_VERSION",
    "AnalogyDimension",
    "AnalogyRecord",
    "AssociationKind",
    "BudgetCeiling",
    "CacheStatus",
    "CostRecord",
    "CostResourceKind",
    "DimensionComparison",
    "EdgeClass",
    "EvidenceBundle",
    "EvidenceItem",
    "Exposure",
    "ExposureChannel",
    "ExposureOutcome",
    "GraphLink",
    "GraphRelation",
    "InternalAnswerStatus",
    "InternalSignal",
    "JobStatus",
    "JobTrigger",
    "LearningOutcome",
    "LineageReceipt",
    "PressureDimension",
    "ProjectEntityRef",
    "ProjectEntityRefKind",
    "ProjectInsight",
    "ProjectIntelligenceJob",
    "QuestionStatus",
    "ResearchQuestion",
    "UnsupportedSchemaVersionError",
    "analogy_record_identity",
    "evidence_bundle_identity",
    "external_source_ref_identity",
    "graph_link_identity",
    "internal_signal_identity",
    "lineage_receipt_identity",
    "new_event_identity",
    "project_entity_ref_identity",
    "project_insight_identity",
    "project_intelligence_job_identity",
    "research_question_identity",
    "validate_insight_against_bundle",
]
