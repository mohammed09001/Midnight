"""Composite scores as optional UX views; components remain the analytical truth."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from .contracts import ClaimKind
from .vector import PerformanceVector

_METHOD = "composite-view"
_DEFAULT_VERSION = "1"

@dataclass(frozen=True, slots=True)
class CompositeComponent:
    name: str; value: float; weight: float; contribution: float

@dataclass(frozen=True, slots=True)
class CompositeView:
    name: str; value: float | None; weights_version: str; components: tuple[CompositeComponent, ...]; excluded_unknowns: tuple[str, ...]; unweighted: tuple[str, ...]; method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str
    def __post_init__(self):
        if not self.name.strip(): raise ValueError("composite view name is required")
        if self.value is not None and not 0 <= self.value <= 1: raise ValueError("composite value must be between zero and one")

def compose(name: str, vector: PerformanceVector, weights: Mapping[str, float], *, weights_version: str = _DEFAULT_VERSION) -> CompositeView:
    """Optional weighted view over valued dimensions; full decomposition is always carried."""
    if not weights:
        raise ValueError("composite weights are required")
    if weights_version.strip() != weights_version or not weights_version:
        raise ValueError("weights version is required and must not contain whitespace")
    by_name = {item.name: item for item in vector.dimensions}
    unknown_names = [key for key in weights if key not in by_name]
    if unknown_names:
        raise ValueError(f"weights reference absent dimensions: {sorted(unknown_names)}")
    for key, weight in weights.items():
        if weight <= 0:
            raise ValueError("composite weights must be positive")
    components: list[CompositeComponent] = []
    numerator = 0.0
    denominator = 0.0
    for key, weight in weights.items():
        dimension = by_name[key]
        if dimension.value is None:
            continue
        contribution = round(weight * dimension.value, 3)
        components.append(CompositeComponent(key, dimension.value, weight, contribution))
        numerator += contribution
        denominator += weight
    excluded_unknowns = tuple(sorted(item.name for item in vector.dimensions if item.name not in weights and item.value is None))
    unweighted = tuple(sorted(item.name for item in vector.dimensions if item.name not in weights and item.value is not None))
    value = round(numerator / denominator, 3) if denominator > 0 else None
    uncertainty = "optional UX view; components are the analytical truth and downstream models must never train solely on this composite"
    if excluded_unknowns:
        uncertainty += f"; unknown dimensions excluded: {list(excluded_unknowns)}"
    if unweighted:
        uncertainty += f"; valued dimensions without weights excluded: {list(unweighted)}"
    return CompositeView(
        name, value, weights_version, tuple(components), excluded_unknowns, unweighted, _METHOD, weights_version,
        ClaimKind.DERIVED if value is not None else ClaimKind.UNKNOWN, uncertainty,
    )
