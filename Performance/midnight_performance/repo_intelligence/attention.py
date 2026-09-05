"""Attention-budget ranking and ledger (Execution RI-14).

Attention is a separate, finite resource from compute budget
(``cost_quality.BudgetLedger``): a candidate can be cheap to compute and
still cost the user's limited attention. This module supplies:

* the exact ranking score the spec asks for --
  ``learning_pressure * evidence_strength * novelty * expected_learning_value
  * timing_fit - (redundancy + interruption_cost + uncertainty + stale_risk)``;
* a rolling attention-spend ledger computed from durable ``Exposure``
  history, independent of any compute ledger.

Quiet queue, cooldown, dismiss suppression, protected focus, and user-pull
override are already fully enforced by
``terminal_learning.decide_terminal_card``/``TerminalContext`` -- this
module does not re-implement that gate, it supplies the ranking score that
feeds it and the separate, non-compute budget check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .contracts import Exposure, ExposureChannel, ExposureOutcome

_REACHED_USER = frozenset(
    {ExposureOutcome.OFFERED, ExposureOutcome.OPENED, ExposureOutcome.SAVED, ExposureOutcome.USED, ExposureOutcome.DISMISSED}
)

_FACTOR_LABELS = (
    "learning_pressure",
    "evidence_strength",
    "novelty",
    "expected_learning_value",
    "timing_fit",
)
_PENALTY_LABELS = ("redundancy", "interruption_cost", "uncertainty", "stale_risk")


@dataclass(frozen=True, slots=True)
class AttentionFactors:
    """Every RI-14 ranking input, each independently inspectable and bounded [0, 1]."""

    learning_pressure: float
    evidence_strength: float
    novelty: float
    expected_learning_value: float
    timing_fit: float
    redundancy: float
    interruption_cost: float
    uncertainty: float
    stale_risk: float

    def __post_init__(self) -> None:
        for label in _FACTOR_LABELS + _PENALTY_LABELS:
            value = getattr(self, label)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"attention factor {label} must be between zero and one")

    @property
    def score(self) -> float:
        """``learning_pressure x evidence_strength x novelty x expected_learning_value
        x timing_fit - (redundancy + interruption_cost + uncertainty + stale_risk)``."""
        gain = (
            self.learning_pressure
            * self.evidence_strength
            * self.novelty
            * self.expected_learning_value
            * self.timing_fit
        )
        cost = self.redundancy + self.interruption_cost + self.uncertainty + self.stale_risk
        return round(gain - cost, 6)


@dataclass(frozen=True, slots=True)
class RankedAttentionCandidate:
    """One scored candidate (a ``ProjectInsight`` or ``AnalogyRecord`` identity) plus why."""

    identity: str
    factors: AttentionFactors
    basis: str

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise ValueError("ranked attention candidates require an identity")
        if not self.basis.strip():
            raise ValueError("ranked attention candidates require a basis")


def rank_attention_candidates(candidates: tuple[RankedAttentionCandidate, ...]) -> tuple[RankedAttentionCandidate, ...]:
    """Deterministic, explainable descending rank by score; ties break on identity."""
    if not candidates:
        raise ValueError("attention ranking requires at least one candidate")
    return tuple(sorted(candidates, key=lambda c: (-c.factors.score, c.identity)))


@dataclass(frozen=True, slots=True)
class AttentionBudgetLimits:
    """Interruption ceilings over a rolling window; independent of compute cost."""

    window: timedelta
    max_interruptions: int
    max_digests: int

    def __post_init__(self) -> None:
        if self.window <= timedelta(0):
            raise ValueError("attention budget window must be positive")
        if self.max_interruptions < 0 or self.max_digests < 0:
            raise ValueError("attention budget ceilings must not be negative")


@dataclass(frozen=True, slots=True)
class AttentionSpend:
    interruptions: int
    digests: int

    def __post_init__(self) -> None:
        if self.interruptions < 0 or self.digests < 0:
            raise ValueError("attention spend must not be negative")


def attention_spend(exposures: tuple[Exposure, ...], *, now: datetime, window: timedelta) -> AttentionSpend:
    """Attention already spent in the trailing window, from durable Exposure history.

    Counts only exposures that actually reached the user (``OFFERED`` or
    later) on an interrupting channel; ``QUIET_QUEUE``/``SUPPRESSED``
    events cost nothing because they never reached the user -- this is
    what keeps attention budget a distinct resource from "candidates
    considered."
    """
    if now.tzinfo is None:
        raise ValueError("attention spend evaluation time must be timezone-aware")
    if window <= timedelta(0):
        raise ValueError("attention spend window must be positive")
    window_start = now - window
    counted = tuple(
        e for e in exposures if window_start <= e.occurred_at <= now and e.outcome in _REACHED_USER
    )
    interruptions = sum(1 for e in counted if e.channel is ExposureChannel.PROACTIVE_PUSH)
    digests = sum(1 for e in counted if e.channel is ExposureChannel.DIGEST)
    return AttentionSpend(interruptions=interruptions, digests=digests)


def attention_budget_allows(spend: AttentionSpend, limits: AttentionBudgetLimits) -> bool:
    """Whether the ledger has room left; a hard, finite ceiling independent of compute cost."""
    return spend.interruptions < limits.max_interruptions and spend.digests < limits.max_digests


__all__ = [
    "AttentionBudgetLimits",
    "AttentionFactors",
    "AttentionSpend",
    "RankedAttentionCandidate",
    "attention_budget_allows",
    "attention_spend",
    "rank_attention_candidates",
]
