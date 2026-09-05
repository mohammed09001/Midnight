"""External repository structural-analogy engine (Execution RI-14).

Comparison is dimension-by-dimension against typed structural facts, never
free-text similarity: ``RepositoryProfile`` carries no description/README
field, so nothing here can be fed keyword soup and asked "is this similar."
A dimension the caller cannot back with typed facts on both sides is
recorded ``comparable=False`` with an honest reason, never guessed from a
name or a blurb.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..contracts import Identity
from .contracts import (
    AnalogyDimension,
    AnalogyRecord,
    DimensionComparison,
    ExternalSourceRef,
    ProjectEntityRef,
    analogy_record_identity,
)
from .identities import RepoIdentity
from .sources import Freshness

DERIVATION_METHOD = "structural-analogy-compare"
DERIVATION_VERSION = "1"


@dataclass(frozen=True, slots=True)
class RepositoryProfile:
    """Typed structural facts about one side of a comparison.

    Deliberately has no free-text "description"/"readme" field: the
    comparison engine below can only compare what is here, so keyword-only
    similarity is structurally impossible to feed it. Set-valued facts
    default to ``None`` ("not investigated") rather than an empty set, so
    "we looked and found none" (an empty ``frozenset``) is never confused
    with "we never gathered this fact" -- only the former is comparable.
    """

    architectural_role: str
    language: str
    evidence_ids: tuple[str, ...]
    dependencies: frozenset[str] | None = None
    protocols: frozenset[str] | None = None
    data_flow_patterns: frozenset[str] | None = None
    failure_modes: frozenset[str] | None = None
    test_strategy: str | None = None
    scale_class: str | None = None

    def __post_init__(self) -> None:
        if not self.architectural_role.strip():
            raise ValueError("repository profiles require an architectural role")
        if not self.language.strip():
            raise ValueError("repository profiles require a language")
        if not self.evidence_ids:
            raise ValueError("repository profiles require at least one evidence id")


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float | None:
    union = left | right
    if not union:
        return None
    return round(len(left & right) / len(union), 4)


def _compare_role(internal: RepositoryProfile, external: RepositoryProfile, evidence: tuple[str, ...]) -> DimensionComparison:
    similar = internal.architectural_role.strip().lower() == external.architectural_role.strip().lower()
    return DimensionComparison(
        dimension=AnalogyDimension.ARCHITECTURAL_ROLE,
        comparable=True,
        similarity=1.0 if similar else 0.0,
        basis=f"internal role '{internal.architectural_role}' vs external role '{external.architectural_role}'",
        evidence_ids=evidence,
    )


def _combine(left: frozenset[str] | None, right: frozenset[str] | None) -> frozenset[str] | None:
    """Union two optional fact sets from the same profile; ``None`` only if both are unknown."""
    if left is None and right is None:
        return None
    return (left or frozenset()) | (right or frozenset())


def _compare_set(
    dimension: AnalogyDimension,
    internal_set: frozenset[str] | None,
    external_set: frozenset[str] | None,
    label: str,
    evidence: tuple[str, ...],
) -> DimensionComparison:
    if internal_set is None or external_set is None:
        return DimensionComparison(
            dimension=dimension,
            comparable=False,
            similarity=None,
            basis=f"{label} was not investigated on at least one side; not comparable",
        )
    score = _jaccard(internal_set, external_set)
    if score is None:
        return DimensionComparison(
            dimension=dimension,
            comparable=False,
            similarity=None,
            basis=f"neither side reports any {label}; no signal to compare",
        )
    overlap = sorted(internal_set & external_set)
    union = sorted(internal_set | external_set)
    return DimensionComparison(
        dimension=dimension,
        comparable=True,
        similarity=score,
        basis=f"{label} overlap: {overlap} of {union}",
        evidence_ids=evidence,
    )


def _compare_text(
    dimension: AnalogyDimension, internal_value: str | None, external_value: str | None, label: str, evidence: tuple[str, ...]
) -> DimensionComparison:
    if internal_value is None or external_value is None:
        return DimensionComparison(
            dimension=dimension,
            comparable=False,
            similarity=None,
            basis=f"{label} unknown on at least one side; not comparable",
        )
    similar = internal_value.strip().lower() == external_value.strip().lower()
    return DimensionComparison(
        dimension=dimension,
        comparable=True,
        similarity=1.0 if similar else 0.0,
        basis=f"internal {label} '{internal_value}' vs external {label} '{external_value}'",
        evidence_ids=evidence,
    )


def compare_repositories(internal: RepositoryProfile, external: RepositoryProfile) -> tuple[DimensionComparison, ...]:
    """Every one of the six explicit dimensions, comparable or explicitly not."""
    evidence = tuple(dict.fromkeys(internal.evidence_ids + external.evidence_ids))
    return (
        _compare_role(internal, external, evidence),
        _compare_set(
            AnalogyDimension.DEPENDENCY_PROTOCOL_OVERLAP,
            _combine(internal.dependencies, internal.protocols),
            _combine(external.dependencies, external.protocols),
            "dependency/protocol",
            evidence,
        ),
        _compare_set(
            AnalogyDimension.COMPONENT_DATA_FLOW_PATTERN,
            internal.data_flow_patterns,
            external.data_flow_patterns,
            "component/data-flow pattern",
            evidence,
        ),
        _compare_set(
            AnalogyDimension.FAILURE_RELIABILITY_PROBLEM,
            internal.failure_modes,
            external.failure_modes,
            "failure/reliability",
            evidence,
        ),
        _compare_text(AnalogyDimension.TEST_STRATEGY, internal.test_strategy, external.test_strategy, "test strategy", evidence),
        _compare_text(
            AnalogyDimension.SCALE_MATURITY_CONSTRAINTS, internal.scale_class, external.scale_class, "scale/maturity class", evidence
        ),
    )


def build_analogy_record(
    project: Identity,
    external_repository: ExternalSourceRef,
    internal_entity_ref: ProjectEntityRef,
    internal: RepositoryProfile,
    external: RepositoryProfile,
    *,
    why_it_matters_now: str,
    meaningful_differences: tuple[str, ...],
    freshness: Freshness,
    now: datetime,
    cost_ref: RepoIdentity | None = None,
) -> AnalogyRecord:
    """Compare, score, and package one project-entity/external-repository analogy.

    ``confidence`` is the mean similarity across only the comparable
    dimensions -- a comparison with more honest "not comparable" gaps is
    never inflated by averaging in a fabricated score for them.
    """
    comparisons = compare_repositories(internal, external)
    comparable = [c for c in comparisons if c.comparable]
    if not comparable:
        raise ValueError("no dimension was comparable; refusing to fabricate an analogy")
    confidence = round(sum(c.similarity for c in comparable) / len(comparable), 4)
    evidence_ids = tuple(dict.fromkeys(eid for c in comparisons for eid in c.evidence_ids))
    if not evidence_ids:
        evidence_ids = (external_repository.identity.canonical,)
    identity = analogy_record_identity(
        project, external_repository.identity, internal_entity_ref.identity, DERIVATION_METHOD, DERIVATION_VERSION, comparisons
    )
    return AnalogyRecord(
        identity=identity,
        project=project,
        external_repository=external_repository.identity,
        internal_entity_ref=internal_entity_ref.identity,
        comparisons=comparisons,
        meaningful_differences=meaningful_differences,
        confidence=confidence,
        why_it_matters_now=why_it_matters_now,
        freshness=freshness,
        method=DERIVATION_METHOD,
        method_version=DERIVATION_VERSION,
        evidence_ids=evidence_ids,
        cost_ref=cost_ref,
        created_at=now,
    )


__all__ = [
    "DERIVATION_METHOD",
    "DERIVATION_VERSION",
    "RepositoryProfile",
    "build_analogy_record",
    "compare_repositories",
]
