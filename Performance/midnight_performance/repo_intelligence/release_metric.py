"""Execution RI-14's unique release metric.

``useful_project_learning / (user_attention_cost + normalized_compute_cost)``.

Deliberately never optimizes click rate alone: a cheap, frequently-offered
insight that nobody ever positively associates with later improvement
scores worse than a rare insight with a real positive association, even
though the first was "seen" far more often.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import AssociationKind, CostRecord, Exposure, ExposureChannel, ExposureOutcome, LearningOutcome

_POSITIVE = frozenset({AssociationKind.POSITIVE_ASSOCIATION})
_NEGATIVE = frozenset({AssociationKind.NEGATIVE_ASSOCIATION})
_INTERRUPTING_CHANNELS = frozenset({ExposureChannel.PROACTIVE_PUSH, ExposureChannel.DIGEST})
_REACHED_USER = frozenset(
    {ExposureOutcome.OFFERED, ExposureOutcome.OPENED, ExposureOutcome.SAVED, ExposureOutcome.USED, ExposureOutcome.DISMISSED}
)


def useful_project_learning(outcomes: tuple[LearningOutcome, ...]) -> float:
    """Net positive learning association; a negative association subtracts, never floors at zero.

    Association is not causality (``LearningOutcome`` itself never claims
    more than statistical strength) -- this is a prioritization aid over
    the same associative evidence, not a causal learning-value estimate.
    """
    positive = sum(1 for o in outcomes if o.association in _POSITIVE)
    negative = sum(1 for o in outcomes if o.association in _NEGATIVE)
    return float(positive - negative)


def user_attention_cost(exposures: tuple[Exposure, ...]) -> float:
    """Interruptions that actually reached the user; a dismissal still cost attention."""
    return float(sum(1 for e in exposures if e.channel in _INTERRUPTING_CHANNELS and e.outcome in _REACHED_USER))


def normalized_compute_cost(costs: tuple[CostRecord, ...], *, micros_per_unit: int = 1_000_000) -> float:
    """Compute spend normalized to a stable unit (default: one unit per 1e6 cost micros)."""
    if micros_per_unit <= 0:
        raise ValueError("micros_per_unit must be positive")
    return sum((c.cost_micros or 0) for c in costs) / micros_per_unit


@dataclass(frozen=True, slots=True)
class ReleaseMetric:
    useful_project_learning: float
    user_attention_cost: float
    normalized_compute_cost: float

    def __post_init__(self) -> None:
        if self.user_attention_cost < 0 or self.normalized_compute_cost < 0:
            raise ValueError("release metric costs must not be negative")

    @property
    def value(self) -> float | None:
        """The ratio, or ``None`` when no attention or compute has been spent yet.

        ``None`` (never a fabricated infinity or zero) is the honest answer
        when the denominator is zero: nothing has been risked yet, so no
        ratio is defined.
        """
        denominator = self.user_attention_cost + self.normalized_compute_cost
        if denominator <= 0:
            return None
        return round(self.useful_project_learning / denominator, 6)


def compute_release_metric(
    outcomes: tuple[LearningOutcome, ...],
    exposures: tuple[Exposure, ...],
    costs: tuple[CostRecord, ...],
) -> ReleaseMetric:
    return ReleaseMetric(
        useful_project_learning=useful_project_learning(outcomes),
        user_attention_cost=user_attention_cost(exposures),
        normalized_compute_cost=normalized_compute_cost(costs),
    )


__all__ = [
    "ReleaseMetric",
    "compute_release_metric",
    "normalized_compute_cost",
    "useful_project_learning",
    "user_attention_cost",
]
