"""Execution 08: real repository-change evidence resolved into typed
`FileChange`/`CodeRegion`/`Symbol` graph entities.

Reuses, never reimplements, the existing Python-AST capability:
`traceability.resolve_code_elements` for qualified symbol enumeration and
`structural_diff.structural_diff` for symbol-level rename/move continuity
(its existing body-digest matching — "not magically equal unless evidence
supports linkage", exactly Section F's requirement). Neither module is
modified; this module re-derives fresh, repository/parser-version-qualified
`Identity` objects from their output rather than reusing their own
path+name-scoped bare-string ids, which are too weak for Section F.

Tree-sitter (Section E) does not qualify for this execution — see this
module's own `TYPESCRIPT_RESOLVER`/`JAVASCRIPT_RESOLVER` uncertainty text.
Performance's strict, pre-existing, zero-third-party-dependency policy rules
out a Python binding outright; Desktop is forbidden from being a second
evidence producer, so it can't host the parser instead. TypeScript/TSX/
JavaScript/JSX get real, honestly-labeled `CodeRegion` line-hunk evidence
(stdlib `difflib`, never claimed as structural/symbol parsing) but never
`Symbol` truth.

This module never reads the filesystem or derives content from
`RepositorySnapshot` (which stores only hashes) — callers supply real file
bytes directly, matching "no source-code diffs shown by default" and the
existing `structural_diff`/`traceability` precedent of taking literal text.

Known, documented, un-fixed inconsistency: `relationship_graph
.add_contradiction_edges` already mints `FILE_CHANGE` identities via
`deterministic_identity(EntityKind.FILE_CHANGE, path)` (bare path only, no
repository/change-set scoping) for an unrelated feature (contradiction
detection against `AlignmentResult` judgments). This module's `FileChange`
identities are scoped far more richly (Section F) and will never coincide
with that mechanism's — out of scope to reconcile, same spirit as the
pre-existing `STRUCTURAL_DIFF_VERSION`/`traceability.PARSER_VERSION`
divergence already accepted elsewhere in this package.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Mapping

from .contracts import EntityKind, Identity, deterministic_identity
from .parser_adapter import MAX_SOURCE_BYTES
from .relationship_graph import ResolvedRepositoryEntity
from .repository_capture import ChangeEvidence
from .structural_diff import StructuralEditKind, structural_diff
from .structural_resolver_contract import IdentityStrategy, ResolverCapability, ResolverDescriptor
from .traceability import CodeElement, CodeElementKind, PARSER_VERSION as PYTHON_AST_TOOL_VERSION, resolve_code_elements

_BINARY_SNIFF_BYTES = 8000

_CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml"}
_CONFIG_NAMES = {"pyproject.toml", "package.json", "requirements.txt", "tsconfig.json", "package-lock.json", "poetry.lock"}


def classify_language(path: str, content: bytes | None) -> str:
    """One of six honest categories (Section A). A NUL byte in the first
    `_BINARY_SNIFF_BYTES` is real, direct evidence of binary content — a
    bounded sniff, never claimed as "structural parsing." Extension-only
    when content is unavailable; never guesses "binary" without evidence."""
    if content is not None and b"\x00" in content[:_BINARY_SNIFF_BYTES]:
        return "binary"
    suffix = PurePosixPath(path).suffix.lower()
    name = PurePosixPath(path).name.lower()
    if suffix == ".py":
        return "python"
    if suffix in (".ts", ".tsx"):
        return "typescript"
    if suffix in (".js", ".jsx"):
        return "javascript"
    if suffix in _CONFIG_SUFFIXES or name in _CONFIG_NAMES:
        return "config"
    return "unknown-text"


class FileChangeStatus(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class FileChangeRecord:
    identity: Identity
    path: str
    previous_path: str | None
    status: FileChangeStatus
    resolver: ResolverDescriptor


@dataclass(frozen=True, slots=True)
class CodeRegionRecord:
    identity: Identity
    file_change: Identity
    start_line: int
    end_line: int
    resolver: ResolverDescriptor


@dataclass(frozen=True, slots=True)
class SymbolRecord:
    identity: Identity
    file_change: Identity
    qualified_name: str
    kind: CodeElementKind
    start_line: int | None
    end_line: int | None
    resolver: ResolverDescriptor
    # `structural_diff`'s own rename/move uncertainty text, verbatim — an
    # ANNOTATION only, never a new graph edge (Section G: structural
    # materialization only, no inferred relationships).
    rename_note: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedFile:
    file_change: FileChangeRecord
    regions: tuple[CodeRegionRecord, ...] = ()
    symbols: tuple[SymbolRecord, ...] = ()
    gaps: tuple[str, ...] = ()


# --- Resolver descriptors (Section D contract instances) -------------------

PYTHON_RESOLVER = ResolverDescriptor(
    language="python", tool="stdlib-ast", tool_version=PYTHON_AST_TOOL_VERSION,
    capabilities=frozenset({ResolverCapability.STRUCTURE, ResolverCapability.SYMBOLS}),
    max_bytes=MAX_SOURCE_BYTES, identity_strategy=IdentityStrategy.REPOSITORY_FILE_QUALIFIED_SYMBOL,
    supported=True, gap=None,
    uncertainty="derived structural projection via Python stdlib ast; source snapshot remains authoritative",
)


def _line_hunk_resolver(language: str) -> ResolverDescriptor:
    return ResolverDescriptor(
        language=language, tool="difflib-line-hunks", tool_version="1",
        capabilities=frozenset({ResolverCapability.REGIONS}),
        max_bytes=MAX_SOURCE_BYTES, identity_strategy=IdentityStrategy.REPOSITORY_FILE_LINE_RANGE,
        supported=True, gap=None,
        uncertainty=(
            "line-based diff evidence only, never structural/symbol parsing — Tree-sitter qualification "
            "for this language did not qualify this execution (Performance's zero-third-party-dependency "
            "policy rules out a Python binding; Desktop cannot host a parser as it must never be a second "
            "evidence producer)"
        ),
    )


TYPESCRIPT_RESOLVER = _line_hunk_resolver("typescript")
JAVASCRIPT_RESOLVER = _line_hunk_resolver("javascript")


def _unsupported_resolver(language: str, gap: str) -> ResolverDescriptor:
    return ResolverDescriptor(
        language=language, tool="none", tool_version="1", capabilities=frozenset(),
        max_bytes=MAX_SOURCE_BYTES, identity_strategy=IdentityStrategy.REPOSITORY_FILE,
        supported=False, gap=gap, uncertainty="file-level truth only; no structural resolution attempted",
    )


CONFIG_RESOLVER = _unsupported_resolver("config", "configuration/data file; no structural symbol resolution attempted")
UNKNOWN_TEXT_RESOLVER = _unsupported_resolver("unknown-text", "unrecognized text language; no structural symbol resolution attempted")
BINARY_RESOLVER = _unsupported_resolver("binary", "binary file; content not inspected beyond classification")


def _deleted_resolver(language: str) -> ResolverDescriptor:
    return ResolverDescriptor(
        language=language, tool="none", tool_version="1", capabilities=frozenset(),
        max_bytes=MAX_SOURCE_BYTES, identity_strategy=IdentityStrategy.REPOSITORY_FILE,
        supported=False, gap="file deleted; no structural symbol resolution possible for removed content",
        uncertainty="file-level truth only; removed content is not re-parsed",
    )


def _oversized_resolver(language: str) -> ResolverDescriptor:
    return ResolverDescriptor(
        language=language, tool="none", tool_version="1", capabilities=frozenset(),
        max_bytes=MAX_SOURCE_BYTES, identity_strategy=IdentityStrategy.REPOSITORY_FILE,
        supported=False, gap="source exceeds parser resource bound",
        uncertainty="file-level truth only; content exceeds the resolver's resource budget",
    )


def _decode_text(data: bytes | None) -> str | None:
    if data is None:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _file_change_stable_key(repository_key: str, change_set_id: str, path: str, status: FileChangeStatus, previous_path: str | None) -> str:
    key = f"{repository_key}|{change_set_id}|{path}|{status.value}"
    if status is FileChangeStatus.RENAMED and previous_path is not None:
        key += f"|{previous_path}"
    return key


def _symbol_record_from_code_element(file_identity: Identity, element: CodeElement, resolver: ResolverDescriptor, rename_note: str | None) -> SymbolRecord:
    stable_key = f"{file_identity.canonical}|{element.qualified_name}|{element.kind.value}|{resolver.tool}:{resolver.tool_version}"
    identity = deterministic_identity(EntityKind.SYMBOL, stable_key)
    return SymbolRecord(identity, file_identity, element.qualified_name, element.kind, element.start_line, element.end_line, resolver, rename_note)


_STRUCTURAL_ELEMENT_KIND = {"class": CodeElementKind.CLASS, "method": CodeElementKind.METHOD, "function": CodeElementKind.FUNCTION}


def _symbol_record_from_structural_element(file_identity: Identity, element, resolver: ResolverDescriptor, rename_note: str | None) -> SymbolRecord:
    kind = _STRUCTURAL_ELEMENT_KIND.get(element.kind, CodeElementKind.UNKNOWN)
    stable_key = f"{file_identity.canonical}|{element.name}|{kind.value}|{resolver.tool}:{resolver.tool_version}"
    identity = deterministic_identity(EntityKind.SYMBOL, stable_key)
    return SymbolRecord(identity, file_identity, element.name, kind, element.start_line, element.end_line, resolver, rename_note)


def _resolve_python_symbols(
    file_identity: Identity, path: str, status: FileChangeStatus, before_bytes: bytes | None, after_bytes: bytes | None, resolver: ResolverDescriptor,
) -> tuple[tuple[SymbolRecord, ...], tuple[str, ...]]:
    after_text = _decode_text(after_bytes)
    if after_text is None:
        return (), (f"{file_identity.canonical}:unavailable:non_utf8_source",)

    if status is FileChangeStatus.MODIFIED and before_bytes is not None:
        before_text = _decode_text(before_bytes)
        diff = structural_diff(path, before_text, after_text)
        symbols = tuple(
            _symbol_record_from_structural_element(
                file_identity, edit.after, resolver,
                edit.uncertainty if edit.kind in (StructuralEditKind.RENAME, StructuralEditKind.MOVE) else None,
            )
            for edit in diff.edits if edit.after is not None
        )
        return symbols, ()

    elements = resolve_code_elements(path, after_text)
    if len(elements) == 1 and elements[0].kind is CodeElementKind.UNKNOWN:
        return (), (f"{file_identity.canonical}:unavailable:python_syntax_error",)
    return tuple(_symbol_record_from_code_element(file_identity, element, resolver, None) for element in elements), ()


def _line_hunks(before_text: str | None, after_text: str) -> tuple[tuple[int, int], ...]:
    after_lines = after_text.splitlines()
    if before_text is None:
        return ((1, len(after_lines) or 1),)
    before_lines = before_text.splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    hunks = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "delete"):
            continue  # a pure delete has no after-side line range to bound
        hunks.append((j1 + 1, j2))
    return tuple(hunks)


def _resolve_line_hunk_regions(
    file_identity: Identity, before_bytes: bytes | None, after_bytes: bytes | None, resolver: ResolverDescriptor,
) -> tuple[tuple[CodeRegionRecord, ...], tuple[str, ...]]:
    after_text = _decode_text(after_bytes)
    if after_text is None:
        return (), (f"{file_identity.canonical}:unavailable:non_utf8_source",)
    before_text = _decode_text(before_bytes)
    hunks = _line_hunks(before_text, after_text)
    if not hunks:
        return (), (f"{file_identity.canonical}:unavailable:no_bounded_region",)
    regions = []
    for index, (start, end) in enumerate(hunks):
        stable_key = f"{file_identity.canonical}|{start}-{end}|{index}"
        regions.append(CodeRegionRecord(deterministic_identity(EntityKind.CODE_REGION, stable_key), file_identity, start, end, resolver))
    return tuple(regions), ()


def resolve_file_change(
    *, repository_key: str, change_set_id: str, path: str, previous_path: str | None,
    status: FileChangeStatus, before: bytes | None, after: bytes | None,
) -> ResolvedFile:
    """Resolve one file's structural entities from real, caller-supplied
    content bytes. Never reads the filesystem itself."""
    stable_key = _file_change_stable_key(repository_key, change_set_id, path, status, previous_path)
    file_identity = deterministic_identity(EntityKind.FILE_CHANGE, stable_key)
    content = after if after is not None else before
    language = classify_language(path, content)

    if status is FileChangeStatus.DELETED:
        resolver = _deleted_resolver(language)
        return ResolvedFile(FileChangeRecord(file_identity, path, previous_path, status, resolver))

    if language == "binary":
        return ResolvedFile(FileChangeRecord(file_identity, path, previous_path, status, BINARY_RESOLVER))

    if language == "config":
        return ResolvedFile(FileChangeRecord(file_identity, path, previous_path, status, CONFIG_RESOLVER))

    if language == "unknown-text":
        return ResolvedFile(FileChangeRecord(file_identity, path, previous_path, status, UNKNOWN_TEXT_RESOLVER))

    if content is not None and len(content) > MAX_SOURCE_BYTES:
        resolver = _oversized_resolver(language)
        return ResolvedFile(FileChangeRecord(file_identity, path, previous_path, status, resolver), gaps=(f"{file_identity.canonical}:unavailable:resource_bound",))

    if language == "python":
        record = FileChangeRecord(file_identity, path, previous_path, status, PYTHON_RESOLVER)
        symbols, gaps = _resolve_python_symbols(file_identity, path, status, before, after, PYTHON_RESOLVER)
        return ResolvedFile(record, symbols=symbols, gaps=gaps)

    resolver = TYPESCRIPT_RESOLVER if language == "typescript" else JAVASCRIPT_RESOLVER
    record = FileChangeRecord(file_identity, path, previous_path, status, resolver)
    regions, gaps = _resolve_line_hunk_regions(file_identity, before, after, resolver)
    return ResolvedFile(record, regions=regions, gaps=gaps)


def _flatten(resolved: ResolvedFile) -> tuple[ResolvedRepositoryEntity, ...]:
    file_identity = resolved.file_change.identity
    items = [ResolvedRepositoryEntity(file_identity, None)]
    items.extend(ResolvedRepositoryEntity(region.identity, file_identity) for region in resolved.regions)
    items.extend(ResolvedRepositoryEntity(symbol.identity, file_identity) for symbol in resolved.symbols)
    return tuple(items)


def _describe(resolved: ResolvedFile) -> dict[Identity, str]:
    """Human-legible labels for a resolved file's own entities — display
    only, never fed back into any identity/edge computation. A caller
    (e.g. `graph_bridge.prompt_run_graph`'s optional `entity_labels`) may
    thread these through so a rendered graph shows real paths/names
    instead of opaque canonical ids."""
    record = resolved.file_change
    file_label = f"{record.previous_path} → {record.path}" if record.status is FileChangeStatus.RENAMED and record.previous_path else record.path
    labels = {record.identity: file_label}
    for region in resolved.regions:
        labels[region.identity] = f"{record.path} (lines {region.start_line}-{region.end_line})"
    for symbol in resolved.symbols:
        labels[symbol.identity] = symbol.qualified_name
    return labels


def resolve_repository_entities(
    *, repository_key: str, change_set_id: str, evidence: ChangeEvidence,
    content_before: Mapping[str, bytes], content_after: Mapping[str, bytes],
) -> tuple[tuple[ResolvedRepositoryEntity, ...], tuple[str, ...], dict[Identity, str]]:
    """Resolve one ChangeSet's full `ChangeEvidence` into the flat
    `(entity, parent)` shape `build_graph`/`compose_graph` consume directly
    via their `resolved_entities` parameter, plus a display-only labels map
    (`graph_bridge.prompt_run_graph`'s optional `entity_labels`). `evidence
    .renamed` is processed first so a renamed file is never ALSO
    double-processed as a separate create+delete pair."""
    entities: list[ResolvedRepositoryEntity] = []
    gaps: list[str] = []
    labels: dict[Identity, str] = {}
    handled: set[str] = set()

    def _record(resolved: ResolvedFile) -> None:
        entities.extend(_flatten(resolved))
        gaps.extend(resolved.gaps)
        labels.update(_describe(resolved))

    for old_path, new_path in evidence.renamed:
        handled.add(old_path)
        handled.add(new_path)
        _record(resolve_file_change(
            repository_key=repository_key, change_set_id=change_set_id, path=new_path, previous_path=old_path,
            status=FileChangeStatus.RENAMED, before=content_before.get(old_path), after=content_after.get(new_path),
        ))

    for path in evidence.created:
        if path in handled:
            continue
        _record(resolve_file_change(
            repository_key=repository_key, change_set_id=change_set_id, path=path, previous_path=None,
            status=FileChangeStatus.CREATED, before=None, after=content_after.get(path),
        ))

    for path in evidence.modified:
        _record(resolve_file_change(
            repository_key=repository_key, change_set_id=change_set_id, path=path, previous_path=None,
            status=FileChangeStatus.MODIFIED, before=content_before.get(path), after=content_after.get(path),
        ))

    for path in evidence.deleted:
        if path in handled:
            continue
        _record(resolve_file_change(
            repository_key=repository_key, change_set_id=change_set_id, path=path, previous_path=None,
            status=FileChangeStatus.DELETED, before=content_before.get(path), after=None,
        ))

    return tuple(entities), tuple(gaps), labels
