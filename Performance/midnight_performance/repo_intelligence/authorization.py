"""Project authorization and project-isolated state for Repo Intelligent.

One project can never read, write, or cache-address another project's
private intelligence.  Authorization wraps the Performance project
identity; state paths and cache keys embed the project identity so
cross-project collisions fail closed instead of blending evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..contracts import EntityKind, Identity
from .sources import SourceClass


REPO_INTELLIGENCE_STATE_DIRNAME = "repo_intelligence"


class CrossProjectAccessError(PermissionError):
    """An operation attempted to cross a project boundary."""


@dataclass(frozen=True, slots=True)
class RepoIntelligenceAuthorization:
    """Server-issued project capability; callers cannot select another project."""

    project: Identity
    allowed_source_classes: frozenset[SourceClass] = field(default_factory=lambda: frozenset(SourceClass))
    external_access: bool = False
    model_access: bool = False
    allow_private_identifiers: bool = False
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.project.kind is not EntityKind.PROJECT:
            raise ValueError("repo intelligence authorization requires a project identity")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("authorization expiry must be timezone-aware")


def require_active_authorization(authorization: RepoIntelligenceAuthorization, *, now: datetime | None = None) -> None:
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("authorization check time must be timezone-aware")
    if authorization.expires_at is not None and moment >= authorization.expires_at:
        raise PermissionError("Repo Intelligent authorization has expired")


def ensure_same_project(authorization: RepoIntelligenceAuthorization, *, project: Identity) -> None:
    if authorization.project != project:
        raise CrossProjectAccessError("cross-project Repo Intelligent access is rejected")


def require_external_access(authorization: RepoIntelligenceAuthorization, *, now: datetime | None = None) -> None:
    require_active_authorization(authorization, now=now)
    if not authorization.external_access:
        raise PermissionError("external discovery/fetch is not authorized for this project")


def require_model_access(authorization: RepoIntelligenceAuthorization, *, now: datetime | None = None) -> None:
    require_active_authorization(authorization, now=now)
    if not authorization.model_access:
        raise PermissionError("model generation is not authorized for this project")


def ensure_record_project(authorization: RepoIntelligenceAuthorization, record_project: Identity) -> None:
    """Validate that a stored or incoming record belongs to the authorized project."""
    ensure_same_project(authorization, project=record_project)


def project_state_dir(data_dir: Path, project: Identity) -> Path:
    """Project-isolated state directory; different projects never share a path."""
    if project.kind is not EntityKind.PROJECT:
        raise ValueError("repo intelligence state requires a project identity")
    return Path(data_dir) / REPO_INTELLIGENCE_STATE_DIRNAME / project.value.hex


def cache_key(namespace: str, project: Identity, content_digest: str) -> str:
    """Project-bound content-addressed cache key.

    The project canonical identity is part of the key material, so two
    projects with byte-identical content can never collide on a cache
    entry, and a cache entry can never be replayed across projects.
    """
    if not namespace.strip():
        raise ValueError("cache keys require a namespace")
    if project.kind is not EntityKind.PROJECT:
        raise ValueError("cache keys require a project identity")
    if not content_digest.strip():
        raise ValueError("cache keys require a content digest")
    material = f"{namespace}|{project.canonical}|{content_digest}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "CrossProjectAccessError",
    "RepoIntelligenceAuthorization",
    "REPO_INTELLIGENCE_STATE_DIRNAME",
    "cache_key",
    "ensure_record_project",
    "ensure_same_project",
    "project_state_dir",
    "require_active_authorization",
    "require_external_access",
    "require_model_access",
]
