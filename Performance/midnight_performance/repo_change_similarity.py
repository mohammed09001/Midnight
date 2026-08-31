"""File/Change-Set-level similarity; falls back gracefully when deeper symbol resolution is unavailable, per the current repository's own resolver."""
from __future__ import annotations
from pathlib import PurePosixPath
from .change_intelligence import ChangeKind, classify
from .repository_capture import ChangeEvidence

_METHOD = "repository-change-similarity"
_VERSION = "1"


def _jaccard(a: frozenset, b: frozenset) -> float | None:
    union = a | b
    return round(len(a & b) / len(union), 3) if union else None


def repository_change_similarity(a: ChangeEvidence, b: ChangeEvidence) -> tuple[float | None, tuple[str, ...]]:
    """Blend exact path overlap, containing-directory overlap (a module proxy), and semantic change-category overlap.

    `resolve_change` in this repository is a path-parser stub with no real symbol resolution, so directory-level
    grouping is the honest stand-in for "module" until deeper structural resolution exists; this is the documented
    file/Change-Set-level fallback, not a shortcut.
    """
    paths_a = frozenset(a.created + a.modified + a.deleted)
    paths_b = frozenset(b.created + b.modified + b.deleted)
    if not paths_a or not paths_b:
        return None, ()
    dirs_a = frozenset(str(PurePosixPath(path).parent) for path in paths_a)
    dirs_b = frozenset(str(PurePosixPath(path).parent) for path in paths_b)
    kinds_a = frozenset(item.kind for item in classify(a)) - {ChangeKind.UNKNOWN}
    kinds_b = frozenset(item.kind for item in classify(b)) - {ChangeKind.UNKNOWN}
    kind_component = _jaccard(kinds_a, kinds_b) if (kinds_a or kinds_b) else None
    components = [value for value in (_jaccard(paths_a, paths_b), _jaccard(dirs_a, dirs_b), kind_component) if value is not None]
    score = round(sum(components) / len(components), 3) if components else None
    evidence = tuple(sorted(paths_a & paths_b))[:5] + tuple(sorted(dirs_a & dirs_b))[:3] + tuple(sorted(kind.value for kind in (kinds_a & kinds_b)))
    return score, evidence
