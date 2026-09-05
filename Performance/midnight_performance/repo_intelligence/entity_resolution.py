"""Incremental repository entity resolution for Repo Intelligent.

Repository structure truth belongs to the live repository; per-change
symbol/region resolution belongs to Performance's
``repository_entity_resolution``.  This module reuses both and adds only
the Repo Intelligent rollup: a project-scoped, content-independent
``ProjectEntityRef`` hierarchy (repository → package → file/module →
test/config/doc) that can be updated incrementally from changed paths
instead of rebuilt wholesale.  Identity is path/qualified-name based, so
small edits keep the same reference; ``content_digest`` and
``last_seen_at`` carry freshness; rename continuity stays honest through
``rename_uncertainty``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from ..contracts import Identity
from ..repository_capture import RepositorySnapshot
from ..repository_entity_resolution import ResolvedFile
from .contracts import ProjectEntityRef, ProjectEntityRefKind, project_entity_ref_identity

ENTITY_RESOLVER_TOOL = "ri-path-classifier"
ENTITY_RESOLVER_VERSION = "1"

_SUFFIX_CONFIG = frozenset({".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env", ".lock", ".xml"})
_SUFFIX_DOC = frozenset({".md", ".rst", ".adoc"})
_CONFIG_FILENAMES = frozenset(
    {"pyproject.toml", "package.json", "package-lock.json", "tsconfig.json", "makefile", "dockerfile"}
)


def classify_entity_kind(path: str) -> ProjectEntityRefKind:
    """Classify one repository path into its entity role."""
    if not path.strip():
        raise ValueError("entity paths must not be blank")
    pure = PurePosixPath(path)
    name = pure.name.lower()
    stem = pure.stem.lower()
    suffix = pure.suffix.lower()
    parts = {part.lower() for part in pure.parts[:-1]}
    if name.startswith("test_") or stem.endswith("_test"):
        return ProjectEntityRefKind.TEST
    if "tests" in parts or "test" in parts:
        return ProjectEntityRefKind.TEST
    if suffix in _SUFFIX_CONFIG or name in _CONFIG_FILENAMES:
        return ProjectEntityRefKind.CONFIG
    if suffix in _SUFFIX_DOC or name in {"readme", "changelog", "license", "contributing"}:
        return ProjectEntityRefKind.DOC
    if suffix == ".py":
        return ProjectEntityRefKind.MODULE
    return ProjectEntityRefKind.FILE


def entity_ref(
    project: Identity,
    repository_key: str,
    path: str | None,
    *,
    now: datetime,
    ref_kind: ProjectEntityRefKind | None = None,
    qualified_name: str | None = None,
    resolver_tool: str = ENTITY_RESOLVER_TOOL,
    resolver_version: str = ENTITY_RESOLVER_VERSION,
) -> ProjectEntityRef:
    """Build one entity ref with its deterministic identity.

    Identity is content-independent: ``project_entity_ref_identity``
    covers repository, role, path, qualified name, and resolver only.
    """
    kind = ref_kind if ref_kind is not None else classify_entity_kind(path or "")
    if kind is ProjectEntityRefKind.REPOSITORY:
        path = None
        qualified_name = qualified_name or repository_key
    identity = project_entity_ref_identity(
        repository_key, kind, path, qualified_name, resolver_tool, resolver_version
    )
    return ProjectEntityRef(
        identity=identity,
        project=project,
        ref_kind=kind,
        repository_key=repository_key,
        resolver_tool=resolver_tool,
        resolver_version=resolver_version,
        first_seen_at=now,
        last_seen_at=now,
        path=path,
        qualified_name=qualified_name,
    )


def package_dirs_from_snapshot(snapshot: RepositorySnapshot) -> frozenset[str]:
    """Directories that are Python packages (contain ``__init__.py``)."""
    files = set(snapshot.files)
    dirs: set[str] = set()
    for path in files:
        pure = PurePosixPath(path)
        if pure.name == "__init__.py" and len(pure.parts) > 1:
            dirs.add(str(pure.parent))
    return frozenset(dirs)


def _container_paths(path: str, package_dirs: frozenset[str]) -> tuple[str, ...]:
    pure = PurePosixPath(path)
    containers: list[str] = []
    for parent in list(pure.parents)[:-1]:
        text = str(parent)
        if text in package_dirs:
            containers.append(text)
    return tuple(containers)


def bootstrap_entity_refs(
    project: Identity,
    repository_key: str,
    snapshot: RepositorySnapshot,
    *,
    now: datetime,
) -> dict[str, ProjectEntityRef]:
    """Full-tree bootstrap of the entity hierarchy from one snapshot."""
    return upsert_entity_refs(
        {},
        project,
        repository_key,
        touched=((path, digest) for path, digest in sorted(snapshot.files.items())),
        package_dirs=package_dirs_from_snapshot(snapshot),
        now=now,
    )[0]


def upsert_entity_refs(
    existing: dict[str, ProjectEntityRef],
    project: Identity,
    repository_key: str,
    *,
    touched,  # iterable of (path, content_digest | None)
    package_dirs: frozenset[str] = frozenset(),
    now: datetime,
) -> tuple[dict[str, ProjectEntityRef], tuple[ProjectEntityRef, ...]]:
    """Incrementally upsert refs for touched paths and their containers.

    Returns the updated mapping plus the refs written in this call, in
    deterministic (canonical identity) order.  ``first_seen_at`` is
    preserved from any existing ref; only ``last_seen_at`` and
    ``content_digest`` move forward.
    """
    if now.tzinfo is None:
        raise ValueError("upsert timestamps must be timezone-aware")
    normalized: list[tuple[str, str | None]] = []
    for path, digest in touched:
        clean = path.replace("\\", "/").lstrip("/")
        if not clean.strip():
            raise ValueError("entity paths must not be blank")
        normalized.append((clean, digest))

    updated = dict(existing)
    written: list[ProjectEntityRef] = []

    def _upsert(path: str, digest: str | None, kind: ProjectEntityRefKind | None, qualified: str | None) -> None:
        base = entity_ref(
            project, repository_key, path, now=now, ref_kind=kind, qualified_name=qualified
        )
        key = base.identity.canonical
        prior = updated.get(key)
        first_seen = prior.first_seen_at if prior is not None else now
        ref = ProjectEntityRef(
            identity=base.identity,
            project=project,
            ref_kind=base.ref_kind,
            repository_key=repository_key,
            resolver_tool=base.resolver_tool,
            resolver_version=base.resolver_version,
            first_seen_at=first_seen,
            last_seen_at=now,
            path=base.path,
            qualified_name=base.qualified_name,
            content_digest=digest if digest is not None else (prior.content_digest if prior else None),
        )
        updated[key] = ref
        written.append(ref)

    for path, digest in normalized:
        _upsert(path, digest, None, None)
        for container in _container_paths(path, package_dirs):
            _upsert(container, None, ProjectEntityRefKind.PACKAGE, None)

    repo_ref = entity_ref(
        project, repository_key, None, now=now, ref_kind=ProjectEntityRefKind.REPOSITORY
    )
    key = repo_ref.identity.canonical
    prior = updated.get(key)
    updated[key] = ProjectEntityRef(
        identity=repo_ref.identity,
        project=project,
        ref_kind=ProjectEntityRefKind.REPOSITORY,
        repository_key=repository_key,
        resolver_tool=repo_ref.resolver_tool,
        resolver_version=repo_ref.resolver_version,
        first_seen_at=prior.first_seen_at if prior is not None else now,
        last_seen_at=now,
        path=None,
        qualified_name=repository_key,
    )
    written.append(updated[key])

    ordered = tuple(sorted(written, key=lambda ref: ref.identity.canonical))
    return updated, ordered


def symbol_refs_from_resolved(
    project: Identity,
    repository_key: str,
    resolved: ResolvedFile,
    *,
    now: datetime,
) -> tuple[ProjectEntityRef, ...]:
    """Map Performance's per-change symbol/region records to entity refs.

    Reuses the resolver tool/version recorded by Performance's own
    resolver so identity stays aligned with the canonical resolver.
    """
    refs: list[ProjectEntityRef] = []
    file_path = resolved.file_change.path
    for symbol in resolved.symbols:
        refs.append(
            ProjectEntityRef(
                identity=project_entity_ref_identity(
                    repository_key,
                    ProjectEntityRefKind.SYMBOL,
                    file_path,
                    symbol.qualified_name,
                    symbol.resolver.tool,
                    symbol.resolver.tool_version,
                ),
                project=project,
                ref_kind=ProjectEntityRefKind.SYMBOL,
                repository_key=repository_key,
                resolver_tool=symbol.resolver.tool,
                resolver_version=symbol.resolver.tool_version,
                first_seen_at=now,
                last_seen_at=now,
                path=file_path,
                qualified_name=symbol.qualified_name,
            )
        )
    for region in resolved.regions:
        span = f"{region.start_line}:{region.end_line}"
        refs.append(
            ProjectEntityRef(
                identity=project_entity_ref_identity(
                    repository_key,
                    ProjectEntityRefKind.CODE_REGION,
                    file_path,
                    span,
                    region.resolver.tool,
                    region.resolver.tool_version,
                ),
                project=project,
                ref_kind=ProjectEntityRefKind.CODE_REGION,
                repository_key=repository_key,
                resolver_tool=region.resolver.tool,
                resolver_version=region.resolver.tool_version,
                first_seen_at=now,
                last_seen_at=now,
                path=file_path,
                qualified_name=span,
            )
        )
    return tuple(sorted(refs, key=lambda ref: ref.identity.canonical))


def index_refs_by_path(refs) -> dict[str, ProjectEntityRef]:
    """Index entity refs by repository path for scan-time lookups.

    Repository refs (no path) and duplicate path claims keep the ref with
    the latest ``last_seen_at``; symbols and regions are keyed by their
    file path plus qualified name so they never shadow their file.
    """
    index: dict[str, ProjectEntityRef] = {}
    for ref in refs:
        if ref.path is None:
            continue
        key = ref.path if ref.qualified_name is None else f"{ref.path}#{ref.qualified_name}"
        prior = index.get(key)
        if prior is None or ref.last_seen_at > prior.last_seen_at:
            index[key] = ref
    return index


__all__ = [
    "ENTITY_RESOLVER_TOOL",
    "ENTITY_RESOLVER_VERSION",
    "bootstrap_entity_refs",
    "classify_entity_kind",
    "entity_ref",
    "index_refs_by_path",
    "package_dirs_from_snapshot",
    "symbol_refs_from_resolved",
    "upsert_entity_refs",
]
