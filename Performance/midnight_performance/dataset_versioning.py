"""Versioned dataset definitions with exact, reproducible snapshots."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from .dataset import DatasetRow

_METHOD = "dataset-snapshot"

@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    name: str; version: str; feature_schema: tuple[str, ...]; inclusion: str; require_labels: bool; starts_at: datetime | None = None; ends_at: datetime | None = None; label_policy: str = "latest_feedback_judgment"
    def __post_init__(self):
        if not self.name.strip() or not self.version.strip(): raise ValueError("definition requires name and version")
        if not self.feature_schema or any(not item.strip() for item in self.feature_schema): raise ValueError("feature schema must list non-empty feature names")
        if not self.inclusion.strip(): raise ValueError("inclusion criteria must be documented")
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at: raise ValueError("time bounds end before start")

@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    definition: DatasetDefinition; rows: tuple[DatasetRow, ...]; fingerprint: str; method: str = _METHOD

def snapshot(definition: DatasetDefinition, rows: tuple[DatasetRow, ...]) -> DatasetSnapshot:
    """Freeze exact membership deterministically; rebuilds with the same inputs reproduce the fingerprint."""
    included = []
    for row in rows:
        if set(definition.feature_schema) - set(row.features):
            continue
        if definition.require_labels and row.label is None:
            continue
        if definition.starts_at and row.observed_at < definition.starts_at:
            continue
        if definition.ends_at and row.observed_at > definition.ends_at:
            continue
        included.append(row)
    included.sort(key=lambda item: (item.observed_at, item.prompt_run_id))
    return DatasetSnapshot(definition, tuple(included), _fingerprint(definition, included))

def _fingerprint(definition: DatasetDefinition, rows: list[DatasetRow]) -> str:
    canonical = json.dumps({
        "name": definition.name, "version": definition.version, "schema": list(definition.feature_schema),
        "inclusion": definition.inclusion, "require_labels": definition.require_labels,
        "label_policy": definition.label_policy,
        "starts_at": definition.starts_at.isoformat() if definition.starts_at else None,
        "ends_at": definition.ends_at.isoformat() if definition.ends_at else None,
        "rows": [
            {"id": row.prompt_run_id, "observed_at": row.observed_at.isoformat(), "features": dict(sorted(row.features.items())), "label": row.label}
            for row in rows
        ],
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
