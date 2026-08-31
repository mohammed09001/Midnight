"""User-invoked suggestions, guarded recommendations, and later-outcome review.

These value objects do not apply a change, submit a prompt, or control a
provider session.  They make evidence and missing sibling context visible so
the developer remains the decision-maker.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ClaimKind


_OUTCOME_DIRECTIONS = {"feedback": 1, "alignment": 1, "verification": 1, "rework": -1, "watch": 1}


@dataclass(frozen=True, slots=True)
class RecommendationEvidence:
    """A reference to retained evidence, scoped to the current project."""

    evidence_id: str
    project_id: str
    source: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.evidence_id, self.project_id, self.source)):
            raise ValueError("recommendation evidence requires an id, project, and source")


@dataclass(frozen=True, slots=True)
class PromptSuggestion:
    """An optional, explainable prompt revision; never an automatic rewrite."""

    original_prompt: str
    revised_prompt: str
    changes: tuple[str, ...]
    evidence: tuple[RecommendationEvidence, ...]
    project_id: str
    user_action_required: bool = True
    claim_kind: ClaimKind = ClaimKind.RECOMMENDED

    def __post_init__(self) -> None:
        if not self.original_prompt.strip() or not self.revised_prompt.strip():
            raise ValueError("suggestions require original and revised prompts")
        if self.original_prompt == self.revised_prompt or not self.changes:
            raise ValueError("a suggestion requires a changed prompt and an explanation")
        _validate_evidence(self.evidence, self.project_id)
        if not self.user_action_required:
            raise ValueError("prompt suggestions must require explicit user action")


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A qualified recommendation that remains advisory and non-causal."""

    text: str
    evidence: tuple[RecommendationEvidence, ...]
    confidence: float
    project_id: str
    allowed: bool
    reasons: tuple[str, ...]
    sibling_evidence_complete: bool
    disclosure: str
    user_action_required: bool = True
    claim_kind: ClaimKind = ClaimKind.RECOMMENDED

    def __post_init__(self) -> None:
        if not self.text.strip() or not 0 <= self.confidence <= 1:
            raise ValueError("recommendations require text and zero-one confidence")
        _validate_evidence(self.evidence, self.project_id)
        if not self.user_action_required:
            raise ValueError("recommendations must require explicit user action")
        if not self.sibling_evidence_complete and "incomplete" not in self.disclosure.lower():
            raise ValueError("incomplete sibling evidence must be disclosed")


@dataclass(frozen=True, slots=True)
class OutcomeMeasure:
    """An independently observed later outcome; recommendation scores are excluded."""

    name: str
    before: float
    after: float
    evidence: RecommendationEvidence

    def __post_init__(self) -> None:
        if self.name not in _OUTCOME_DIRECTIONS:
            raise ValueError("outcome must be feedback, alignment, verification, rework, or watch")
        if not 0 <= self.before <= 1 or not 0 <= self.after <= 1:
            raise ValueError("outcome values must be zero-one")

    @property
    def improvement(self) -> float:
        return round((self.after - self.before) * _OUTCOME_DIRECTIONS[self.name], 6)


@dataclass(frozen=True, slots=True)
class RecommendationEvaluation:
    recommendation_allowed: bool
    accepted: bool | None
    outcomes: tuple[OutcomeMeasure, ...]
    improved: bool | None
    disclosure: str
    claim_kind: ClaimKind = ClaimKind.DERIVED


def suggest_prompt(
    original_prompt: str,
    revised_prompt: str,
    changes: tuple[str, ...],
    evidence: tuple[RecommendationEvidence, ...],
    project_id: str,
) -> PromptSuggestion:
    return PromptSuggestion(original_prompt, revised_prompt, changes, evidence, project_id)


def suggest(
    text: str,
    evidence: tuple[RecommendationEvidence, ...],
    confidence: float,
    *,
    project_id: str,
    minimum_confidence: float = 0.7,
    sibling_evidence_complete: bool = True,
) -> Recommendation:
    if not 0 <= minimum_confidence <= 1:
        raise ValueError("minimum confidence must be zero-one")
    _validate_evidence(evidence, project_id)
    reasons = () if evidence and confidence >= minimum_confidence else ("insufficient evidence or confidence",)
    disclosure = (
        "Sibling evidence is incomplete; this recommendation may omit relevant outcome context."
        if not sibling_evidence_complete
        else "Recommendation is advisory; it does not establish causation."
    )
    return Recommendation(text, evidence, confidence, project_id, not reasons, reasons,
                          sibling_evidence_complete, disclosure)


def evaluate_recommendation(
    recommendation: Recommendation,
    accepted: bool | None,
    outcomes: tuple[OutcomeMeasure, ...],
) -> RecommendationEvaluation:
    """Evaluate from later external outcomes, never the recommendation's confidence."""
    for outcome in outcomes:
        if outcome.evidence.project_id != recommendation.project_id:
            raise ValueError("outcome evidence cannot cross project boundaries")
    if not recommendation.allowed or accepted is not True or not outcomes:
        improved = None
    else:
        improved = all(outcome.improvement > 0 for outcome in outcomes)
    disclosure = (
        "No improvement conclusion without an accepted recommendation and later independent outcomes."
        if improved is None
        else "Outcome comparison is associative, not causal."
    )
    return RecommendationEvaluation(recommendation.allowed, accepted, outcomes, improved, disclosure)


def _validate_evidence(evidence: tuple[RecommendationEvidence, ...], project_id: str) -> None:
    if not project_id.strip():
        raise ValueError("project id required")
    if any(item.project_id != project_id for item in evidence):
        raise ValueError("recommendation evidence cannot cross project boundaries")
