"""Task-type contextual scope discipline findings over repository change evidence."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from .repository_capture import ChangeEvidence

_METHOD = "scope-heuristic"
_VERSION = "1"
_CONFIG_NAMES = {"pyproject.toml", "package.json", "tsconfig.json", "requirements.txt", "poetry.lock", "package-lock.json"}
_DOC_SUFFIXES = {".md", ".rst", ".txt"}

class TaskType(str, Enum):
    BUG_FIX = "bug_fix"; FEATURE_ADDITION = "feature_addition"; REFACTOR = "refactor"; DOCUMENTATION = "documentation"; CONFIGURATION = "configuration"; UNKNOWN = "unknown"

class FindingKind(str, Enum):
    MISSING_REQUESTED_WORK = "missing_requested_work"; FORBIDDEN_CHANGE = "forbidden_change"; UNEXPECTED_DELETION = "unexpected_deletion"; UNRELATED_CHANGE = "unrelated_change"; IMPLEMENTATION_DRIFT = "implementation_drift"; SCOPE_EXPANSION = "scope_expansion"; EXCESSIVE_BLAST_RADIUS = "excessive_blast_radius"

_MAX_DIRS = {TaskType.BUG_FIX: 2, TaskType.FEATURE_ADDITION: 4, TaskType.REFACTOR: 6, TaskType.DOCUMENTATION: 1, TaskType.CONFIGURATION: 1, TaskType.UNKNOWN: 3}
_EXPANSION_FRACTION = {TaskType.BUG_FIX: .25, TaskType.FEATURE_ADDITION: .5, TaskType.REFACTOR: .5, TaskType.DOCUMENTATION: .25, TaskType.CONFIGURATION: .25, TaskType.UNKNOWN: .33}

@dataclass(frozen=True, slots=True)
class DisciplineFinding:
    kind: FindingKind; paths: tuple[str, ...]; confidence: float; method: str; method_version: str; uncertainty: str
    def __post_init__(self):
        if not self.paths: raise ValueError("findings must name the evidence paths")
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")

@dataclass(frozen=True, slots=True)
class ScopeDiscipline:
    task_type: TaskType; findings: tuple[DisciplineFinding, ...]; method_version: str

def _is_test(path: str) -> bool:
    return path.startswith("tests/") or PurePosixPath(path).name.startswith("test_")

def _is_doc(path: str) -> bool:
    return PurePosixPath(path).suffix in _DOC_SUFFIXES

def _companion_allowed(path: str, task_type: TaskType) -> bool:
    name = PurePosixPath(path).name
    if task_type is TaskType.DOCUMENTATION:
        return _is_doc(path)
    if task_type is TaskType.CONFIGURATION:
        return name in _CONFIG_NAMES
    return _is_test(path) or name in _CONFIG_NAMES

def _within(path: str, scopes: tuple[str, ...]) -> bool:
    return any(path == scope or path.startswith(scope.rstrip("/") + "/") for scope in scopes)

def assess_scope(requested: tuple[str, ...], changes: ChangeEvidence, task_type: TaskType = TaskType.UNKNOWN, *, forbidden: tuple[str, ...] = ()) -> ScopeDiscipline:
    """Judge change discipline against requested scope; thresholds contextualize by task type."""
    if not requested:
        raise ValueError("requested scope is required to judge discipline")
    changed = tuple(sorted(set(changes.created + changes.modified)))
    touched = tuple(sorted(set(changed + changes.deleted)))
    findings: list[DisciplineFinding] = []

    def add(kind: FindingKind, paths: tuple[str, ...], confidence: float, uncertainty: str) -> None:
        findings.append(DisciplineFinding(kind, tuple(sorted(paths)), confidence, _METHOD, _VERSION, uncertainty))

    missing = tuple(r for r in requested if not any(_within(p, (r,)) for p in changed + changes.deleted))
    if missing:
        add(FindingKind.MISSING_REQUESTED_WORK, missing, .9, "requested scope has no corresponding change evidence")
    forbidden_hits = tuple(p for p in touched if _within(p, forbidden))
    if forbidden_hits:
        add(FindingKind.FORBIDDEN_CHANGE, forbidden_hits, .9, "change intersects explicitly forbidden scope")
    unexpected_deletions = tuple(p for p in changes.deleted if not _within(p, requested))
    if unexpected_deletions:
        add(FindingKind.UNEXPECTED_DELETION, unexpected_deletions, .8, "deletion was not part of the requested scope")
    unrequested = tuple(p for p in changed if not _within(p, requested) and not _companion_allowed(p, task_type) and not _within(p, forbidden))
    if unrequested:
        add(FindingKind.UNRELATED_CHANGE, unrequested, .7, "unrequested paths outside the task-type companion allowance")
        modified_unrequested = tuple(p for p in unrequested if p in changes.modified)
        if modified_unrequested:
            add(FindingKind.IMPLEMENTATION_DRIFT, modified_unrequested, .7, "existing files pulled away from the requested scope")
        if changed and len(unrequested) / len(changed) > _EXPANSION_FRACTION[task_type]:
            add(FindingKind.SCOPE_EXPANSION, unrequested, .6, f"unrequested fraction exceeds {_EXPANSION_FRACTION[task_type]} for {task_type.value}; expansion is aggregate, not per-file")
    directories = tuple({str(PurePosixPath(p).parent) for p in touched})
    if len(directories) > _MAX_DIRS[task_type]:
        add(FindingKind.EXCESSIVE_BLAST_RADIUS, directories, .6, f"threshold {_MAX_DIRS[task_type]} directories for {task_type.value}; minimal change is not assumed, the threshold is contextual")
    return ScopeDiscipline(task_type, tuple(findings), _VERSION)
