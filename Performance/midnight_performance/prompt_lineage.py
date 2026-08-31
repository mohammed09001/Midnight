"""Explicit parent/child prompt revision lineage; diffed structurally and never inferred from text similarity."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from .prompt_analysis import PromptFeatures, RequirementType
from .stats_tests import ComparisonResult, compare_proportions

_METHOD = "prompt-lineage"
_VERSION = "1"


@dataclass(frozen=True, slots=True)
class PromptRevision:
    """One prompt version with an explicit, caller-asserted parent; the chain is identity, never a similarity guess."""
    version_id: str; parent_version_id: str | None; features: PromptFeatures; observed_at: datetime

    def __post_init__(self):
        if not self.version_id.strip(): raise ValueError("revision requires a version id")
        if self.parent_version_id is not None and not self.parent_version_id.strip(): raise ValueError("parent version id must be non-empty when present")
        if self.parent_version_id == self.version_id: raise ValueError("a revision cannot declare itself as its own parent")
        if self.observed_at.tzinfo is None: raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PromptLineageLink:
    parent_version_id: str; child_version_id: str
    added_constraints: tuple[str, ...]; removed_constraints: tuple[str, ...]
    added_acceptance: tuple[str, ...]; removed_acceptance: tuple[str, ...]
    added_verification: tuple[str, ...]; removed_verification: tuple[str, ...]
    unchanged_requirements: int
    outcome_shift: ComparisonResult | None
    method: str; method_version: str; uncertainty: str

    def __post_init__(self):
        if not self.parent_version_id.strip() or not self.child_version_id.strip(): raise ValueError("lineage link requires both version ids")
        if self.parent_version_id == self.child_version_id: raise ValueError("a link cannot connect a revision to itself")
        if self.unchanged_requirements < 0: raise ValueError("unchanged requirement count cannot be negative")

    @property
    def constraints_changed(self) -> bool:
        return bool(self.added_constraints or self.removed_constraints)

    @property
    def acceptance_changed(self) -> bool:
        return bool(self.added_acceptance or self.removed_acceptance)

    @property
    def verification_changed(self) -> bool:
        return bool(self.added_verification or self.removed_verification)


def _texts(features: PromptFeatures, kind: RequirementType) -> frozenset[str]:
    return frozenset(item.text for item in features.requirements if item.type is kind)


def link_revisions(parent: PromptRevision, child: PromptRevision, *, parent_outcomes: tuple[int, int] | None = None, child_outcomes: tuple[int, int] | None = None) -> PromptLineageLink:
    """Diff two revisions by exact requirement-text set membership per type; this is structural, not a fuzzy text match.

    `child.parent_version_id` must equal `parent.version_id`: lineage is the caller's asserted identity
    chain, never something this function infers from how alike the prompt text looks.
    """
    if child.parent_version_id != parent.version_id:
        raise ValueError("child revision does not declare parent as its parent_version_id")
    parent_constraints, child_constraints = _texts(parent.features, RequirementType.CONSTRAINT), _texts(child.features, RequirementType.CONSTRAINT)
    parent_acceptance, child_acceptance = _texts(parent.features, RequirementType.ACCEPTANCE), _texts(child.features, RequirementType.ACCEPTANCE)
    parent_verification, child_verification = _texts(parent.features, RequirementType.VERIFICATION), _texts(child.features, RequirementType.VERIFICATION)
    parent_all = frozenset(item.text for item in parent.features.requirements)
    child_all = frozenset(item.text for item in child.features.requirements)
    outcome_shift = None
    if parent_outcomes is not None and child_outcomes is not None:
        outcome_shift = compare_proportions(parent_outcomes[0], parent_outcomes[1], child_outcomes[0], child_outcomes[1])
    parts = [f"{len(parent_all - child_all)} requirement lines removed and {len(child_all - parent_all)} added across all types; a rewritten line surfaces as one removal plus one addition, never a fuzzy match"]
    if outcome_shift is None:
        parts.append("outcome counts were not supplied for both revisions; outcome difference is unknown, not zero")
    return PromptLineageLink(
        parent.version_id, child.version_id,
        tuple(sorted(child_constraints - parent_constraints)), tuple(sorted(parent_constraints - child_constraints)),
        tuple(sorted(child_acceptance - parent_acceptance)), tuple(sorted(parent_acceptance - child_acceptance)),
        tuple(sorted(child_verification - parent_verification)), tuple(sorted(parent_verification - child_verification)),
        len(parent_all & child_all),
        outcome_shift, _METHOD, _VERSION, "; ".join(parts),
    )


def build_lineage(revisions: tuple[PromptRevision, ...], outcomes: Mapping[str, tuple[int, int]] | None = None) -> tuple[PromptLineageLink, ...]:
    """Link every revision in the history to its declared parent; an unresolved parent is a raised gap, never a silently dropped edge."""
    outcomes = outcomes or {}
    by_id = {item.version_id: item for item in revisions}
    ids = [item.version_id for item in revisions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate revision ids in the same lineage history")
    links = []
    for revision in revisions:
        if revision.parent_version_id is None:
            continue
        parent = by_id.get(revision.parent_version_id)
        if parent is None:
            raise ValueError(f"revision {revision.version_id} declares an unresolved parent {revision.parent_version_id}")
        links.append(link_revisions(parent, revision, parent_outcomes=outcomes.get(parent.version_id), child_outcomes=outcomes.get(revision.version_id)))
    return tuple(links)
