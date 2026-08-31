"""Versioned, extensible taxonomy of coding tasks and problem areas; multi-label, with unknown categories preserved rather than guessed."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping
from .contracts import ClaimKind
from .scope_discipline import _CONFIG_NAMES, _is_test

_METHOD = "task-taxonomy"
TAXONOMY_VERSION = "1"

CANONICAL_PROBLEM_AREAS: tuple[str, ...] = (
    "authentication", "database", "ui", "performance", "testing",
    "refactoring", "dependency", "security", "configuration",
)
UNKNOWN_AREA = "unknown"

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "authentication": ("auth", "login", "logout", "session", "token", "oauth", "credential", "password", "sso"),
    "database": ("database", "sql", "query", "migration", "schema", "orm", "table", "index"),
    "ui": ("ui", "component", "render", "css", "layout", "button", "frontend", "screen"),
    "performance": ("performance", "latency", "throughput", "slow", "cache", "optimi", "benchmark"),
    "testing": ("test", "spec", "coverage", "mock", "fixture", "assert"),
    "refactoring": ("refactor", "rename", "extract", "simplify", "cleanup", "restructure"),
    "dependency": ("dependency", "package", "upgrade", "requirements", "lockfile", "version bump"),
    "security": ("security", "vulnerab", "exploit", "sanitiz", "csrf", "xss", "injection", "secret"),
    "configuration": ("config", "setting", "environment variable", "flag", "toml", "yaml", "yml"),
}
_DEPENDENCY_FILES = {"pyproject.toml", "requirements.txt", "package.json", "package-lock.json", "poetry.lock", "Pipfile", "Pipfile.lock", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock"}
_PATH_HINTS = {
    "testing": _is_test,
    "configuration": lambda path: PurePosixPath(path).name in _CONFIG_NAMES,
    "dependency": lambda path: PurePosixPath(path).name in _DEPENDENCY_FILES,
}


@dataclass(frozen=True, slots=True)
class TaxonomyLabel:
    area: str; confidence: float; evidence: tuple[str, ...]

    def __post_init__(self):
        if not self.area.strip(): raise ValueError("taxonomy label requires an area name")
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class TaxonomyClassification:
    subject_id: str; version: str; labels: tuple[TaxonomyLabel, ...]; repository_specific: tuple[str, ...]; claim_kind: ClaimKind; method: str; method_version: str; uncertainty: str

    def __post_init__(self):
        if not self.subject_id.strip(): raise ValueError("classification requires a subject id")
        if not self.version.strip(): raise ValueError("classification requires a taxonomy version")
        if not self.labels: raise ValueError("classification requires at least one label; use the unknown area when nothing matches")
        names = [label.area for label in self.labels]
        if len(names) != len(set(names)): raise ValueError("labels must not repeat an area")
        if any(name not in CANONICAL_PROBLEM_AREAS and name != UNKNOWN_AREA for name in names):
            raise ValueError("labels must use a canonical problem area or the unknown area; repository-specific components belong in repository_specific")
        if UNKNOWN_AREA in names and len(names) > 1:
            raise ValueError("the unknown area must not be combined with a matched canonical label")

    @property
    def areas(self) -> tuple[str, ...]:
        return tuple(label.area for label in self.labels)


def classify_taxonomy(subject_id: str, text: str, *, changed_paths: tuple[str, ...] = (), repository_components: Mapping[str, str] | None = None, min_confidence: float = 0.0, version: str = TAXONOMY_VERSION) -> TaxonomyClassification:
    """Multi-label classification from lexical keyword hits and changed-path hints; never a trained model.

    `repository_components` maps a caller-owned path prefix to a repository-specific component name;
    matches land in `repository_specific`, kept distinct from the versioned canonical vocabulary.
    """
    if not subject_id.strip(): raise ValueError("classification requires a subject id")
    repository_components = repository_components or {}
    lowered = text.lower()
    labels: list[TaxonomyLabel] = []
    for area in CANONICAL_PROBLEM_AREAS:
        keyword_hits = {keyword for keyword in _KEYWORDS.get(area, ()) if keyword in lowered}
        path_predicate = _PATH_HINTS.get(area)
        path_hits = {path for path in changed_paths if path_predicate and path_predicate(path)}
        evidence = tuple(sorted(keyword_hits | path_hits))
        if not evidence:
            continue
        confidence = round(min(1.0, len(evidence) / 3), 3)
        if confidence < min_confidence:
            continue
        labels.append(TaxonomyLabel(area, confidence, evidence))
    repo_hits: dict[str, set[str]] = {}
    for path in changed_paths:
        for prefix, component in repository_components.items():
            if path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/"):
                repo_hits.setdefault(component, set()).add(path)
    repository_specific = tuple(sorted(repo_hits))
    if not labels:
        labels.append(TaxonomyLabel(UNKNOWN_AREA, 0.0, ()))
    claim_kind = ClaimKind.INFERRED if labels[0].area != UNKNOWN_AREA else ClaimKind.UNKNOWN
    parts = ["lexical keyword and changed-path heuristics, never a trained model; multi-label, evidence-cited per area"]
    if labels[0].area == UNKNOWN_AREA:
        parts.append("no canonical problem area matched; unknown is reported explicitly rather than guessed")
    if repository_specific:
        parts.append(f"repository-specific components matched via caller-supplied path prefixes: {list(repository_specific)}")
    return TaxonomyClassification(subject_id, version, tuple(labels), repository_specific, claim_kind, _METHOD, version, "; ".join(parts))
