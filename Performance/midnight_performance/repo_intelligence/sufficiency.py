"""Per-question Memory sufficiency & knowledge-gap qualification.

Repo Intelligent 02, Execution 02: the internal-knowledge gate must decide,
for the SPECIFIC research question being considered, whether Performance +
Memory already provide enough evidence to answer it. Sufficiency is a
routing decision, not a new Memory record — nothing here is persisted.

Deterministic and cheap-first by design: no model or network access is
involved beyond the one bounded, concept-scoped Memory read
(`MemoryBridgePort.read_context`). A future learned predictor may replace or
augment this, but it must be allowed to abstain and must never override the
hard rules enforced here (contradiction, freshness, provenance).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..contracts import ClaimKind
from .contracts import InternalAnswerStatus
from .ports import MemoryBridgePort
from .signals import ScoredSignal

DEFAULT_FRESHNESS_WINDOW = timedelta(days=90)

_VERIFICATION_TEMPLATE_KINDS = frozenset(
    {"verification_failure", "flaky_verification", "rework", "rollback"}
)

_UNATTRIBUTED_AUTHORITY_TIER = "unattributed"
_MIN_CONFIDENCE = 0.5


@dataclass(frozen=True, slots=True)
class SufficiencyDimension:
    """One explainable factor behind a sufficiency decision.

    `passed` is `None` when the dimension could not be evaluated at all
    (missing/malformed data) — that is never silently treated as a pass.
    """

    name: str
    passed: bool | None
    detail: str


@dataclass(frozen=True, slots=True)
class SufficiencyDecision:
    """The per-question outcome of the internal-knowledge gate."""

    status: InternalAnswerStatus
    dimensions: tuple[SufficiencyDimension, ...]
    expected_information_value: bool
    diagnostic: str


def _diagnostic(status: InternalAnswerStatus, dimensions: tuple[SufficiencyDimension, ...]) -> str:
    parts = [
        f"{d.name}={'pass' if d.passed else ('unknown' if d.passed is None else 'fail')}"
        for d in dimensions
    ]
    return f"{status.value}: " + ("; ".join(parts) if parts else "no dimensions evaluated")


def _decision(
    status: InternalAnswerStatus,
    dimensions: tuple[SufficiencyDimension, ...],
    *,
    expected_information_value: bool,
) -> SufficiencyDecision:
    return SufficiencyDecision(
        status=status,
        dimensions=dimensions,
        expected_information_value=expected_information_value,
        diagnostic=_diagnostic(status, dimensions),
    )


def _absent_unavailable(reason: str) -> SufficiencyDecision:
    dims = (SufficiencyDimension("memory_bridge", False, reason),)
    decision = _decision(InternalAnswerStatus.ABSENT, dims, expected_information_value=True)
    return SufficiencyDecision(
        status=decision.status,
        dimensions=decision.dimensions,
        expected_information_value=decision.expected_information_value,
        diagnostic=f"ABSENT/UNAVAILABLE: {reason}",
    )


def _parse_observed_at(record: dict) -> datetime | None:
    raw = record.get("observedAt")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_sufficiency(
    *,
    concept: str,
    template_kind: str,
    scored: ScoredSignal,
    memory: MemoryBridgePort | None,
    project_key: str,
    now: datetime,
    freshness_window: timedelta = DEFAULT_FRESHNESS_WINDOW,
) -> SufficiencyDecision:
    """Deterministically qualify internal sufficiency for one compiled concept.

    Uses a bounded, concept-scoped Memory read (`query=concept`) rather than
    an unscoped project-wide read, so the decision is actually about the
    question being considered, not a coarse project-level guess.
    """
    if memory is None:
        return _absent_unavailable("no Memory bridge configured")

    try:
        result = memory.read_context(project_key, size=5, query=concept)
    except Exception as exc:  # provider boundary: degrade without leaking payload text
        return _absent_unavailable(f"memory bridge raised {type(exc).__name__}")

    if not result.available:
        return _absent_unavailable(str(result.error_code))

    if not result.records:
        dims = (
            SufficiencyDimension(
                "relevance", False, f"no record matched concept '{concept}' via Memory's query filter"
            ),
        )
        return _decision(InternalAnswerStatus.ABSENT, dims, expected_information_value=True)

    records = result.records

    # Hard rule 1: contradiction always wins, checked before anything else.
    open_contradictions = [
        entry["record"].get("recordId", "?")
        for entry in records
        if isinstance(entry.get("contradiction"), dict) and entry["contradiction"].get("status") == "open"
    ]
    if open_contradictions:
        dims = (
            SufficiencyDimension(
                "contradiction",
                False,
                f"open contradiction among record(s) {', '.join(open_contradictions)}",
            ),
        )
        return _decision(InternalAnswerStatus.CONTRADICTED, dims, expected_information_value=True)
    contradiction_dim = SufficiencyDimension("contradiction", True, "no open contradiction found")

    # Hard rule 2: freshness. A record with an unparseable timestamp counts
    # as unknown, never as fresh.
    freshness_floor = now - freshness_window
    observed_ats = [_parse_observed_at(entry["record"]) for entry in records]
    known_observed_ats = [ts for ts in observed_ats if ts is not None]
    has_fresh_record = any(ts >= freshness_floor for ts in known_observed_ats)
    if known_observed_ats and not has_fresh_record:
        dims = (
            contradiction_dim,
            SufficiencyDimension(
                "freshness",
                False,
                f"newest matched record is older than the {freshness_window.days}-day freshness window",
            ),
        )
        return _decision(InternalAnswerStatus.STALE, dims, expected_information_value=True)

    freshness_dim = SufficiencyDimension(
        "freshness",
        None if (not known_observed_ats) else True,
        "no record carried a parseable observedAt timestamp"
        if not known_observed_ats
        else "at least one matched record is within the freshness window",
    )

    relevance_dim = SufficiencyDimension(
        "relevance", True, f"{len(records)} record(s) matched concept '{concept}' via Memory's query filter"
    )

    coverage_ok = any(
        int(entry.get("evidenceCount") or 0) >= 1 and not entry.get("evidenceGaps")
        for entry in records
    )
    all_gaps = sorted({gap for entry in records for gap in (entry.get("evidenceGaps") or [])})
    coverage_dim = SufficiencyDimension(
        "coverage",
        coverage_ok,
        "at least one record has evidence with no coverage gaps"
        if coverage_ok
        else f"no record has full evidence coverage; gaps={all_gaps}" if all_gaps else "no record carries any evidence",
    )

    provenance_ok = any(
        (entry.get("authority") or {}).get("tier") not in (None, _UNATTRIBUTED_AUTHORITY_TIER)
        for entry in records
    )
    provenance_dim = SufficiencyDimension(
        "provenance",
        provenance_ok,
        "at least one record carries attributed structural authority"
        if provenance_ok
        else "every matched record is unattributed or missing authority",
    )

    confidences = [entry.get("confidence") for entry in records if isinstance(entry.get("confidence"), (int, float))]
    confidence_unscoreable = not confidences
    signal_claim_known = scored.signal.claim_kind is not ClaimKind.UNKNOWN
    confidence_ok = bool(confidences) and max(confidences) >= _MIN_CONFIDENCE and signal_claim_known
    confidence_dim = SufficiencyDimension(
        "confidence",
        None if confidence_unscoreable else confidence_ok,
        "no matched record carries a numeric confidence"
        if confidence_unscoreable
        else (
            f"top confidence {max(confidences):.2f} meets floor and signal claim kind is known"
            if confidence_ok
            else f"top confidence {max(confidences):.2f} below floor or signal claim kind unknown"
        ),
    )

    dims = [contradiction_dim, freshness_dim, relevance_dim, coverage_dim, provenance_dim, confidence_dim]

    if template_kind in _VERIFICATION_TEMPLATE_KINDS:
        # Performance canonically owns verification/outcome history for its own
        # signals — this dimension is scored from the signal's own gaps, never
        # from Memory record content, so Memory is never asked to answer what
        # Performance already knows about its own development history.
        verified = not scored.signal.gaps
        verification_dim = SufficiencyDimension(
            "verification_support",
            verified,
            "Performance's own signal carries no unresolved verification gaps"
            if verified
            else f"Performance's own signal still carries gaps: {list(scored.signal.gaps)}",
        )
        dims.append(verification_dim)

    material = [d for d in dims if d.passed is not None]
    unscoreable_material = [d for d in dims if d.passed is None]
    all_pass = all(d.passed for d in material)
    any_fail = any(d.passed is False for d in material)

    if all_pass and not unscoreable_material:
        return _decision(InternalAnswerStatus.SUFFICIENT, tuple(dims), expected_information_value=False)
    if unscoreable_material and not any_fail:
        return _decision(InternalAnswerStatus.UNKNOWN, tuple(dims), expected_information_value=True)
    return _decision(InternalAnswerStatus.PARTIAL, tuple(dims), expected_information_value=True)


__all__ = [
    "DEFAULT_FRESHNESS_WINDOW",
    "SufficiencyDecision",
    "SufficiencyDimension",
    "evaluate_sufficiency",
]
