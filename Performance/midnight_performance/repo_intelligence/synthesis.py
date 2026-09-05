"""Evidence-grounded synthesis for bounded project knowledge.

The synthesizer consumes only claim candidates and evidence *references*;
raw prompts, source code, and untrusted web text never enter its public
result.  A model adapter may propose candidates upstream, but every citation
is re-grounded here before an insight can exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..contracts import ClaimKind
from .authorization import RepoIntelligenceAuthorization, ensure_same_project
from .contracts import (
    EvidenceBundle,
    LineageReceipt,
    ProjectInsight,
    project_insight_identity,
    validate_insight_against_bundle,
)


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    """A bounded interpretation proposal, never evidence in its own right."""

    topic: str
    statement: str
    claim_kind: ClaimKind
    evidence_refs: tuple[str, ...]
    supports: bool = True
    actionable_learning_direction: str | None = None

    def __post_init__(self) -> None:
        if not self.topic.strip() or not self.statement.strip():
            raise ValueError("claim candidates require a topic and statement")
        if len(self.statement) > 600:
            raise ValueError("claim candidate statement must stay bounded")
        if self.claim_kind in (ClaimKind.OBSERVED, ClaimKind.UNKNOWN):
            raise ValueError("claim candidates must be an interpretation, not observed or unknown evidence")
        if not self.evidence_refs:
            raise ValueError("claim candidates require cited evidence")
        if self.actionable_learning_direction is not None and not self.actionable_learning_direction.strip():
            raise ValueError("learning direction must not be blank")


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """A result is either a re-grounded insight or an explicit evidence gap."""

    insight: ProjectInsight | None
    cited_evidence_refs: tuple[str, ...]
    gaps: tuple[str, ...]
    contradictions: tuple[str, ...]
    actionable_learning_direction: str | None = None


def _ground(candidate: ClaimCandidate, bundle: EvidenceBundle) -> None:
    available = {item.ref for item in bundle.items}
    missing = sorted(set(candidate.evidence_refs) - available)
    if missing:
        raise ValueError(f"candidate cites evidence absent from bundle: {missing}")


def _contradicted(candidates: tuple[ClaimCandidate, ...]) -> tuple[str, ...]:
    polarities: dict[str, set[bool]] = {}
    refs: dict[str, set[str]] = {}
    for candidate in candidates:
        key = candidate.topic.strip().lower()
        polarities.setdefault(key, set()).add(candidate.supports)
        refs.setdefault(key, set()).update(candidate.evidence_refs)
    return tuple(
        f"contradictory evidence for {topic}: {', '.join(sorted(refs[topic]))}"
        for topic in sorted(polarities) if len(polarities[topic]) > 1
    )


def synthesize(
    bundle: EvidenceBundle,
    candidates: tuple[ClaimCandidate, ...],
    authorization: RepoIntelligenceAuthorization,
    *,
    now: datetime,
    lineage_receipt: LineageReceipt | None = None,
    max_evidence_age: timedelta = timedelta(days=30),
    method: str = "evidence-synthesis",
    method_version: str = "1",
) -> SynthesisResult:
    """Re-ground candidates, surface contradictions, and create at most one insight.

    This deterministic gate is deliberately downstream of any optional model:
    hallucinated citations, cross-project inputs, stale-only evidence, and
    contradictions become gaps rather than confident generated knowledge.
    """
    if now.tzinfo is None:
        raise ValueError("synthesis time must be timezone-aware")
    if max_evidence_age <= timedelta(0):
        raise ValueError("maximum evidence age must be positive")
    ensure_same_project(authorization, project=bundle.project)
    if lineage_receipt is not None and lineage_receipt.project != bundle.project:
        raise PermissionError("cross-project lineage receipt is denied")
    for candidate in candidates:
        _ground(candidate, bundle)
    contradictions = _contradicted(candidates)
    stale = tuple(sorted(item.ref for item in bundle.items if now - item.captured_at > max_evidence_age))
    gaps = list(bundle.gaps)
    if stale:
        gaps.append("stale evidence requires refresh before synthesis: " + ", ".join(stale))
    if contradictions:
        gaps.extend(contradictions)
    supported = tuple(candidate for candidate in candidates if candidate.supports)
    if not supported:
        gaps.append("no supported claim candidate; retain as an open question")
    if gaps:
        return SynthesisResult(None, (), tuple(sorted(set(gaps))), contradictions)

    # Stable order makes tie handling reproducible and makes cache identities safe.
    chosen = sorted(supported, key=lambda item: (item.topic.lower(), item.statement))[0]
    disclosure = None
    if bundle.one_sided_external():
        disclosure = "This is an external-evidence interpretation, not a fact about the project."
    insight = ProjectInsight(
        identity=project_insight_identity(bundle.project, bundle.identity, method, method_version, chosen.statement),
        project=bundle.project,
        statement=chosen.statement,
        claim_kind=chosen.claim_kind,
        method=method,
        method_version=method_version,
        uncertainty="derived from the cited bounded evidence; source evidence may change or be incomplete",
        evidence_bundle=bundle.identity,
        confidence=0.65,
        lineage_receipt=lineage_receipt.identity if lineage_receipt else None,
        requires_user_action=chosen.claim_kind is ClaimKind.RECOMMENDED,
        disclosure=disclosure,
        valid_from=now,
    )
    validate_insight_against_bundle(insight, bundle)
    return SynthesisResult(insight, tuple(sorted(set(chosen.evidence_refs))), (), (), chosen.actionable_learning_direction)


__all__ = ["ClaimCandidate", "SynthesisResult", "synthesize"]
