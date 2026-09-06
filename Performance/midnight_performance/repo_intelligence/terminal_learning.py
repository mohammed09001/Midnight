"""Local, calm terminal presentation for already-produced ProjectInsights.

Rendering is pure local formatting.  It never calls providers, performs
research, or reads raw evidence; expensive work must complete before a card
reaches this layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .authorization import RepoIntelligenceAuthorization, ensure_same_project
from .contracts import Exposure, ExposureChannel, ExposureOutcome, ProjectInsight, new_event_identity
from .identities import RepoIntelligenceKind
from .attention import AttentionBudgetLimits, attention_budget_allows, attention_spend, AttentionFactors


def _safe_text(value: str, limit: int = 280) -> str:
    """Keep terminal control sequences and unbounded source-derived text inert."""
    clean = "".join(char for char in value if char >= " " and char != "\x7f")
    return " ".join(clean.split())[:limit]


@dataclass(frozen=True, slots=True)
class TerminalCandidate:
    insight: ProjectInsight
    why_now: str
    project_connection: str
    next_learning_action: str
    relevance: float
    evidence_quality: float
    novelty: float
    expected_learning_value: float
    interruption_cost: float
    external_connection: str | None = None
    learning_pressure: float = 1.0
    timing_fit: float = 1.0
    redundancy: float = 0.0
    uncertainty: float = 0.0
    stale_risk: float = 0.0

    def __post_init__(self) -> None:
        for label, value in (
            ("why_now", self.why_now), ("project_connection", self.project_connection),
            ("next_learning_action", self.next_learning_action),
        ):
            if not value.strip():
                raise ValueError(f"terminal candidates require {label}")
        for value in (self.relevance, self.evidence_quality, self.novelty, self.expected_learning_value, self.interruption_cost, self.learning_pressure, self.timing_fit, self.redundancy, self.uncertainty, self.stale_risk):
            if not 0.0 <= value <= 1.0:
                raise ValueError("terminal candidate scores must be between zero and one")

    @property
    def priority(self) -> float:
        return AttentionFactors(
            learning_pressure=self.learning_pressure,
            evidence_strength=self.evidence_quality,
            novelty=self.novelty,
            expected_learning_value=self.expected_learning_value,
            timing_fit=self.timing_fit,
            redundancy=self.redundancy,
            interruption_cost=self.interruption_cost,
            uncertainty=self.uncertainty,
            stale_risk=self.stale_risk,
        ).score


@dataclass(frozen=True, slots=True)
class TerminalContext:
    protected_focus: bool = False
    proactive_enabled: bool = True
    budget_allowed: bool = True
    relevance_threshold: float = 0.6
    evidence_threshold: float = 0.6
    novelty_threshold: float = 0.4
    cooldown: timedelta = timedelta(hours=8)
    dismissal_limit: int = 3
    attention_limits: AttentionBudgetLimits | None = AttentionBudgetLimits(timedelta(hours=24), 3, 10)

    def __post_init__(self) -> None:
        if self.cooldown < timedelta(0) or self.dismissal_limit < 1:
            raise ValueError("terminal attention settings must be non-negative and bounded")


@dataclass(frozen=True, slots=True)
class TerminalDecision:
    card: str | None
    exposure: Exposure
    reason: str


def render_card(candidate: TerminalCandidate) -> str:
    """Render the fixed, bounded card format without source dumps."""
    insight = candidate.insight
    lines = [
        f"WHAT: {_safe_text(insight.statement)}",
        f"WHY NOW: {_safe_text(candidate.why_now)}",
        f"PROJECT CONNECTION: {_safe_text(candidate.project_connection)}",
    ]
    if candidate.external_connection:
        lines.append(f"EXTERNAL CONNECTION: {_safe_text(candidate.external_connection)}")
    lines.extend((
        f"CONFIDENCE/GAPS: {insight.confidence if insight.confidence is not None else 'unscored'}; {_safe_text(insight.uncertainty)}",
        f"NEXT LEARNING ACTION: {_safe_text(candidate.next_learning_action)}",
    ))
    return "\n".join(lines)


def _suppressed(candidate: TerminalCandidate, now: datetime, context: TerminalContext, history: tuple[Exposure, ...]) -> str | None:
    insight = candidate.insight
    if insight.is_superseded():
        return "insight is stale or superseded"
    if not insight.proactively_exposable():
        return "insight lacks a lineage receipt for proactive exposure"
    if not context.proactive_enabled:
        return "proactive enrichment is paused"
    if context.protected_focus:
        return "terminal is in protected focus"
    if not context.budget_allowed:
        return "attention or compute budget is unavailable"
    if context.attention_limits is not None:
        spend = attention_spend(history, now=now, window=context.attention_limits.window)
        if not attention_budget_allows(spend, context.attention_limits):
            return "rolling attention budget is exhausted"
    if candidate.relevance < context.relevance_threshold or candidate.evidence_quality < context.evidence_threshold:
        return "relevance or evidence quality is below proactive threshold"
    if candidate.novelty < context.novelty_threshold or candidate.expected_learning_value <= candidate.interruption_cost:
        return "novelty or expected learning value does not earn interruption"
    related = tuple(item for item in history if item.insight == insight.identity)
    if sum(item.outcome is ExposureOutcome.DISMISSED for item in related) >= context.dismissal_limit:
        return "repeated dismissal suppresses proactive exposure"
    if any(now - item.occurred_at < context.cooldown for item in related):
        return "insight is within its attention cooldown"
    return None


def decide_terminal_card(
    candidates: tuple[TerminalCandidate, ...],
    authorization: RepoIntelligenceAuthorization,
    *,
    now: datetime,
    history: tuple[Exposure, ...] = (),
    context: TerminalContext = TerminalContext(),
    user_pull: bool = False,
) -> TerminalDecision:
    """Select one card deterministically, otherwise create a suppressed event."""
    if now.tzinfo is None:
        raise ValueError("terminal decision time must be timezone-aware")
    valid = []
    for candidate in candidates:
        ensure_same_project(authorization, project=candidate.insight.project)
        valid.append(candidate)
    if not valid:
        raise ValueError("terminal selection requires at least one candidate")
    candidate = sorted(valid, key=lambda item: (-item.priority, item.insight.identity.canonical))[0]
    if user_pull and not candidate.insight.is_superseded():
        return TerminalDecision(render_card(candidate), Exposure(new_event_identity(RepoIntelligenceKind.EXPOSURE), candidate.insight.project, candidate.insight.identity, ExposureChannel.USER_PULL, ExposureOutcome.OFFERED, "terminal", now, novelty_score=candidate.novelty), "user requested learning card")
    reason = _suppressed(candidate, now, context, history)
    if reason:
        return TerminalDecision(None, Exposure(new_event_identity(RepoIntelligenceKind.EXPOSURE), candidate.insight.project, candidate.insight.identity, ExposureChannel.QUIET_QUEUE, ExposureOutcome.SUPPRESSED, "terminal", now, focus_protected=context.protected_focus, attention_cooldown_active="cooldown" in reason, novelty_score=candidate.novelty, suppression_reason=reason), reason)
    justification = "hiding this insight would leave its current project connection unexplained"
    return TerminalDecision(render_card(candidate), Exposure(new_event_identity(RepoIntelligenceKind.EXPOSURE), candidate.insight.project, candidate.insight.identity, ExposureChannel.PROACTIVE_PUSH, ExposureOutcome.OFFERED, "terminal", now, relevance_justification=justification, novelty_score=candidate.novelty), "earned proactive interruption")


__all__ = ["TerminalCandidate", "TerminalContext", "TerminalDecision", "decide_terminal_card", "render_card"]
