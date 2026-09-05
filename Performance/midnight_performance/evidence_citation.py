"""Execution 06, Section E: safe evidence citations for the Desktop graph.

`GraphEdge.evidence` is a bare string tuple — nothing stops a careless
caller from putting raw human text into it. Several real domain types carry
exactly that: `VerificationEvidence.output` (raw command output, up to 4096
chars) and `FeedbackRecord.free_text` (raw human commentary) must never
reach the default Desktop graph. This module defines the safe shape and the
only functions permitted to build one from each domain's real evidence —
every builder below explicitly whitelists safe, structural fields and never
touches a raw-text field.

Raw prompt/output/code/command output requires a deeper, explicit,
policy-gated read and is out of scope for V1 — `detail_available` exists so
a future, separately-gated read path has somewhere to declare "yes, more
exists," without this module ever fetching or exposing it itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .feedback import FeedbackRecord
from .outcomes import OutcomeReference
from .verification import VerificationEvidence

_MAX_SUMMARY_LENGTH = 280


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    """A stable, safe pointer to one piece of underlying evidence — never
    the evidence's raw content."""

    reference_id: str
    evidence_kind: str
    project: str
    observed_at: datetime | None = None
    source: str | None = None
    detail_available: bool = False
    summary: str | None = None  # a derived, bounded, structural-only safe summary — never raw content

    def __post_init__(self) -> None:
        if not self.reference_id.strip() or not self.evidence_kind.strip() or not self.project.strip():
            raise ValueError("evidence citations require a reference id, evidence kind, and project")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("citation timestamps must be timezone-aware")
        if self.summary is not None and len(self.summary) > _MAX_SUMMARY_LENGTH:
            raise ValueError(f"citation summary must be a bounded safe derivation (<= {_MAX_SUMMARY_LENGTH} chars), not raw content")


def verification_citation(evidence: VerificationEvidence, *, project: str) -> EvidenceCitation:
    """Safe fields only: identity/source/status/duration/exit_code/changed
    file COUNT. Deliberately never `evidence.output` (raw command output)."""
    summary = f"status={evidence.status}"
    if evidence.exit_code is not None:
        summary += f" exit_code={evidence.exit_code}"
    summary += f" changed_files={len(evidence.changed_files)}"
    return EvidenceCitation(
        reference_id=evidence.identity, evidence_kind="verification_run", project=project,
        source=evidence.source.value, detail_available=bool(evidence.output), summary=summary,
    )


def feedback_citation(record: FeedbackRecord, *, project: str) -> EvidenceCitation:
    """Safe fields only: id/judgment/reasons/confidence/submitted_at.
    Deliberately never `record.free_text` (raw human commentary)."""
    summary = f"judgment={record.judgment.value}"
    if record.reasons:
        summary += f" reasons={','.join(reason.value for reason in record.reasons)}"
    return EvidenceCitation(
        reference_id=record.id, evidence_kind="feedback_record", project=project,
        observed_at=record.submitted_at, source=record.actor, detail_available=bool(record.free_text), summary=summary,
    )


def outcome_citation(reference: OutcomeReference, *, project: str) -> EvidenceCitation:
    """`OutcomeReference` is already fully structural — safe to cite verbatim."""
    return EvidenceCitation(
        reference_id=reference.external_id, evidence_kind="outcome_reference", project=project,
        observed_at=reference.occurred_at, source=reference.provider.value, summary=f"kind={reference.kind}",
    )
