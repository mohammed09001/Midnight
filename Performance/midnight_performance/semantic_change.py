"""Qualified semantic hypotheses built from structural evidence, never path names alone."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ClaimKind
from .structural_diff import ChangedSurface, StructuralEditKind, SurfaceKind
SEMANTIC_CHANGE_VERSION="1"
class SemanticLabel(str, Enum): FEATURE="feature"; REFACTOR="refactor"; TEST="test"; BEHAVIOR_AFFECTING="behavior_affecting"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class SemanticChangeEvent:
    labels: tuple[SemanticLabel,...]; structural_evidence: tuple[str,...]; supporting_evidence: tuple[str,...]; weakening_evidence: tuple[str,...]; confidence: float; claim_kind: ClaimKind; method: str; method_version: str; uncertainty: str
def classify_semantic_change(surfaces: tuple[ChangedSurface,...], *, prompt_evidence: tuple[str,...]=(), verification_evidence: tuple[str,...]=(), ai_evidence: tuple[str,...]=()) -> SemanticChangeEvent:
    edits={item.edit.kind for item in surfaces}; test_only=bool(surfaces) and all(item.surface is SurfaceKind.TEST for item in surfaces)
    labels=[]
    if test_only: labels.append(SemanticLabel.TEST)
    if StructuralEditKind.RENAME in edits or StructuralEditKind.MOVE in edits: labels.append(SemanticLabel.REFACTOR)
    if StructuralEditKind.INSERT in edits: labels.append(SemanticLabel.FEATURE)
    if StructuralEditKind.UPDATE in edits and any(item.surface is SurfaceKind.SOURCE for item in surfaces): labels.append(SemanticLabel.BEHAVIOR_AFFECTING)
    if not labels: labels=[SemanticLabel.UNKNOWN]
    structural=tuple(sorted({f"{item.edit.kind.value}:{(item.element.id if item.element else 'unresolved')}" for item in surfaces}))
    support=tuple(prompt_evidence+verification_evidence+ai_evidence); confidence=.7 if structural and not test_only else (.5 if structural else 0)
    return SemanticChangeEvent(tuple(dict.fromkeys(labels)),structural,support,(),confidence,ClaimKind.INFERRED,"structural-semantic-classifier",SEMANTIC_CHANGE_VERSION,"semantic purpose is hypothesis; optional AI evidence cannot replace structural facts")
