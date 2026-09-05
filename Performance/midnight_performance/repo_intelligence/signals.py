"""Internal signal detection and explainable learning-pressure scoring.

Deterministic and local by default.  The score is a prioritization aid,
never a quality judgment: churn alone never becomes "problem", missing
evidence lowers confidence instead of being fabricated, and every factor
carries its own evidence ids and basis text.  Old activity decays with an
explicit half-life so historical hotspots cannot dominate forever.  Every
signal carries a Performance Lineage Receipt; a signal without one is
never eligible for proactive exposure.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from itertools import combinations
from typing import Callable, Mapping

from ..contracts import ClaimKind, EntityKind, Identity
from ..observation_model import ObservationEnvelope
from .contracts import (
    CacheStatus,
    CostRecord,
    CostResourceKind,
    InternalAnswerStatus,
    InternalSignal,
    LineageReceipt,
    PressureDimension,
    ProjectEntityRef,
    ProjectIntelligenceJob,
    internal_signal_identity,
    lineage_receipt_identity,
    new_event_identity,
)
from .evidence_join import EvidenceEvent, join_evidence
from .identities import RepoIntelligenceKind

SECONDS_PER_DAY = 86400.0

DERIVATION_METHOD = "signal-detect"
DERIVATION_VERSION = "1"


class PressureFactorName(str, Enum):
    """Factors of ``need = activity × friction × recurrence × impact × gap × freshness``."""

    ACTIVITY = "activity"
    FRICTION = "friction"
    RECURRENCE = "recurrence"
    IMPACT = "impact"
    KNOWLEDGE_DEFICIT = "knowledge_deficit"
    FRESHNESS = "freshness"


_FACTOR_DIMENSIONS: dict[PressureFactorName, PressureDimension] = {
    PressureFactorName.ACTIVITY: PressureDimension.ATTENTION,
    PressureFactorName.FRICTION: PressureDimension.FRICTION,
    PressureFactorName.RECURRENCE: PressureDimension.RECURRENCE,
    PressureFactorName.IMPACT: PressureDimension.IMPACT,
    PressureFactorName.KNOWLEDGE_DEFICIT: PressureDimension.KNOWLEDGE_DEFICIT,
    PressureFactorName.FRESHNESS: PressureDimension.FRESHNESS,
}


@dataclass(frozen=True, slots=True)
class PressureWeights:
    """Replaceable factor weights; every factor stays inspectable."""

    activity: float = 1.0
    friction: float = 1.0
    recurrence: float = 1.0
    impact: float = 1.0
    knowledge_deficit: float = 1.0
    freshness: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "activity",
            "friction",
            "recurrence",
            "impact",
            "knowledge_deficit",
            "freshness",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} weight must not be negative")

    def for_factor(self, name: PressureFactorName) -> float:
        return getattr(self, name.value)


@dataclass(frozen=True, slots=True)
class PressureConfig:
    """Bounded, inspectable configuration for signal detection."""

    window_seconds: float = 14 * SECONDS_PER_DAY
    half_life_seconds: float = 3 * SECONDS_PER_DAY
    churn_scale: float = 10.0
    coupling_scale: float = 8.0
    rework_min_changes: int = 2
    min_evidence_diversity: int = 2
    recurring_task_days: int = 3
    weights: PressureWeights = field(default_factory=PressureWeights)

    def __post_init__(self) -> None:
        for name in ("window_seconds", "half_life_seconds", "churn_scale", "coupling_scale"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.rework_min_changes < 1:
            raise ValueError("rework_min_changes must be at least one")
        if self.min_evidence_diversity < 1:
            raise ValueError("min_evidence_diversity must be at least one")


@dataclass(frozen=True, slots=True)
class PressureFactor:
    """One inspectable factor: value, backing evidence, and basis text."""

    name: PressureFactorName
    value: float | None
    evidence_ids: tuple[str, ...]
    basis: str

    def __post_init__(self) -> None:
        if not self.basis.strip():
            raise ValueError("pressure factors require a basis")
        if self.value is not None and not 0.0 <= self.value <= 1.0:
            raise ValueError("factor values must lie between zero and one")


@dataclass(frozen=True, slots=True)
class LearningPressure:
    """Explainable learning pressure: product of available factors, never quality."""

    factors: tuple[PressureFactor, ...]
    score: float | None
    confidence: float | None
    claim_kind: ClaimKind
    uncertainty: str

    def __post_init__(self) -> None:
        if not self.uncertainty.strip():
            raise ValueError("learning pressure requires uncertainty text")
        if self.score is not None and self.score < 0:
            raise ValueError("pressure scores must not be negative")

    def factor(self, name: PressureFactorName) -> PressureFactor | None:
        for factor in self.factors:
            if factor.name is name:
                return factor
        return None

    def missing(self) -> tuple[PressureFactorName, ...]:
        return tuple(factor.name for factor in self.factors if factor.value is None)

    def covered_dimensions(self) -> tuple[PressureDimension, ...]:
        return tuple(
            _FACTOR_DIMENSIONS[factor.name] for factor in self.factors if factor.value is not None
        )


@dataclass(frozen=True, slots=True)
class SignalDetails:
    """Typed event counts shared by scoring and detection."""

    change_observations: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    passed: tuple[str, ...] = ()
    verifications: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()
    flips: int = 0
    rollbacks: int = 0
    rework_excess: int = 0
    activity_dates: int = 0
    first_seen_in_window: bool = False


def _decay(observed_at: datetime, now: datetime, half_life_seconds: float) -> float:
    age = max(0.0, (now - observed_at).total_seconds())
    return 0.5 ** (age / half_life_seconds)


def _round4(value: float) -> float:
    return round(value, 4)


def score_path_pressure(
    path: str,
    events: tuple[EvidenceEvent, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    config: PressureConfig,
    now: datetime,
    partner_paths: tuple[str, ...] = (),
    partner_evidence: tuple[str, ...] = (),
    memory_status: InternalAnswerStatus | None = None,
    entity_first_seen: datetime | None = None,
) -> tuple[LearningPressure, SignalDetails]:
    """Compute the six-factor learning pressure for one entity path.

    Returns the pressure plus typed detail counts so detection never
    re-parses events.  Missing evidence yields missing factors and lower
    confidence, never invented values.
    """
    if now.tzinfo is None or window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("pressure scoring times must be timezone-aware")
    changes = [e for e in events if e.event_kind == "change"]
    verifications = [e for e in events if e.event_kind == "verification"]
    intents = [e for e in events if e.event_kind == "intent"]
    failures = [e for e in verifications if e.passed is False]
    passed = [e for e in verifications if e.passed is True]
    ordered = sorted(
        (e for e in verifications if e.passed is not None),
        key=lambda e: (e.observed_at, e.observation_canonical),
    )
    flips = sum(1 for prev, nxt in zip(ordered, ordered[1:]) if prev.passed != nxt.passed)
    distinct_change_obs = sorted({e.observation_canonical for e in changes})
    rework_excess = max(0, len(distinct_change_obs) - (config.rework_min_changes - 1))
    deletion_obs = {e.observation_canonical for e in events if "deleted" in e.roles}
    modification_obs = {e.observation_canonical for e in changes if set(e.roles) - {"deleted"}}
    rollbacks = 1 if deletion_obs and (modification_obs - deletion_obs) else 0
    activity_dates = {e.observed_at.date() for e in events}

    weights = config.weights
    factors: list[PressureFactor] = []

    if changes:
        activity = min(
            1.0,
            sum(_decay(e.observed_at, now, config.half_life_seconds) for e in changes)
            / config.churn_scale,
        )
        factors.append(
            PressureFactor(
                name=PressureFactorName.ACTIVITY,
                value=_round4(activity),
                evidence_ids=tuple(distinct_change_obs),
                basis=f"decayed count of {len(distinct_change_obs)} change observations touching {path}",
            )
        )
    else:
        factors.append(
            PressureFactor(
                name=PressureFactorName.ACTIVITY,
                value=None,
                evidence_ids=(),
                basis="no change evidence in window; activity unknown",
            )
        )

    friction_evidence = tuple(
        dict.fromkeys(e.observation_canonical for e in tuple(failures) + tuple(passed) + tuple(changes))
    )[:16]
    if failures or flips or rollbacks:
        friction_basis = (
            f"{len(failures)} failed, {flips} flaky flips, rollbacks {rollbacks} "
            f"(rework excess {rework_excess}) on {path}"
        )
        friction_parts = len(failures) + 0.5 * flips + 0.5 * rollbacks + 0.25 * rework_excess
        friction_value = _round4(min(1.0, friction_parts / 3.0))
    elif passed:
        friction_basis = f"{len(passed)} verifications observed in window, none failing; repeated edits with passing verification are healthy iteration"
        friction_value = 0.0
    else:
        friction_basis = "no verification evidence in window; friction unknown, not assumed"
        friction_value = None
    factors.append(
        PressureFactor(
            name=PressureFactorName.FRICTION,
            value=friction_value,
            evidence_ids=friction_evidence,
            basis=friction_basis,
        )
    )

    total_days = max(1, (window_end.date() - window_start.date()).days + 1)
    factors.append(
        PressureFactor(
            name=PressureFactorName.RECURRENCE,
            value=_round4(min(1.0, len(activity_dates) / total_days)),
            evidence_ids=tuple(dict.fromkeys(e.observation_canonical for e in events))[:16],
            basis=f"activity on {len(activity_dates)} of {total_days} window days",
        )
    )

    if changes and partner_paths:
        factors.append(
            PressureFactor(
                name=PressureFactorName.IMPACT,
                value=_round4(min(1.0, len(partner_paths) / config.coupling_scale)),
                evidence_ids=partner_evidence,
                basis=f"co-changed with {len(partner_paths)} distinct entities",
            )
        )
    else:
        factors.append(
            PressureFactor(
                name=PressureFactorName.IMPACT,
                value=None,
                evidence_ids=(),
                basis=(
                    "no co-change evidence in window; structural impact unknown, not assumed zero"
                    if changes
                    else "no change evidence; structural impact unknown"
                ),
            )
        )

    _DEFICIT = {
        InternalAnswerStatus.SUFFICIENT: (0.0, "internal/Memory context already answers the need"),
        InternalAnswerStatus.PARTIAL: (0.5, "partial internal/Memory context exists"),
        InternalAnswerStatus.ABSENT: (1.0, "no internal/Memory knowledge found for this need"),
    }
    if memory_status is not None:
        deficit_value, deficit_basis = _DEFICIT[memory_status]
        factors.append(
            PressureFactor(
                name=PressureFactorName.KNOWLEDGE_DEFICIT,
                value=deficit_value,
                evidence_ids=(),
                basis=deficit_basis,
            )
        )
    else:
        factors.append(
            PressureFactor(
                name=PressureFactorName.KNOWLEDGE_DEFICIT,
                value=None,
                evidence_ids=(),
                basis="Memory context unavailable (no provider result); deficit unknown",
            )
        )

    if events:
        last = max(events, key=lambda e: (e.observed_at, e.observation_canonical))
        factors.append(
            PressureFactor(
                name=PressureFactorName.FRESHNESS,
                value=_round4(_decay(last.observed_at, now, config.half_life_seconds)),
                evidence_ids=(last.observation_canonical,),
                basis=f"last evidence at {last.observed_at.isoformat()}",
            )
        )
    else:
        factors.append(
            PressureFactor(
                name=PressureFactorName.FRESHNESS,
                value=None,
                evidence_ids=(),
                basis="no evidence in window; freshness unknown",
            )
        )

    available = [f for f in factors if f.value is not None]
    missing_names = [f.name for f in factors if f.value is None]
    score: float | None = None
    if available:
        score = 1.0
        for factor in available:
            score *= factor.value ** weights.for_factor(factor.name)
        score = _round4(score)

    confidence = 0.5 ** len(missing_names)
    distinct_observation_ids = {
        obs_id
        for factor in available
        for obs_id in factor.evidence_ids
    }
    uncertainty_parts: list[str] = []
    if missing_names:
        uncertainty_parts.append(
            "missing factors lower confidence: " + ", ".join(n.value for n in missing_names)
        )
    if len(distinct_observation_ids) < config.min_evidence_diversity:
        confidence = min(confidence, 0.5)
        uncertainty_parts.append(
            f"evidence diversity below minimum ({len(distinct_observation_ids)} distinct "
            f"observations of {config.min_evidence_diversity} required)"
        )
    uncertainty_parts.append(
        f"decay half-life {config.half_life_seconds / SECONDS_PER_DAY:.0f}d; "
        "score is a prioritization aid, never a quality judgment"
    )

    pressure = LearningPressure(
        factors=tuple(factors),
        score=score,
        confidence=round(confidence, 3),
        claim_kind=ClaimKind.DERIVED if score is not None else ClaimKind.UNKNOWN,
        uncertainty="; ".join(uncertainty_parts),
    )
    details = SignalDetails(
        change_observations=tuple(distinct_change_obs),
        failures=tuple(sorted({e.observation_canonical for e in failures})),
        passed=tuple(sorted({e.observation_canonical for e in passed})),
        verifications=tuple(sorted({e.observation_canonical for e in verifications})),
        intents=tuple(sorted({e.observation_canonical for e in intents})),
        flips=flips,
        rollbacks=rollbacks,
        rework_excess=rework_excess,
        activity_dates=len(activity_dates),
        first_seen_in_window=(
            entity_first_seen is not None and entity_first_seen >= window_start
        ),
    )
    return pressure, details


@dataclass(frozen=True, slots=True)
class ScoredSignal:
    """One detected internal signal with its pressure and lineage receipt."""

    signal: InternalSignal
    receipt: LineageReceipt
    pressure: LearningPressure
    paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError("scored signals require at least one entity path")


@dataclass(frozen=True, slots=True)
class SignalScanResult:
    """Full output of one deterministic local scan; everything is inspectable."""

    project: Identity
    repository_key: str
    window_start: datetime
    window_end: datetime
    signals: tuple[ScoredSignal, ...]
    cost_records: tuple[CostRecord, ...]
    gaps: tuple[str, ...]


def _split_evidence_refs(evidence_ids: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    performance_refs: list[str] = []
    change_refs: list[str] = []
    for raw in evidence_ids:
        try:
            identity = Identity.parse(raw)
        except ValueError:
            performance_refs.append(raw)
            continue
        if identity.kind is EntityKind.CHANGE_SET:
            change_refs.append(raw)
        else:
            performance_refs.append(raw)
    return tuple(performance_refs), tuple(change_refs)


def _make_signal(
    project: Identity,
    *,
    signal_kind: str,
    paths: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    dimensions: tuple[PressureDimension, ...],
    pressure: LearningPressure,
    summary: str,
    window_start: datetime,
    window_end: datetime,
    gaps: tuple[str, ...],
    entity_refs: tuple[str, ...],
    cost_ref: object,
    now: datetime,
) -> ScoredSignal:
    evidence_digest = ";".join(sorted(evidence_ids)) or "no-evidence"
    identity = internal_signal_identity(project, signal_kind, window_start, evidence_digest)
    performance_refs, change_refs = _split_evidence_refs(evidence_ids)
    signal = InternalSignal(
        identity=identity,
        project=project,
        signal_kind=signal_kind,
        dimensions=tuple(dict.fromkeys(dimensions)),
        window_start=window_start,
        window_end=window_end,
        claim_kind=pressure.claim_kind,
        method=DERIVATION_METHOD,
        method_version=DERIVATION_VERSION,
        uncertainty=pressure.uncertainty[:280],
        summary=summary[:280],
        performance_refs=performance_refs,
        entity_refs=entity_refs,
        evidence_ids=evidence_ids,
        confidence=pressure.confidence,
        gaps=gaps,
    )
    receipt = LineageReceipt(
        identity=lineage_receipt_identity(
            project,
            DERIVATION_METHOD,
            DERIVATION_VERSION,
            window_start,
            window_end,
            performance_refs,
            change_refs,
            (),
        ),
        project=project,
        derivation_method=DERIVATION_METHOD,
        derivation_version=DERIVATION_VERSION,
        window_start=window_start,
        window_end=window_end,
        claim_kind=ClaimKind.DERIVED,
        privacy_decision="local_only",
        created_at=now,
        performance_evidence_ids=performance_refs,
        repository_change_refs=change_refs,
        memory_refs=(),
        gaps=gaps,
        confidence=pressure.confidence,
        cost_ref=cost_ref,
    )
    return ScoredSignal(signal=signal, receipt=receipt, pressure=pressure, paths=paths)


def scan_signals(
    project: Identity,
    repository_key: str,
    *,
    envelopes: tuple[ObservationEnvelope, ...] | list,
    refs_by_path: Mapping[str, ProjectEntityRef] | None = None,
    window_start: datetime,
    window_end: datetime,
    config: PressureConfig = PressureConfig(),
    now: datetime,
    memory_status: InternalAnswerStatus | None = None,
    job: ProjectIntelligenceJob | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
) -> SignalScanResult:
    """One bounded, deterministic, local scan: join evidence, detect, score, account.

    ``envelopes`` are Performance-owned observations exactly as
    ``EvidenceLedger.replay()`` yields them.  ``refs_by_path`` maps entity
    paths to their resolved ProjectEntityRef.  Everything is
    project-scoped and fails closed on cross-project evidence.
    """
    if now.tzinfo is None:
        raise ValueError("scan time must be timezone-aware")
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("scan window must be timezone-aware")
    joined = join_evidence(
        envelopes, project, window_start=window_start, window_end=window_end
    )
    started = monotonic()
    refs_by_path = refs_by_path or {}
    cost_identity = (
        new_event_identity(RepoIntelligenceKind.COST_RECORD) if job is not None else None
    )

    partner_paths: dict[str, set[str]] = {}
    partner_evidence: dict[str, set[str]] = {}
    for co_change in joined.co_changes:
        for path in co_change.paths:
            partner_paths.setdefault(path, set()).update(set(co_change.paths) - {path})
            partner_evidence.setdefault(path, set()).add(co_change.observation_canonical)

    scored: list[ScoredSignal] = []

    def emit(kind: str, paths: tuple[str, ...], evidence: tuple[str, ...], summary: str, gaps: tuple[str, ...] = ()) -> None:
        path_refs = tuple(
            dict.fromkeys(
                refs_by_path[p].identity.canonical for p in paths if p in refs_by_path
            )
        )
        scored.append(
            _make_signal(
                project,
                signal_kind=kind,
                paths=paths,
                evidence_ids=evidence,
                dimensions=pressure_for_last.covered_dimensions(),
                pressure=pressure_for_last,
                summary=summary,
                window_start=window_start,
                window_end=window_end,
                gaps=gaps,
                entity_refs=path_refs,
                cost_ref=cost_identity,
                now=now,
            )
        )

    for path, events in joined.timelines.items():
        ref = refs_by_path.get(path)
        pressure_for_last, details = score_path_pressure(
            path,
            events,
            window_start=window_start,
            window_end=window_end,
            config=config,
            now=now,
            partner_paths=tuple(sorted(partner_paths.get(path, ()))),
            partner_evidence=tuple(sorted(partner_evidence.get(path, ()))),
            memory_status=memory_status,
            entity_first_seen=ref.first_seen_at if ref is not None else None,
        )
        changes = details.change_observations
        failures = details.failures
        all_evidence = tuple(dict.fromkeys(e.observation_canonical for e in events))

        if len(changes) >= 2:
            emit(
                "churn",
                (path,),
                changes,
                f"churn on {path}: {len(changes)} change observations; "
                "churn records activity, never a defect judgment",
            )
        if len(changes) >= config.rework_min_changes and (
            failures or details.flips or details.rollbacks or details.intents
        ):
            emit(
                "rework",
                (path,),
                tuple(dict.fromkeys(changes + failures + details.intents)),
                f"rework on {path}: {len(changes)} distinct changes with friction/intent evidence",
            )
        if failures:
            emit(
                "verification_failure",
                (path,),
                failures,
                f"verification failures on {path}: {len(failures)} failed observations",
            )
        if details.flips >= 2:
            emit(
                "flaky_verification",
                (path,),
                details.verifications,
                f"flaky verification on {path}: {details.flips} pass/fail flips",
            )
        if len(details.intents) >= 2:
            emit(
                "recurring_intent",
                (path,),
                details.intents,
                f"recurring intent on {path}: {len(details.intents)} episode-correlated prompt runs",
            )
        if details.rollbacks:
            emit(
                "rollback",
                (path,),
                changes,
                f"rollback on {path}: deletion following modification within the window",
            )
        if changes and not details.verifications:
            emit(
                "evidence_gap",
                (path,),
                changes,
                f"evidence gap on {path}: changes without any verification evidence",
                gaps=("no verification observations reached this entity in the window",),
            )
        if details.first_seen_in_window and (failures or details.rework_excess):
            emit(
                "unfamiliar_subsystem",
                (path,),
                tuple(dict.fromkeys(changes + failures)),
                f"unfamiliar subsystem {path}: first seen in this window with friction",
            )
        if details.activity_dates >= config.recurring_task_days and len(changes) >= 2:
            emit(
                "recurring_task",
                (path,),
                changes,
                f"recurring task pattern on {path}: activity on {details.activity_dates} distinct days",
            )

    pair_cache: dict[tuple[str, str], set[str]] = {}
    for co_change in joined.co_changes:
        for left, right in combinations(co_change.paths, 2):
            pair = (left, right) if left < right else (right, left)
            pair_cache.setdefault(pair, set()).add(co_change.observation_canonical)
    for (left, right), pair_evidence_set in sorted(pair_cache.items()):
        pair_evidence = tuple(sorted(pair_evidence_set))
        if len(pair_evidence) < 2:
            continue
        pair_events: tuple[EvidenceEvent, ...] = tuple(
            event
            for path in (left, right)
            for event in joined.timelines.get(path, ())
            if event.observation_canonical in pair_evidence_set
        )
        pressure_for_last, _ = score_path_pressure(
            left,
            pair_events,
            window_start=window_start,
            window_end=window_end,
            config=config,
            now=now,
            partner_paths=(right,),
            partner_evidence=pair_evidence,
            memory_status=memory_status,
        )
        emit(
            "coupling",
            (left, right),
            pair_evidence,
            f"coupling between {left} and {right}: co-changed in {len(pair_evidence)} observations",
        )

    cost_records: tuple[CostRecord, ...] = ()
    if job is not None and cost_identity is not None:
        cost_records = (
            CostRecord(
                identity=cost_identity,
                project=project,
                job=job.identity,
                resource=CostResourceKind.LOCAL_COMPUTE,
                provider="deterministic-local",
                latency_ms=_round4((monotonic() - started) * 1000.0),
                occurred_at=now,
                cache_status=CacheStatus.MISS,
            ),
        )

    ordered = tuple(
        sorted(scored, key=lambda s: (s.paths, s.signal.signal_kind, s.signal.identity.canonical))
    )
    return SignalScanResult(
        project=project,
        repository_key=repository_key,
        window_start=window_start,
        window_end=window_end,
        signals=ordered,
        cost_records=cost_records,
        gaps=joined.gaps,
    )


__all__ = [
    "DERIVATION_METHOD",
    "DERIVATION_VERSION",
    "LearningPressure",
    "PressureConfig",
    "PressureFactor",
    "PressureFactorName",
    "PressureWeights",
    "ScoredSignal",
    "SignalDetails",
    "SignalScanResult",
    "scan_signals",
    "score_path_pressure",
]
