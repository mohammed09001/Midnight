"""Change discipline mathematics normalized by task category, not global thresholds."""
from __future__ import annotations
from dataclasses import dataclass
from .change_metrics import ChangeEvidence, ChangeMetrics, measure
from .contracts import ClaimKind
from .scope_discipline import TaskType, _EXPANSION_FRACTION, _MAX_DIRS, assess_scope
from .vector import Dimension

_METHOD = "change-discipline-math"
_VERSION = "1"
_IMPACT_TOLERANCE = {TaskType.BUG_FIX: 2, TaskType.FEATURE_ADDITION: 4, TaskType.REFACTOR: 3, TaskType.DOCUMENTATION: 1, TaskType.CONFIGURATION: 1, TaskType.UNKNOWN: 2}

@dataclass(frozen=True, slots=True)
class ChangeMeasure:
    name: str; value: float | None; claim_kind: ClaimKind; uncertainty: str
    def __post_init__(self):
        if self.value is not None and not 0 <= self.value <= 1: raise ValueError("measure value must be between zero and one")
        if (self.value is None) is not (self.claim_kind is ClaimKind.UNKNOWN): raise ValueError("unknown measures carry no value; valued measures are not unknown")

@dataclass(frozen=True, slots=True)
class ChangeDisciplineScore:
    task_type: TaskType; components: tuple[ChangeMeasure, ...]; method: str; method_version: str

    def dimensions(self) -> tuple[Dimension, ...]:
        return tuple(
            Dimension(f"change_discipline.{item.name}", item.value, item.claim_kind, _METHOD, _VERSION, .8 if item.value is not None else None, item.uncertainty)
            for item in self.components
        )

def measure_change_discipline(requested: tuple[str, ...], changes: ChangeEvidence, task_type: TaskType = TaskType.UNKNOWN) -> ChangeDisciplineScore:
    """Normalized discipline measures; every threshold is contextual to the task category."""
    scope = assess_scope(requested, changes, task_type)
    metrics: ChangeMetrics = measure(changes)
    changed = metrics.files_touched
    deleted = metrics.deleted_files
    unrelated = next((len(finding.paths) for finding in scope.findings if finding.kind.value == "unrelated_change"), 0)
    unexpected_deletions = next((len(finding.paths) for finding in scope.findings if finding.kind.value == "unexpected_deletion"), 0)
    components: list[ChangeMeasure] = []
    if changed:
        fraction = unrelated / changed
        threshold = _EXPANSION_FRACTION[task_type]
        components.append(ChangeMeasure("scope_expansion", round(1 - min(1.0, fraction / threshold), 3), ClaimKind.DERIVED, f"unrequested fraction {round(fraction, 3)} normalized by {threshold} for {task_type.value}"))
        components.append(ChangeMeasure("unrelated_component_touch", round(1 - fraction, 3), ClaimKind.DERIVED, f"{unrelated} of {changed} touched paths are unrequested after task-type companion allowance"))
    else:
        components.append(ChangeMeasure("scope_expansion", None, ClaimKind.UNKNOWN, "no changed paths"))
        components.append(ChangeMeasure("unrelated_component_touch", None, ClaimKind.UNKNOWN, "no changed paths"))
    components.append(ChangeMeasure("locality", metrics.locality, ClaimKind.DERIVED, f"{metrics.directories_touched} directories touched; locality is the reciprocal spread"))
    if changed:
        dispersion = round(1 - min(1.0, metrics.directories_touched / _MAX_DIRS[task_type]), 3)
        components.append(ChangeMeasure("dispersion", max(dispersion, 0.0), ClaimKind.DERIVED, f"{metrics.directories_touched} directories normalized by {_MAX_DIRS[task_type]} allowed for {task_type.value}"))
    else:
        components.append(ChangeMeasure("dispersion", None, ClaimKind.UNKNOWN, "no changed paths"))
    if deleted:
        rate = unexpected_deletions / deleted
        components.append(ChangeMeasure("unexpected_deletion", round(1 - rate, 3), ClaimKind.DERIVED, f"{unexpected_deletions} of {deleted} deletions were unrequested"))
    else:
        components.append(ChangeMeasure("unexpected_deletion", None, ClaimKind.UNKNOWN, "no deletions to measure"))
    tolerance = _IMPACT_TOLERANCE[task_type]
    components.append(ChangeMeasure("structural_impact", round(1 - min(1.0, len(metrics.potential_impacts) / tolerance), 3), ClaimKind.DERIVED, f"impacts {list(metrics.potential_impacts)} normalized by tolerance {tolerance} for {task_type.value}"))
    return ChangeDisciplineScore(task_type, tuple(components), _METHOD, _VERSION)
