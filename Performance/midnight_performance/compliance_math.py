"""Transparent constraint compliance mathematics; every violation stays individually visible."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .alignment import AlignmentResult, AlignmentStatus, _banned_paths
from .contracts import ClaimKind
from .repository_capture import ChangeEvidence
from .vector import Dimension

_METHOD = "compliance-math"
_VERSION = "1"
_HARD_MARKERS = ("must", "do not", "never", "cannot", "forbidden", "required to")
_DEFAULT_SOFT_MARKERS = ("should", "prefer", "ideally", "optional", "if possible")

class ConstraintSeverity(str, Enum):
    HARD = "hard"; SOFT = "soft"

@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    constraint: str; severity: ConstraintSeverity; evidence: tuple[str, ...]; method: str; method_version: str; uncertainty: str

@dataclass(frozen=True, slots=True)
class ComplianceScore:
    value: float | None; numerator: float; denominator: float; hard_violations: tuple[ConstraintViolation, ...]; soft_violations: tuple[ConstraintViolation, ...]; unverified: tuple[str, ...]; method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str

    def dimension(self) -> Dimension:
        return Dimension("constraint_compliance", self.value, self.claim_kind, self.method, self.method_version, .8 if self.value is not None else None, self.uncertainty)

def _severity_of(text: str, soft_markers: tuple[str, ...]) -> ConstraintSeverity:
    low = text.lower()
    return ConstraintSeverity.SOFT if any(marker in low for marker in soft_markers) else ConstraintSeverity.HARD

def score_compliance(alignment: AlignmentResult, changes: ChangeEvidence, *, soft_markers: tuple[str, ...] = _DEFAULT_SOFT_MARKERS) -> ComplianceScore:
    """Compliance over named-path constraints; violations are exposed individually, never aggregated away."""
    changed = {path.lower() for path in changes.created + changes.modified + changes.deleted}
    hard: list[ConstraintViolation] = []
    soft: list[ConstraintViolation] = []
    unverified: list[str] = []
    numerator = 0.0
    denominator = 0.0
    for judgment in alignment.judgments:
        if not any(marker in judgment.text.lower() for marker in _HARD_MARKERS + soft_markers):
            continue
        severity = _severity_of(judgment.text, soft_markers)
        banned = _banned_paths(judgment.text)
        violated = tuple(sorted(path for path in changes.created + changes.modified + changes.deleted if path.lower() in banned))
        if not banned:
            unverified.append(judgment.text)
            continue
        denominator += 1.0
        if violated:
            violation = ConstraintViolation(judgment.text, severity, violated, _METHOD, _VERSION, judgment.uncertainty)
            (hard if severity is ConstraintSeverity.HARD else soft).append(violation)
        else:
            numerator += 1.0
    value = round(numerator / denominator, 3) if denominator > 0 else None
    parts = [f"{len(hard)} hard and {len(soft)} soft violations exposed individually"]
    if unverified:
        parts.append(f"{len(unverified)} constraints name no verifiable object and stay excluded, never counted as compliant")
    uncertainty = "; ".join(parts)
    return ComplianceScore(
        value, numerator, denominator, tuple(hard), tuple(soft), tuple(unverified), _METHOD, _VERSION,
        ClaimKind.DERIVED if value is not None else ClaimKind.UNKNOWN, uncertainty,
    )
