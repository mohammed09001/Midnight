"""Versioned curated prompt fixtures and isolated offline experiment records."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
@dataclass(frozen=True, slots=True)
class CuratedItem:
    item_id: str; version: int; prompt_run_id: str; prompt: str; expected_intent: tuple[str, ...]; constraints: tuple[str, ...]; code_references: tuple[str, ...]; expected_verification: tuple[str, ...]; outcome_label: str | None; provenance: tuple[str, ...]; parent_version: int | None = None
    def __post_init__(self):
        if not all((self.item_id.strip(), self.prompt_run_id.strip(), self.prompt.strip())) or self.version < 1 or not self.provenance: raise ValueError("curated item requires identity, input, version, and provenance")
@dataclass(frozen=True, slots=True)
class CuratedDataset:
    name: str; items: tuple[CuratedItem, ...] = ()
    def add(self, item: CuratedItem) -> "CuratedDataset":
        prior = [x for x in self.items if x.item_id == item.item_id]
        if any(x.version == item.version for x in prior): raise ValueError("duplicate item version")
        if item.parent_version is not None and item.parent_version not in {x.version for x in prior}: raise ValueError("missing parent item version")
        return CuratedDataset(self.name, self.items + (item,))
    def version(self, item_id: str, version: int) -> CuratedItem | None: return next((x for x in self.items if (x.item_id, x.version) == (item_id, version)), None)
@dataclass(frozen=True, slots=True)
class OfflineExperiment:
    experiment_id: str; dataset_name: str; item_versions: tuple[tuple[str, int], ...]; prompt_variant: str; isolated: bool; execution: tuple[str, ...]; changes: tuple[str, ...]; verification: tuple[str, ...]; evaluator_scores: tuple[float, ...]; claim_kind: ClaimKind = ClaimKind.DERIVED
    def __post_init__(self):
        if not all((self.experiment_id.strip(), self.dataset_name.strip(), self.prompt_variant.strip())) or not self.isolated: raise PermissionError("offline experiments require explicit isolated fixtures")
        if any(not 0 <= x <= 1 for x in self.evaluator_scores): raise ValueError("evaluator scores must be zero-one")
