"""Canonical prompt-experience analytical dataset with raw evidence lineage."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping
from .contracts import CONTRACT_VERSION
from .feedback import FeedbackRecord
from .prompt_run import PromptRun
from .vector import PerformanceVector

DATASET_SCHEMA_VERSION = 1

@dataclass(frozen=True, slots=True)
class DatasetRow:
    prompt_run_id: str; observed_at: datetime; features: Mapping[str, float | None]; label: str | None; label_confidence: float | None; agent_metadata: Mapping[str, str]; lineage: tuple[str, ...]; schema_version: int = DATASET_SCHEMA_VERSION
    def __post_init__(self):
        if not self.prompt_run_id.strip(): raise ValueError("row requires a prompt run id")
        if self.observed_at.tzinfo is None: raise ValueError("observed_at must be timezone-aware")
        for name, value in self.features.items():
            if not name.strip(): raise ValueError("feature names must be non-empty")
            if value is not None and not 0 <= value <= 1: raise ValueError(f"feature {name} outside zero-one bounds")
        if self.label is not None and not self.label.strip(): raise ValueError("labels must be non-empty when present")
        if self.label_confidence is not None and not 0 <= self.label_confidence <= 1: raise ValueError("label confidence must be between zero and one")
        if any(not ref.strip() for ref in self.lineage): raise ValueError("lineage references must be non-empty")
        if self.schema_version < 1: raise ValueError("schema version must be positive")

    def feature(self, name: str) -> float | None:
        return self.features.get(name)

@dataclass(frozen=True, slots=True)
class PromptExperienceDataset:
    name: str; rows: tuple[DatasetRow, ...]; feature_names: tuple[str, ...]; schema_version: int = DATASET_SCHEMA_VERSION
    def __post_init__(self):
        if not self.name.strip(): raise ValueError("dataset name is required")
        ids = [row.prompt_run_id for row in self.rows]
        if len(ids) != len(set(ids)): raise ValueError("duplicate rows for the same prompt run")
        for row in self.rows:
            if set(row.features) != set(self.feature_names): raise ValueError(f"row {row.prompt_run_id} does not match the dataset feature schema")
        if self.schema_version < 1: raise ValueError("schema version must be positive")

    def row(self, prompt_run_id: str) -> DatasetRow | None:
        return next((item for item in self.rows if item.prompt_run_id == prompt_run_id), None)

def build_row(prompt_run: PromptRun, vector: PerformanceVector, *, observed_at: datetime, judgment: FeedbackRecord | None = None, agent_metadata: Mapping[str, str] | None = None) -> DatasetRow:
    """Assemble one dataset row; lineage keeps raw references so features can be regenerated."""
    lineage = tuple(ref for ref in (*prompt_run.agent_run_ids, *prompt_run.change_set_ids, *prompt_run.verification_ids, *prompt_run.feedback_ids, *prompt_run.outcome_references, *prompt_run.analysis_ids, *([prompt_run.episode_id] if prompt_run.episode_id else [])) if ref and ref.strip())
    label = judgment.judgment.value if judgment else None
    label_confidence = judgment.confidence if judgment else None
    return DatasetRow(
        prompt_run.prompt_run_id, observed_at,
        {dimension.name: dimension.value for dimension in vector.dimensions},
        label, label_confidence,
        dict(agent_metadata or {}),
        lineage,
    )
