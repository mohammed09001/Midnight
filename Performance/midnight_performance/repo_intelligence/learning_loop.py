"""Bounded controller for Repo Intelligent's continuous learning loop.

The controller schedules already-defined stages; it does not own Performance
evidence, launch providers, or crawl.  Trigger receipts, jobs, checkpoints and
audit reasons are deterministic so replay is safe and interruptions resume at
an explicit boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from ..contracts import EntityKind, Identity
from .authorization import RepoIntelligenceAuthorization, ensure_same_project
from .contracts import BudgetCeiling, JobStatus, JobTrigger, ProjectIntelligenceJob, project_intelligence_job_identity


class TriggerKind(str, Enum):
    REPOSITORY_CHANGE = "repository_change"
    PERFORMANCE_EPISODE = "performance_episode"
    HOTSPOT_THRESHOLD = "hotspot_threshold"
    VERIFICATION_CLUSTER = "verification_cluster"
    NEW_DEPENDENCY = "new_dependency"
    MEMORY_UPDATE = "memory_update"
    FRESHNESS_EXPIRY = "freshness_expiry"
    USER_REQUEST = "user_request"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True, slots=True)
class LearningTrigger:
    project: Identity
    kind: TriggerKind
    component: str
    occurred_at: datetime
    reason: str
    source_ref: str

    def __post_init__(self) -> None:
        if self.project.kind is not EntityKind.PROJECT:
            raise ValueError("learning triggers require a project identity")
        if self.occurred_at.tzinfo is None:
            raise ValueError("trigger time must be timezone-aware")
        if not self.component.strip() or not self.reason.strip() or not self.source_ref.strip():
            raise ValueError("learning triggers require component, reason, and source reference")


@dataclass(frozen=True, slots=True)
class LoopControls:
    debounce: timedelta = timedelta(seconds=10)
    component_cooldown: timedelta = timedelta(minutes=30)
    maximum_traversal_depth: int = 4
    maximum_follow_up_questions: int = 2
    maximum_remote_sources: int = 5
    maximum_model_calls: int = 2
    maximum_tokens: int = 8_000
    maximum_wall_time_seconds: float = 120.0
    minimum_marginal_gain: float = 0.1
    enabled: bool = True
    quiet_mode: bool = False

    def __post_init__(self) -> None:
        numeric = (self.maximum_traversal_depth, self.maximum_follow_up_questions, self.maximum_remote_sources, self.maximum_model_calls, self.maximum_tokens)
        if self.debounce < timedelta(0) or self.component_cooldown < timedelta(0) or any(value < 0 for value in numeric):
            raise ValueError("loop controls must not be negative")
        if self.maximum_wall_time_seconds <= 0 or not 0 <= self.minimum_marginal_gain <= 1:
            raise ValueError("wall time and marginal-gain bounds are invalid")


@dataclass(frozen=True, slots=True)
class MarginalKnowledgeGain:
    evidence_diversity: float = 0.0
    contradiction_resolution: float = 0.0
    freshness: float = 0.0
    graph_connection: float = 0.0
    redundancy: float = 0.0

    def __post_init__(self) -> None:
        if any(not 0 <= value <= 1 for value in (self.evidence_diversity, self.contradiction_resolution, self.freshness, self.graph_connection, self.redundancy)):
            raise ValueError("marginal gain features must be between zero and one")

    @property
    def score(self) -> float:
        return round(max(0.0, (self.evidence_diversity + self.contradiction_resolution + self.freshness + self.graph_connection) / 4 - self.redundancy), 6)


@dataclass(frozen=True, slots=True)
class LoopCheckpoint:
    job_identity: object
    next_step: int
    completed_stages: tuple[str, ...]
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class LoopRun:
    job: ProjectIntelligenceJob | None
    checkpoint: LoopCheckpoint | None
    coalesced_trigger_count: int
    remote_steps: int
    stopped_reason: str
    audit_trail: tuple[str, ...]
    replayed: bool = False
    quiet: bool = False


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown: timedelta = timedelta(minutes=5)
    transient_failures: int = 0
    opened_at: datetime | None = None

    def allow(self, now: datetime) -> bool:
        if self.opened_at is None:
            return True
        if now - self.opened_at >= self.cooldown:
            self.transient_failures = 0
            self.opened_at = None
            return True
        return False

    def record_failure(self, now: datetime, *, transient: bool) -> None:
        if not transient:
            return
        self.transient_failures += 1
        if self.transient_failures >= self.failure_threshold:
            self.opened_at = now

    def record_success(self) -> None:
        self.transient_failures = 0
        self.opened_at = None


def _trigger_key(trigger: LearningTrigger, debounce: timedelta) -> str:
    bucket_seconds = max(1, int(debounce.total_seconds()))
    bucket = int(trigger.occurred_at.timestamp()) // bucket_seconds
    return f"{trigger.kind.value}|{trigger.component.strip().lower()}|{bucket}"


class ContinuousLearningLoop:
    """In-process scheduler state; durable owners may persist returned checkpoints."""

    _STAGES = ("capture_trigger", "coalesce", "changed_scope", "refresh_signals", "score_gap", "check_cache", "external_decision", "research", "synthesize", "graph_link", "rank", "queue_exposure")

    def __init__(self, project: Identity, *, controls: LoopControls = LoopControls(), circuit_breaker: CircuitBreaker | None = None) -> None:
        if project.kind is not EntityKind.PROJECT:
            raise ValueError("continuous loops require a project identity")
        self.project = project
        self.controls = controls
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._completed: dict[str, LoopRun] = {}
        self._last_component_run: dict[str, datetime] = {}

    def run(self, triggers: tuple[LearningTrigger, ...], authorization: RepoIntelligenceAuthorization, *, now: datetime, marginal_gains: tuple[MarginalKnowledgeGain, ...] = (), existing_question_keys: frozenset[str] = frozenset(), question_key: str | None = None, provider_available: bool = True, cancel: bool = False, resume: LoopCheckpoint | None = None) -> LoopRun:
        if now.tzinfo is None:
            raise ValueError("loop run time must be timezone-aware")
        ensure_same_project(authorization, project=self.project)
        for trigger in triggers:
            ensure_same_project(authorization, project=trigger.project)
        if not triggers:
            return LoopRun(None, None, 0, 0, "no triggers", ("no work scheduled",), quiet=self.controls.quiet_mode)
        user_pull = any(trigger.kind is TriggerKind.USER_REQUEST for trigger in triggers)
        if not self.controls.enabled and not user_pull:
            return LoopRun(None, None, 0, 0, "project learning loop disabled", ("disabled by project control",), quiet=True)

        unique = { _trigger_key(trigger, self.controls.debounce): trigger for trigger in sorted(triggers, key=lambda item: (item.occurred_at, item.source_ref)) }
        selected = tuple(unique[key] for key in sorted(unique))
        components = tuple(sorted({trigger.component.strip().lower() for trigger in selected}))
        material = "|".join(_trigger_key(trigger, self.controls.debounce) for trigger in selected)
        idempotency_key = hashlib.sha256(f"{self.project.canonical}|{material}".encode()).hexdigest()
        if idempotency_key in self._completed and resume is None:
            previous = self._completed[idempotency_key]
            return LoopRun(previous.job, previous.checkpoint, previous.coalesced_trigger_count, previous.remote_steps, "idempotent replay", previous.audit_trail, replayed=True, quiet=previous.quiet)
        cooled = [component for component in components if component in self._last_component_run and now - self._last_component_run[component] < self.controls.component_cooldown]
        if cooled and not user_pull:
            return LoopRun(None, None, len(selected), 0, "component cooldown active", (f"cooled components: {', '.join(cooled)}",), quiet=True)

        identity = project_intelligence_job_identity(self.project, "continuous_learning", idempotency_key)
        if resume is not None and resume.job_identity != identity:
            raise ValueError("checkpoint belongs to a different job")
        started_step = resume.next_step if resume else 0
        audit = [f"why did this run: {trigger.kind.value}: {trigger.reason}" for trigger in selected]
        if question_key and question_key in existing_question_keys:
            audit.append(f"duplicate research question suppressed: {question_key}")
            marginal_gains = ()
            provider_available = False
        remote_steps = 0
        stop_reason = "bounded loop completed"
        if cancel:
            stop_reason = "cancelled at checkpoint"
        elif not provider_available:
            stop_reason = "provider offline; internal-only checkpoint retained"
        elif not self.circuit_breaker.allow(now):
            stop_reason = "circuit breaker open; external branch skipped"
        else:
            maximum_steps = min(self.controls.maximum_remote_sources, self.controls.maximum_follow_up_questions + 1)
            for gain in marginal_gains[:maximum_steps]:
                if gain.score <= self.controls.minimum_marginal_gain:
                    stop_reason = "marginal knowledge gain reached redundancy saturation"
                    break
                remote_steps += 1
            else:
                if len(marginal_gains) > maximum_steps:
                    stop_reason = "remote/follow-up source ceiling reached"

        completed_stages = self._STAGES[:started_step]
        if not cancel:
            completed_stages = self._STAGES
        checkpoint = LoopCheckpoint(identity, len(completed_stages), completed_stages, cancel)
        status = JobStatus.CANCELLED if cancel else JobStatus.COMPLETED
        trigger_kind = JobTrigger.USER_PULL if user_pull else JobTrigger.MAINTENANCE if all(t.kind is TriggerKind.MAINTENANCE for t in selected) else JobTrigger.PROACTIVE
        job = ProjectIntelligenceJob(identity, self.project, "continuous_learning", idempotency_key, trigger_kind, status, "stop on marginal gain saturation or any configured ceiling", BudgetCeiling(max_model_calls=self.controls.maximum_model_calls, max_network_requests=self.controls.maximum_remote_sources, max_seconds=self.controls.maximum_wall_time_seconds), "continuous-learning-loop", "1", now, now, now if status is JobStatus.COMPLETED else None)
        result = LoopRun(job, checkpoint, len(selected), remote_steps, stop_reason, tuple(audit), quiet=self.controls.quiet_mode and not user_pull)
        if not cancel:
            self._completed[idempotency_key] = result
            for component in components:
                self._last_component_run[component] = now
        return result


__all__ = ["CircuitBreaker", "ContinuousLearningLoop", "LearningTrigger", "LoopCheckpoint", "LoopControls", "LoopRun", "MarginalKnowledgeGain", "TriggerKind"]
