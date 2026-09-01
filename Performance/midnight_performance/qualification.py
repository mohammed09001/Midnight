"""Frozen evaluation corpora and passive coding-harness qualification.

The corpus is a deterministic, versioned test fixture for Performance itself.
It does not execute coding agents or commands.  Provider events and prose are
untrusted observations; repository before/after evidence remains authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Mapping

from .alignment import AlignmentStatus, align
from .claude_adapter import CLAUDE_ADAPTER, normalize_claude_hook
from .codex_adapter import CODEX_ADAPTER, normalize_codex_event
from .contracts import ClaimKind
from .drift import AdapterHealth, CapabilityManifest, HealthReport, probe
from .evaluation import EvaluationResult, evaluate_deterministically
from .harness import ObservationAdapter
from .opencode_adapter import OPENCODE_ADAPTER, OpenCodeObserver
from .prompt_analysis import PromptFeatures, analyze_prompt
from .prompt_run import PromptRun
from .repository_capture import ChangeEvidence, RepositorySnapshot, compare
from .report_consistency import ReportConsistency, assess_report
from .scope_discipline import ScopeDiscipline, TaskType, assess_scope
from .verification import VerificationEvidence
from .windows import ExecutionWindow, window_from_lifecycle

_VERSION = "1"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenEvent:
    """A supplied provider event with a stable identity for replay/deduplication."""
    event_id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("frozen event id is required")


@dataclass(frozen=True, slots=True)
class FrozenPromptRun:
    """Complete, local test input for one known development experience."""
    prompt_run: PromptRun
    prompt: str
    provider: str
    lifecycle_events: tuple[FrozenEvent, ...] = ()
    tool_events: tuple[FrozenEvent, ...] = ()
    commands: tuple[VerificationEvidence, ...] = ()
    baseline: RepositorySnapshot = field(default_factory=lambda: RepositorySnapshot({}))
    final: RepositorySnapshot = field(default_factory=lambda: RepositorySnapshot({}))
    requested_scope: tuple[str, ...] = ()
    forbidden_scope: tuple[str, ...] = ()
    task_type: TaskType = TaskType.UNKNOWN
    feedback_ids: tuple[str, ...] = ()
    sibling_references: tuple[str, ...] = ()
    expected_scores: Mapping[str, float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prompt.strip() or not self.provider.strip():
            raise ValueError("frozen prompt and provider are required")
        if self.prompt_run.feedback_ids and tuple(self.prompt_run.feedback_ids) != tuple(self.feedback_ids):
            raise ValueError("feedback ids must agree with the prompt run")
        if any(value is not None and not 0 <= value <= 1 for value in self.expected_scores.values()):
            raise ValueError("expected scores must be zero-one or unknown")

    @property
    def changes(self) -> ChangeEvidence:
        return compare(self.baseline, self.final)

    @property
    def fingerprint(self) -> str:
        return _fingerprint({
            "version": _VERSION, "prompt_run": self.prompt_run, "prompt": self.prompt,
            "provider": self.provider, "lifecycle": self.lifecycle_events, "tools": self.tool_events,
            "commands": self.commands, "baseline": self.baseline.files, "final": self.final.files,
            "requested_scope": self.requested_scope, "forbidden_scope": self.forbidden_scope,
            "task_type": self.task_type.value, "feedback": self.feedback_ids,
            "siblings": self.sibling_references, "expected": self.expected_scores,
        })


@dataclass(frozen=True, slots=True)
class EvaluationCorpus:
    version: str
    runs: tuple[FrozenPromptRun, ...]
    corpus_id: str = "performance-qualification"

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.corpus_id.strip():
            raise ValueError("corpus identity and version are required")
        ids = [run.prompt_run.prompt_run_id for run in self.runs]
        if len(ids) != len(set(ids)):
            raise ValueError("corpus prompt run ids must be unique")

    @property
    def fingerprint(self) -> str:
        return _fingerprint({"corpus_id": self.corpus_id, "version": self.version, "runs": [item.fingerprint for item in self.runs]})

    def replay(self) -> tuple[FrozenPromptRun, ...]:
        """Return the same frozen ordering; callers can compare corpus fingerprints."""
        return self.runs


@dataclass(frozen=True, slots=True)
class CorpusResult:
    prompt_run_id: str
    features: PromptFeatures
    changes: ChangeEvidence
    evaluations: tuple[EvaluationResult, ...]
    scope: ScopeDiscipline | None
    expected_mismatches: tuple[str, ...]
    claim_kind: ClaimKind
    uncertainty: str


def evaluate_frozen_run(run: FrozenPromptRun) -> CorpusResult:
    """Derive transparent prompt/change scores without upgrading unknown evidence."""
    features, _ = analyze_prompt(run.prompt)
    changes = run.changes
    alignment = align(features, changes)
    actionable = [item for item in alignment.judgments if item.status is not AlignmentStatus.INSUFFICIENT_EVIDENCE]
    coverage = None if not actionable else round(sum(item.status in {AlignmentStatus.SATISFIED, AlignmentStatus.PARTIALLY_SATISFIED} for item in actionable) / len(actionable), 3)
    constraints = [item for item in alignment.judgments if "constraint" in item.uncertainty]
    violation_rate = None if not constraints else round(sum(item.status is AlignmentStatus.CONTRADICTED for item in constraints) / len(constraints), 3)
    values = {"requirement_coverage": coverage, "constraint_violation_rate": violation_rate}
    evidence = {
        "requirement_coverage": tuple(path for item in alignment.judgments for path in item.evidence),
        "constraint_violation_rate": tuple(path for item in alignment.judgments for path in item.evidence if item.status is AlignmentStatus.CONTRADICTED),
    }
    evaluations = evaluate_deterministically(run.prompt_run.prompt_run_id, values, evidence)
    scope = assess_scope(run.requested_scope, changes, run.task_type, forbidden=run.forbidden_scope) if run.requested_scope else None
    actual = {item.evaluator: item.score for item in evaluations}
    mismatches = tuple(sorted(name for name, expected in run.expected_scores.items() if actual.get(name) != expected))
    return CorpusResult(run.prompt_run.prompt_run_id, features, changes, evaluations, scope, mismatches, ClaimKind.DERIVED, "path-based alignment and scope are derived; they do not prove behavioral correctness")


class QualificationState(str, Enum):
    QUALIFIED = "qualified"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class HarnessQualification:
    prompt_run_id: str
    provider: str
    health: HealthReport
    state: QualificationState
    accepted_event_ids: tuple[str, ...]
    duplicate_event_ids: tuple[str, ...]
    windows: tuple[ExecutionWindow, ...]
    repository_changes: ChangeEvidence
    native_file_claims: tuple[str, ...]
    unreconciled_native_claims: tuple[str, ...]
    report: ReportConsistency | None
    gaps: tuple[str, ...]
    claim_kind: ClaimKind
    uncertainty: str


_ADAPTERS: Mapping[str, ObservationAdapter] = {"codex": CODEX_ADAPTER, "claude-code": CLAUDE_ADAPTER, "opencode": OPENCODE_ADAPTER}


def _normalize(provider: str, event: FrozenEvent, observer: OpenCodeObserver) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if provider == "codex":
        observed = normalize_codex_event(event.payload)
        payload = observed.payload
        return observed.gaps, _paths(payload)
    if provider == "claude-code":
        observed = normalize_claude_hook(event.payload)
        return observed.gaps, _paths(observed.payload)
    if provider == "opencode":
        observed = observer.normalize(event.payload)
        if observed is None:
            return ("unavailable:duplicate-provider-payload",), ()
        return observed.gaps, _paths(observed.payload)
    raise ValueError(f"unsupported provider: {provider}")


def _paths(payload: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("path", "file_path", "file", "files"):
        value = payload.get(key)
        if isinstance(value, str): values.append(value)
        elif isinstance(value, (list, tuple)):
            values.extend(item for item in value if isinstance(item, str))
    return tuple(sorted(set(values)))


def _window_for(provider: str, payload: Mapping[str, Any], prompt_run_id: str) -> ExecutionWindow | None:
    """Map only declared lifecycle states; unrelated turn events do not invent windows."""
    state = payload.get("state")
    if not isinstance(state, str):
        event = payload.get("type") if provider != "claude-code" else payload.get("hook_event_name")
        state = {
            "turn.started": "started", "turn.completed": "completed", "turn.failed": "failed", "turn.interrupted": "interrupted",
            "SessionStart": "started", "SessionEnd": "completed", "Stop": "completed", "StopFailure": "failed",
        }.get(event) if isinstance(event, str) else None
    if state is None:
        return None
    return window_from_lifecycle({"state": state, "agent_run_id": payload.get("agent_run_id"), "session_id": payload.get("session_id"), "turn_id": payload.get("turn_id"), "prompt_run_id": prompt_run_id})


def qualify_harness(run: FrozenPromptRun, manifest: CapabilityManifest, *, provider_version: str | None, hooks_available: bool = True, permission_granted: bool = True, agent_prose: str | None = None) -> HarnessQualification:
    """Qualify supplied passive capture against real repository before/after evidence."""
    adapter = _ADAPTERS.get(run.provider)
    if adapter is None:
        raise ValueError(f"unsupported provider: {run.provider}")
    health = (HealthReport(AdapterHealth.UNSUPPORTED_VERSION, (f"unavailable:manifest-adapter:{manifest.adapter}",))
              if manifest.adapter != adapter.name else probe(adapter, manifest, provider_version=provider_version, hooks_available=hooks_available, permission_granted=permission_granted))
    observer = OpenCodeObserver()
    accepted: list[str] = []; duplicates: list[str] = []; gaps: list[str] = list(health.gaps); native: list[str] = []; windows: list[ExecutionWindow] = []
    seen: set[str] = set()
    for event in run.lifecycle_events + run.tool_events:
        if event.event_id in seen:
            duplicates.append(event.event_id); continue
        seen.add(event.event_id)
        event_gaps, paths = _normalize(run.provider, event, observer)
        accepted.append(event.event_id); gaps.extend(event_gaps); native.extend(paths)
        window = _window_for(run.provider, event.payload, run.prompt_run.prompt_run_id)
        if window is not None:
            windows.append(window)
    changes = run.changes
    actual = set(changes.created + changes.modified + changes.deleted)
    native_claims = tuple(sorted(set(native)))
    unreconciled = tuple(sorted(set(native) - actual))
    if unreconciled: gaps.extend(f"unreconciled:native-file:{path}" for path in unreconciled)
    report = assess_report(agent_prose, changes, run.commands) if agent_prose is not None else None
    state = QualificationState.QUALIFIED if not gaps else (QualificationState.UNSUPPORTED if health.health.value in {"unsupported_version", "unavailable"} else QualificationState.DEGRADED)
    return HarnessQualification(run.prompt_run.prompt_run_id, run.provider, health, state, tuple(accepted), tuple(duplicates), tuple(windows), changes, native_claims, unreconciled, report, tuple(sorted(set(gaps))), ClaimKind.DERIVED, "provider events are observed declarations; repository changes remain authoritative and prose is assessed only for consistency")
