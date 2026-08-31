"""Weighted requirement coverage mathematics with explicit states and recalculable components."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from .alignment import AlignmentResult, AlignmentStatus
from .contracts import ClaimKind
from .vector import Dimension

_METHOD = "alignment-math"
_VERSION = "1"
_PARTIAL_VALUE = 0.5

class RequirementState(str, Enum):
    SATISFIED = "satisfied"; PARTIAL = "partial"; FAILED = "failed"; CONTRADICTED = "contradicted"; UNKNOWN = "unknown"

_STATE_VALUES = {
    RequirementState.SATISFIED: 1.0,
    RequirementState.PARTIAL: _PARTIAL_VALUE,
    RequirementState.FAILED: 0.0,
    RequirementState.CONTRADICTED: 0.0,
}

@dataclass(frozen=True, slots=True)
class RequirementTerm:
    requirement_id: str; weight: float; state: RequirementState; contribution: float | None; evaluated: bool; uncertainty: str

@dataclass(frozen=True, slots=True)
class AlignmentScore:
    numerator: float; denominator: float; value: float | None; components: tuple[RequirementTerm, ...]; method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str

    def dimension(self) -> Dimension:
        return Dimension("requirement_coverage", self.value, self.claim_kind, self.method, self.method_version, .8 if self.value is not None else None, self.uncertainty)

def _state_of(status: AlignmentStatus) -> RequirementState:
    if status is AlignmentStatus.SATISFIED: return RequirementState.SATISFIED
    if status is AlignmentStatus.PARTIALLY_SATISFIED: return RequirementState.PARTIAL
    if status is AlignmentStatus.NOT_SATISFIED: return RequirementState.FAILED
    if status is AlignmentStatus.CONTRADICTED: return RequirementState.CONTRADICTED
    return RequirementState.UNKNOWN

def score_alignment(alignment: AlignmentResult, weights: Mapping[str, float] | None = None) -> AlignmentScore:
    """Weighted coverage over evaluable requirements; unknowns are excluded, never counted as success."""
    components: list[RequirementTerm] = []
    numerator = 0.0
    denominator = 0.0
    unknown_ids: list[str] = []
    for judgment in alignment.judgments:
        requirement_id = f"req:{judgment.start}"
        weight = 1.0 if weights is None else weights.get(requirement_id, 1.0)
        if weight <= 0:
            raise ValueError("requirement weights must be positive")
        state = _state_of(judgment.status)
        evaluated = state is not RequirementState.UNKNOWN
        contribution = round(weight * _STATE_VALUES[state], 3) if evaluated else None
        if evaluated:
            numerator += contribution
            denominator += weight
        else:
            unknown_ids.append(requirement_id)
        components.append(RequirementTerm(requirement_id, weight, state, contribution, evaluated, judgment.uncertainty))
    value = round(numerator / denominator, 3) if denominator > 0 else None
    uncertainty = "every requirement was evaluable"
    if unknown_ids:
        uncertainty = f"unknown requirements excluded from the denominator, never counted as success: {unknown_ids}"
    return AlignmentScore(
        round(numerator, 3), round(denominator, 3), value, tuple(components), _METHOD, _VERSION,
        ClaimKind.DERIVED if value is not None else ClaimKind.UNKNOWN, uncertainty,
    )
