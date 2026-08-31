"""Claim-specific evidence authority rules for Midnight Performance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import ClaimKind


class ClaimType(str, Enum):
    REPOSITORY_CHANGE = "repository_change"
    COMMAND_RESULT = "command_result"
    RUNTIME_OUTCOME = "runtime_outcome"
    DATA_OUTCOME = "data_outcome"
    SECURITY_OUTCOME = "security_outcome"
    USER_EXPERIENCE = "user_experience"


class EvidenceSource(str, Enum):
    REPOSITORY_SNAPSHOT = "repository_snapshot"
    CHANGE_SET = "change_set"
    AGENT_FILE_EVENT = "agent_file_event"
    AGENT_PROSE = "agent_prose"
    STRUCTURED_COMMAND = "structured_command"
    WATCH_RUNTIME = "watch_runtime"
    WATCH_DATA = "watch_data"
    SECURITY = "security"
    USER_FEEDBACK = "user_feedback"
    AI_EVALUATION = "ai_evaluation"
    HEURISTIC = "heuristic"
    STATISTICAL = "statistical"
    MODEL_PREDICTION = "model_prediction"


_AUTHORITY: dict[ClaimType, tuple[EvidenceSource, ...]] = {
    ClaimType.REPOSITORY_CHANGE: (EvidenceSource.REPOSITORY_SNAPSHOT, EvidenceSource.CHANGE_SET, EvidenceSource.AGENT_FILE_EVENT, EvidenceSource.AGENT_PROSE),
    ClaimType.COMMAND_RESULT: (EvidenceSource.STRUCTURED_COMMAND, EvidenceSource.AGENT_PROSE),
    ClaimType.RUNTIME_OUTCOME: (EvidenceSource.WATCH_RUNTIME,),
    ClaimType.DATA_OUTCOME: (EvidenceSource.WATCH_DATA,),
    ClaimType.SECURITY_OUTCOME: (EvidenceSource.SECURITY,),
    ClaimType.USER_EXPERIENCE: (EvidenceSource.USER_FEEDBACK,),
}


@dataclass(frozen=True, slots=True)
class QualifiedClaim:
    claim_type: ClaimType
    source: EvidenceSource
    claim_kind: ClaimKind
    method: str | None = None
    method_version: str | None = None
    confidence: float | None = None
    uncertainty: str | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        weak = {ClaimKind.INFERRED, ClaimKind.STATISTICAL, ClaimKind.PREDICTED, ClaimKind.RECOMMENDED}
        if self.claim_kind in weak and not all((self.method, self.method_version, self.confidence is not None, self.uncertainty)):
            raise ValueError("weak claims require method, version, confidence, and uncertainty")

    @property
    def authority_rank(self) -> int:
        try:
            return _AUTHORITY[self.claim_type].index(self.source)
        except ValueError:
            return len(_AUTHORITY[self.claim_type])


def preferred(claims: list[QualifiedClaim]) -> QualifiedClaim:
    """Return the strongest applicable source; never upgrade claim qualification."""
    if not claims:
        raise ValueError("at least one claim is required")
    claim_type = claims[0].claim_type
    if any(item.claim_type is not claim_type for item in claims):
        raise ValueError("only like claim types can be compared")
    return min(claims, key=lambda item: item.authority_rank)
