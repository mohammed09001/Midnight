"""Deterministic dataset admission checks; findings are not truth judgments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .dataset import DatasetRow
from .dataset_versioning import DatasetDefinition, DatasetSnapshot, snapshot


class PoisoningFindingKind(str, Enum):
    ANOMALOUS_LABEL = "anomalous_label"
    DUPLICATE_EXPERIENCE = "duplicate_experience"
    CROSS_PROJECT_CONTAMINATION = "cross_project_contamination"
    SUSPICIOUS_FEEDBACK = "suspicious_feedback"


@dataclass(frozen=True, slots=True)
class PoisoningFinding:
    kind: PoisoningFindingKind
    prompt_run_ids: tuple[str, ...]
    severity: str
    rationale: str


@dataclass(frozen=True, slots=True)
class DatasetAdmission:
    findings: tuple[PoisoningFinding, ...]
    requires_approval: bool
    approved_by: str | None = None

    def __post_init__(self) -> None:
        if self.approved_by is not None and not self.approved_by.strip():
            raise ValueError("approver must be non-empty when supplied")


def assess_dataset(rows: tuple[DatasetRow, ...], *, project_id: str) -> DatasetAdmission:
    """Find suspicious patterns without silently discarding evidence."""
    if not project_id.strip():
        raise ValueError("project id is required")
    findings: list[PoisoningFinding] = []
    by_fingerprint: dict[str, list[DatasetRow]] = {}
    by_feedback_actor: dict[str, list[DatasetRow]] = {}
    for row in rows:
        row_project = row.agent_metadata.get("project")
        if row_project is not None and row_project != project_id:
            findings.append(PoisoningFinding(PoisoningFindingKind.CROSS_PROJECT_CONTAMINATION, (row.prompt_run_id,), "high", "row project metadata differs from dataset project"))
        by_fingerprint.setdefault(_experience_fingerprint(row), []).append(row)
        actor = row.agent_metadata.get("feedback_actor")
        if actor and row.label is not None:
            by_feedback_actor.setdefault(actor, []).append(row)
    for grouped in by_fingerprint.values():
        if len(grouped) > 1:
            labels = {row.label for row in grouped}
            severity = "high" if len(labels) > 1 else "medium"
            findings.append(PoisoningFinding(PoisoningFindingKind.DUPLICATE_EXPERIENCE, tuple(sorted(row.prompt_run_id for row in grouped)), severity, "identical features and lineage repeat"))
            if len(labels) > 1:
                findings.append(PoisoningFinding(PoisoningFindingKind.ANOMALOUS_LABEL, tuple(sorted(row.prompt_run_id for row in grouped)), "high", "identical experience has conflicting labels"))
    for actor, grouped in by_feedback_actor.items():
        labels = {row.label for row in grouped}
        if len(grouped) >= 3 and len(labels) == 1:
            findings.append(PoisoningFinding(PoisoningFindingKind.SUSPICIOUS_FEEDBACK, tuple(sorted(row.prompt_run_id for row in grouped)), "medium", f"feedback actor {actor!r} supplied a single label for {len(grouped)} experiences"))
    findings.sort(key=lambda item: (item.kind.value, item.prompt_run_ids))
    return DatasetAdmission(tuple(findings), any(item.severity == "high" for item in findings))


def reviewed_snapshot(definition: DatasetDefinition, rows: tuple[DatasetRow, ...], *, project_id: str, approved_by: str | None = None) -> DatasetSnapshot:
    """Freeze only an assessed dataset; high-impact findings require an approver."""
    admission = assess_dataset(rows, project_id=project_id)
    if admission.requires_approval and approved_by is None:
        raise PermissionError("high-impact dataset poisoning findings require approval")
    return snapshot(definition, rows)


def _experience_fingerprint(row: DatasetRow) -> str:
    payload = {"features": dict(sorted(row.features.items())), "lineage": sorted(row.lineage)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
