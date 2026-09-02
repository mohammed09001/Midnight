"""Versioned, evidence-backed capability baseline for improvement work.

This is deliberately a derived assessment.  It stores references to code and
tests supplied by the caller; it does not claim that a file name proves runtime
behaviour or become another evidence ledger.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

IMPROVEMENT_GATE_VERSION = "1"

class CapabilityState(str, Enum):
    PRESENT_DEEP = "present_deep"
    PRESENT_SHALLOW = "present_shallow"
    MISSING = "missing"
    DUPLICATE = "duplicate"
    UNVERIFIABLE = "unverifiable"

@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    location: str
    detail: str
    kind: str = "repository"

    def __post_init__(self) -> None:
        if not self.location.strip() or not self.detail.strip():
            raise ValueError("capability evidence needs a location and detail")

@dataclass(frozen=True, slots=True)
class ImprovementCapabilityGap:
    capability: str
    state: CapabilityState
    canonical_owner: str | None
    extend_owners: tuple[str, ...]
    evidence: tuple[CapabilityEvidence, ...]
    method_version: str = IMPROVEMENT_GATE_VERSION
    uncertainty: str = "derived repository assessment; execution behaviour requires fresh verification"

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise ValueError("capability is required")
        if self.state is not CapabilityState.UNVERIFIABLE and not self.evidence:
            raise ValueError("a classified capability requires concrete evidence")
        if self.state is CapabilityState.UNVERIFIABLE and not self.uncertainty.strip():
            raise ValueError("unverifiable capability must retain uncertainty")
        if self.canonical_owner is not None and not self.canonical_owner.strip():
            raise ValueError("canonical owner cannot be blank")

@dataclass(frozen=True, slots=True)
class ImprovementArchitectureGate:
    gaps: tuple[ImprovementCapabilityGap, ...]
    invariants: tuple[str, ...]
    version: str = IMPROVEMENT_GATE_VERSION

    def for_capability(self, capability: str) -> ImprovementCapabilityGap:
        for gap in self.gaps:
            if gap.capability == capability:
                return gap
        raise KeyError(capability)

DEFAULT_IMPROVEMENT_INVARIANTS = (
    "repository evidence is strongest for actual change",
    "AI-derived analysis remains qualified",
    "Performance does not host or control coding agents",
    "sibling products retain their own database ownership",
    "privacy is fail-closed for sensitive or unclassified fields",
)

def establish_improvement_gate(gaps: tuple[ImprovementCapabilityGap, ...], *, invariants: tuple[str, ...] = DEFAULT_IMPROVEMENT_INVARIANTS) -> ImprovementArchitectureGate:
    names = [gap.capability for gap in gaps]
    if len(names) != len(set(names)):
        raise ValueError("each capability may have one gate assessment")
    if not invariants or any(not item.strip() for item in invariants):
        raise ValueError("improvement invariants are required")
    return ImprovementArchitectureGate(gaps, invariants)
