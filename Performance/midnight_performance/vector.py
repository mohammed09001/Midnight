"""Decomposable multi-dimensional performance vectors; no single authoritative score."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
from .prompt_analysis import PromptMetrics
from .repository_capture import ChangeEvidence
from .scope_discipline import FindingKind, ScopeDiscipline
from .verification_quality import VerificationQuality

_METHOD = "performance-vector"
_VERSION = "1"
_CANONICAL = ("prompt_clarity", "prompt_specificity", "requirement_coverage", "constraint_compliance", "scope_discipline", "change_discipline", "verification_quality", "evidence_completeness", "user_satisfaction", "runtime_outcome_quality", "attribution_confidence")
_HARD_FINDINGS = {FindingKind.FORBIDDEN_CHANGE, FindingKind.MISSING_REQUESTED_WORK, FindingKind.UNEXPECTED_DELETION}
_SOFT_FINDINGS = {FindingKind.UNRELATED_CHANGE, FindingKind.IMPLEMENTATION_DRIFT, FindingKind.SCOPE_EXPANSION, FindingKind.EXCESSIVE_BLAST_RADIUS}
_WEAK = {ClaimKind.INFERRED, ClaimKind.STATISTICAL, ClaimKind.PREDICTED, ClaimKind.RECOMMENDED}

CANONICAL_DIMENSIONS: tuple[str, ...] = _CANONICAL

@dataclass(frozen=True, slots=True)
class Dimension:
    name: str; value: float | None; claim_kind: ClaimKind; method: str; method_version: str; confidence: float | None; uncertainty: str
    def __post_init__(self):
        if not self.name.strip(): raise ValueError("dimension name is required")
        if self.value is not None and not 0 <= self.value <= 1: raise ValueError("dimension value must be between zero and one")
        if (self.value is None) is not (self.claim_kind is ClaimKind.UNKNOWN): raise ValueError("unknown claims must carry no value and valued claims must not be unknown")
        if not all((self.method.strip(), self.method_version.strip(), self.uncertainty.strip())): raise ValueError("dimensions require method, version, and uncertainty disclosure")
        if self.claim_kind in _WEAK and self.confidence is None: raise ValueError("weak claim dimensions require confidence")
        if self.confidence is not None and not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")

@dataclass(frozen=True, slots=True)
class PerformanceVector:
    """Per-prompt-run decomposable dimensions; aggregate scoring is intentionally absent."""
    prompt_run_id: str; dimensions: tuple[Dimension, ...]; method_version: str
    def __post_init__(self):
        if not self.prompt_run_id.strip(): raise ValueError("prompt_run_id is required")
        names = [item.name for item in self.dimensions]
        if len(names) != len(set(names)): raise ValueError("dimension names must be unique")
    def get(self, name: str) -> Dimension | None:
        return next((item for item in self.dimensions if item.name == name), None)

def build_vector(prompt_run_id: str, dimensions: tuple[Dimension, ...], *, method_version: str = _VERSION) -> PerformanceVector:
    return PerformanceVector(prompt_run_id, tuple(dimensions), method_version)

def _dimension(name: str, value: float | None, claim_kind: ClaimKind, uncertainty: str, confidence: float | None = None, method: str = _METHOD, method_version: str = _VERSION) -> Dimension:
    return Dimension(name, value, claim_kind, method, method_version, confidence, uncertainty)

def dimension_from_metrics(metrics: PromptMetrics) -> tuple[Dimension, ...]:
    return (
        _dimension("prompt_clarity", metrics.clarity, ClaimKind.DERIVED, "transparent structural prompt metric"),
        _dimension("prompt_specificity", metrics.specificity, ClaimKind.DERIVED, "transparent structural prompt metric"),
    )

def dimension_from_scope(scope: ScopeDiscipline) -> tuple[Dimension, ...]:
    kinds = {finding.kind for finding in scope.findings}
    hard_hit, soft_hit = kinds & _HARD_FINDINGS, kinds & _SOFT_FINDINGS
    scope_dim = (
        _dimension("scope_discipline", 1.0, ClaimKind.DERIVED, "no scope discipline findings against requested scope", .8) if not kinds else
        _dimension("scope_discipline", 0.0, ClaimKind.DERIVED, f"hard scope findings: {sorted(item.value for item in hard_hit)}", .8) if hard_hit else
        _dimension("scope_discipline", 0.5, ClaimKind.DERIVED, f"soft scope findings: {sorted(item.value for item in soft_hit)}", .8)
    )
    change_dim = (
        _dimension("change_discipline", 1.0, ClaimKind.DERIVED, "no change discipline findings against requested scope", .8) if not kinds else
        _dimension("change_discipline", 0.0, ClaimKind.DERIVED, f"hard change findings: {sorted(item.value for item in hard_hit)}", .8) if hard_hit else
        _dimension("change_discipline", 0.5, ClaimKind.DERIVED, f"soft change findings: {sorted(item.value for item in soft_hit)}", .8)
    )
    return (scope_dim, change_dim)

def dimension_from_verification_quality(quality: VerificationQuality) -> tuple[Dimension, ...]:
    requested = len(quality.requested)
    completeness = round((requested - len(quality.missing)) / requested, 3) if requested else None
    return (
        _dimension("verification_quality", quality.coverage, ClaimKind.DERIVED, f"requested-kind coverage; behavior_exercised={quality.behavior_exercised} is tracked separately", .8),
        _dimension("evidence_completeness", completeness, ClaimKind.DERIVED if completeness is not None else ClaimKind.UNKNOWN, "requested kinds with any evidence, executed or reported" if completeness is not None else "no requested verification kinds", .8),
    )

def unknown_dimension(name: str, reason: str) -> Dimension:
    return _dimension(name, None, ClaimKind.UNKNOWN, reason)
