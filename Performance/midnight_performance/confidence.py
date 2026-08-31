"""Evidence-availability confidence that never mutates performance values."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
from .vector import PerformanceVector

_METHOD = "evidence-confidence"
_VERSION = "1"
_MISSING_FACTOR = 0.5

@dataclass(frozen=True, slots=True)
class ConfidenceReport:
    value: float | None; completeness: float | None; available_dimensions: tuple[str, ...]; unknown_dimensions: tuple[str, ...]; applied_factors: tuple[str, ...]; missing_factors: tuple[str, ...]; intervening_changes: tuple[str, ...]; method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str
    def __post_init__(self):
        if self.value is not None and not 0 <= self.value <= 1: raise ValueError("confidence must be between zero and one")

def assess_confidence(vector: PerformanceVector, *, code_resolution: float | None = None, watch_coverage: float | None = None, label_certainty: float | None = None, attribution_quality: float | None = None, intervening_changes: tuple[str, ...] = ()) -> ConfidenceReport:
    """Confidence from evidence availability; performance dimensions are inputs only, never outputs."""
    total = len(vector.dimensions)
    if not total:
        return ConfidenceReport(None, None, (), (), (), ("code_resolution", "watch_coverage", "label_certainty", "attribution_quality"), intervening_changes, _METHOD, _VERSION, ClaimKind.UNKNOWN, "no dimensions to assess")
    available = tuple(item.name for item in vector.dimensions if item.value is not None)
    unknown = tuple(item.name for item in vector.dimensions if item.value is None)
    completeness = round(len(available) / total, 3)
    confidence = completeness
    applied: list[str] = []
    missing: list[str] = []
    for name, factor in (("code_resolution", code_resolution), ("watch_coverage", watch_coverage), ("label_certainty", label_certainty), ("attribution_quality", attribution_quality)):
        if factor is None:
            missing.append(name)
            confidence *= _MISSING_FACTOR
            continue
        if not 0 <= factor <= 1:
            raise ValueError(f"{name} factor must be between zero and one")
        applied.append(f"{name}:{factor}")
        confidence *= factor
    if intervening_changes:
        confidence /= 1 + len(intervening_changes)
    confidence = round(min(confidence, 1.0), 3)
    parts = [f"{len(unknown)} of {total} dimensions are unknown; missing evidence lowers confidence, never performance"]
    if missing:
        parts.append(f"unprovided factors penalized by {_MISSING_FACTOR}: {missing}")
    if intervening_changes:
        parts.append(f"confidence divided by 1 + {len(intervening_changes)} intervening changes")
    return ConfidenceReport(
        confidence, completeness, available, unknown, tuple(applied), tuple(missing), intervening_changes,
        _METHOD, _VERSION, ClaimKind.DERIVED, "; ".join(parts),
    )
