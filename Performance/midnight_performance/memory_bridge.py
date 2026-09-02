"""Bridge from Midnight Performance to Midnight Memory's versioned contract.

Memory is the canonical owner of durable cross-session/project knowledge;
Performance remains the canonical owner of development-history evidence. This
module is the concrete, language-neutral boundary between them: it maps
Performance project/workspace identities to Memory scope identities, builds
JSON envelopes matching Memory's own `MemoryRequestEnvelope`/
`MemoryResponseEnvelope` contract (`Memory/src/contracts/operations.ts`), and
exchanges them by calling Memory's CLI `contract call` surface as a
subprocess. It never opens Memory's SQLite store directly, and it never
copies raw Performance evidence into Memory — only bounded, evidence-backed
lesson statements referencing Performance observations by their stable
canonical identity.

Task 4 (identity mapping): mirrors `Memory/src/engine/performanceIdentity.ts`.
Performance's canonical identity string (`mp:v<version>:<kind>:<uuid>`,
`Identity.canonical`) contains colons, which a Memory projectKey
(`[\\w][\\w.-]*`) cannot. The colon-to-dot substitution below is lossless and
its inverse unambiguous, because neither an `EntityKind` value nor a UUID's
canonical form ever contains a literal dot. Scoped to PROJECT/WORKSPACE
identities only — Memory scopes correspond to Performance projects/
workspaces, never to evidence-record identities (Performance's own
`Observation.identity` is restricted to a disjoint whitelist of evidence
kinds that excludes PROJECT/WORKSPACE).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

from .authority import QualifiedClaim
from .contracts import ClaimKind, EntityKind, ExternalReference, Identity
from .observation_model import ObservationEnvelope
from .privacy import redact_sensitive_text
from .provenance import verify

_PERFORMANCE_IDENTITY_KINDS = (EntityKind.PROJECT, EntityKind.WORKSPACE)
_PROJECT_KEY_RE = re.compile(r"^[\w][\w.-]*$")

# Only the MAJOR segment is enforced by Memory's dispatcher (majorOf() in
# Memory/src/engine/dispatcher.ts splits on "." and compares the first
# segment only), so this pinned minor/patch is allowed to drift from the
# live Memory checkout without needing a lockstep bump here.
MEMORY_CONTRACT_VERSION = "1.26.0"


def project_key_for_identity(identity: Identity) -> str:
    """Map a Performance PROJECT/WORKSPACE Identity to a Memory projectKey."""
    if identity.kind not in _PERFORMANCE_IDENTITY_KINDS:
        raise ValueError(
            f"identity kind '{identity.kind.value}' cannot map to a Memory "
            f"projectKey; only {[k.value for k in _PERFORMANCE_IDENTITY_KINDS]} are supported"
        )
    project_key = identity.canonical.replace(":", ".")
    if not _PROJECT_KEY_RE.match(project_key):
        raise ValueError(f"mapped projectKey '{project_key}' is not a valid Memory projectKey")
    return project_key


def identity_from_project_key(project_key: str) -> Identity:
    """Inverse of project_key_for_identity — recovers the exact Identity."""
    if not _PROJECT_KEY_RE.match(project_key):
        raise ValueError(f"'{project_key}' is not a valid Memory projectKey")
    parts = project_key.split(".")
    if len(parts) != 4:
        raise ValueError(f"'{project_key}' is not a Performance-derived projectKey")
    identity = Identity.parse(":".join(parts))
    if identity.kind not in _PERFORMANCE_IDENTITY_KINDS:
        raise ValueError(f"identity kind '{identity.kind.value}' is not project/workspace")
    return identity


# ---------------------------------------------------------------------------
# Task 5: the versioned contract envelope + Memory CLI subprocess client.
#
# Memory already defines a versioned, language-neutral JSON envelope
# (`MemoryRequestEnvelope`/`MemoryResponseEnvelope`,
# Memory/src/contracts/operations.ts) and exposes it as a subprocess-callable
# surface via its CLI (`contract call --operation <op> --request '<json>'`,
# Memory/src/cli/cli.ts). This module builds envelopes matching that exact
# shape and calls the CLI as a subprocess — no new Memory-side contract is
# introduced. `memory.performance.propose` is the write direction;
# `memory.context` (bounded, scoped, provenance-rich) is reused as-is for the
# read direction — Memory does not need a Performance-specific read
# operation.
# ---------------------------------------------------------------------------


class MemoryUnavailableError(Exception):
    """The Memory CLI subprocess could not be reached or produced no valid
    JSON response: node/cli.ts not found, the call timed out, or stdout was
    not parseable JSON. Distinct from MemoryContractError, which means
    Memory *was* reached and returned a typed failure."""


class MemoryContractError(Exception):
    """Memory returned a typed ok:false envelope (or an equivalent CLI-level
    failure). Mirrors {error.code, error.message} as catchable attributes so
    callers can react to specific codes (e.g. MEMORY_CONTRACT_MISMATCH)
    without string matching."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def build_propose_envelope(project_key: str, lessons: list[dict], *, caller: dict | None = None) -> dict:
    """Build a `memory.performance.propose` request envelope. `lessons` are
    plain dicts matching Memory's PerformanceLesson shape
    (`{subject, content, evidenceRefs: [str, ...], note?, ...}`) — build them
    with `lesson_from_sealed_envelope` so evidence is never unverifiable."""
    request: dict = {"scope": project_key, "lessons": lessons}
    if caller is not None:
        request["caller"] = caller
    return {
        "contractVersion": MEMORY_CONTRACT_VERSION,
        "operation": "memory.performance.propose",
        "request": request,
    }


def _verified_identity(sealed: ObservationEnvelope) -> str:
    """Task 6 (evidence-reference hardening) — the "inaccessible" enforcement
    point, shared by every lesson-building path below: `sealed` must be
    genuinely sealed AND pass checksum verification (`verify(sealed) is
    True`) before its identity is eligible to become Memory evidence.
    `verify` returns None for an envelope that was never sealed and False
    for one that fails its checksum (tampered) — both are refused here,
    before any call to Memory is attempted, so Memory never receives an
    unverifiable reference and never has to pretend it can confirm
    reachability itself (it structurally cannot: no direct sibling-store
    access). This proves integrity/sealedness, not ledger membership — see
    docs/EVIDENCE_REFERENCES.md's "honest limits" section.
    """
    verified = verify(sealed)
    if verified is not True:
        state = "never sealed" if verified is None else "checksum mismatch (tampered)"
        raise ValueError(f"evidence envelope is not eligible as Memory evidence: {state}")
    return sealed.observation.identity.canonical


def lesson_from_sealed_envelope(
    sealed: ObservationEnvelope,
    *,
    subject: str,
    content: str,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Build one PerformanceLesson dict (Memory's
    `Memory/src/engine/performance.ts` PerformanceLesson shape) from a
    SEALED observation envelope's stable identity. See `_verified_identity`
    for the sealed/verified enforcement this relies on.

    `content` is always the caller-authored lesson statement — the raw
    `sealed.observation.payload` is NEVER copied into it (content
    minimization, Memory/docs/BOUNDARY.md Section 0). As a structural
    backstop (Task 17, Execution 06) — not a substitute for that discipline
    — `subject`/`content`/`note` are passed through
    `redact_sensitive_text` (the same secret/email pattern PrivacyGuard
    applies to payload fields) before crossing to Memory, so a stray
    secret that slips into caller-authored text is still caught here.

    Task 9 (delivery semantics): `idempotency_key` defaults to the
    envelope's own canonical identity — already Performance's stable,
    replay-safe per-observation id, so re-exporting the same observation
    always replays to the same Memory candidate with no extra bookkeeping.
    Pass an explicit key to override.
    """
    ref = _verified_identity(sealed)
    lesson: dict = {
        "subject": redact_sensitive_text(subject),
        "content": redact_sensitive_text(content),
        "evidenceRefs": [ref],
        "idempotencyKey": idempotency_key if idempotency_key is not None else ref,
    }
    if note:
        lesson["note"] = redact_sensitive_text(note)
    return lesson


# Mirrors Memory/src/engine/performance.ts's MAX_PERFORMANCE_EVIDENCE_PER_LESSON.
# Cannot share a literal across languages; Memory's own validation remains
# the final authority — this bound only lets the exporter fail closed early.
_MAX_EVIDENCE_PER_LESSON = 8

# ClaimKind -> Memory EpistemicClass. NEVER upgrades claim strength (mirrors
# authority.py's own preferred() rule: "never upgrade claim qualification").
# Memory has no "statistical"/"predicted" class; both map to the closest
# class that is not stronger than what they actually are: "inferred".
_CLAIM_KIND_TO_EPISTEMIC_CLASS = {
    ClaimKind.OBSERVED: "observed",
    ClaimKind.DERIVED: "derived",
    ClaimKind.INFERRED: "inferred",
    ClaimKind.STATISTICAL: "inferred",
    ClaimKind.PREDICTED: "inferred",
    ClaimKind.RECOMMENDED: "recommendation",
    ClaimKind.UNKNOWN: "unknown",
}


def lesson_from_qualified_claim(
    claim: QualifiedClaim,
    sealed_envelopes: list[ObservationEnvelope],
    *,
    subject: str,
    content: str | None = None,
) -> dict:
    """Task 8: the lesson exporter. Turns a real Performance analysis object
    (a QualifiedClaim — Performance's own evidence-authority-checked claim,
    never raw agent prose) grounded in one or more sealed observation
    envelopes into a bounded, evidence-backed Memory lesson, deriving
    epistemicClass/content/idempotencyKey deterministically so callers don't
    have to hand-author epistemic classification per lesson.

    `subject`/`content` are passed through `redact_sensitive_text` before
    crossing to Memory (Task 17, Execution 06) — the same structural
    backstop `lesson_from_sealed_envelope` applies.
    """
    if not sealed_envelopes:
        raise ValueError("a QualifiedClaim lesson requires at least one grounding envelope")
    # Deduplicate identical evidence identities before bounding — Memory's
    # own validation rejects duplicate {engine, ref} pairs (Execution 02
    # Task 6), so collapsing them here first means a caller who happens to
    # pass the same envelope twice never hits that rejection unnecessarily.
    refs = sorted({_verified_identity(envelope) for envelope in sealed_envelopes})
    if len(refs) > _MAX_EVIDENCE_PER_LESSON:
        raise ValueError(f"a lesson may carry at most {_MAX_EVIDENCE_PER_LESSON} distinct evidence refs")
    epistemic_class = _CLAIM_KIND_TO_EPISTEMIC_CLASS[claim.claim_kind]
    if content is None:
        parts = [f"{claim.claim_type.value} claim from {claim.source.value}"]
        if claim.method:
            parts.append(f"method={claim.method}" + (f" v{claim.method_version}" if claim.method_version else ""))
        if claim.confidence is not None:
            parts.append(f"confidence={claim.confidence}")
        if claim.uncertainty:
            parts.append(claim.uncertainty)
        content = "; ".join(parts)
    lesson: dict = {
        "subject": redact_sensitive_text(subject),
        "content": redact_sensitive_text(content),
        "evidenceRefs": refs,
        "epistemicClass": epistemic_class,
        "idempotencyKey": "claim:" + hashlib.sha256("|".join(refs).encode()).hexdigest(),
    }
    if claim.confidence is not None:
        lesson["confidence"] = claim.confidence
    return lesson


def build_context_envelope(project_key: str, **filters) -> dict:
    """Build a `memory.context` request envelope — the read direction of
    this bridge. Reuses Memory's existing bounded, scoped, provenance-rich
    context operation rather than a Performance-specific read surface."""
    return {
        "contractVersion": MEMORY_CONTRACT_VERSION,
        "operation": "memory.context",
        "request": {"scope": project_key, **filters},
    }


def call_memory_cli(
    envelope: dict,
    *,
    memory_repo_path: str | os.PathLike,
    store_path: str | os.PathLike | None = None,
    node_executable: str = "node",
    timeout_seconds: float = 30.0,
) -> dict:
    """The ONLY way this module talks to Memory: a subprocess call to
    Memory's own CLI `contract call` surface. NEVER opens or reads Memory's
    SQLite store file directly — that file is private to the Memory engine
    (Memory/src/index.ts's module-surface contract), and this function is
    the concrete, testable enforcement point proving Performance never
    bypasses it.

    Raises MemoryUnavailableError when Memory could not be reached at all
    (node/cli.ts missing, timeout, unparseable stdout), or
    MemoryContractError when Memory was reached and returned a typed
    failure (e.g. MEMORY_CONTRACT_MISMATCH, MEMORY_VALIDATION_FAILED).
    Never returns a response that claims success without Memory actually
    having said so.
    """
    cli_path = os.path.join(str(memory_repo_path), "src", "cli", "cli.ts")
    argv = [
        node_executable,
        "--experimental-strip-types",
        cli_path,
        "contract",
        "call",
        "--operation",
        envelope["operation"],
        "--request",
        json.dumps(envelope["request"]),
        "--version",
        envelope["contractVersion"],
    ]
    if store_path is not None:
        argv += ["--store", str(store_path)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        raise MemoryUnavailableError(f"node executable '{node_executable}' not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise MemoryUnavailableError(f"Memory CLI call timed out after {timeout_seconds}s") from exc
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MemoryUnavailableError(
            f"Memory CLI produced non-JSON stdout (exit {proc.returncode}): "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        ) from exc
    if not parsed.get("ok", False):
        error = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        raise MemoryContractError(
            code=error.get("code", "MEMORY_CLI_ERROR"),
            message=error.get("message", proc.stderr or "unknown Memory CLI failure"),
        )
    return parsed


def call_memory_cli_with_retry(
    envelope: dict,
    *,
    max_retries: int = 3,
    backoff_seconds: float = 0.5,
    **kwargs,
) -> dict:
    """Task 9 (delivery semantics): a bounded-retry wrapper around
    `call_memory_cli`. Retries ONLY `MemoryUnavailableError` (transient:
    node/cli.ts unreachable, timeout, unparseable stdout) up to
    `max_retries` times with linear backoff. NEVER retries
    `MemoryContractError` — a deterministic validation/authorization/
    contract-version failure will fail identically on every retry, so
    retrying it would only be a retry storm with no chance of success; it
    is raised immediately on the first attempt.

    Combined with `lesson_from_sealed_envelope`'s/`lesson_from_qualified_claim`'s
    default idempotencyKey, a retried call is always safe: Memory's own
    idempotent candidate intake (`Memory/src/engine/records.ts`
    `addCandidateImpl`) guarantees a duplicate delivery — whether from this
    retry loop or an entirely separate caller — never creates a second
    candidate.
    """
    attempt = 0
    while True:
        try:
            return call_memory_cli(envelope, **kwargs)
        except MemoryUnavailableError:
            if attempt >= max_retries:
                raise
            time.sleep(backoff_seconds * (attempt + 1))
            attempt += 1


# ---------------------------------------------------------------------------
# Task 11/12 (Execution 04): explicit proposals to / reads from Memory, with
# a truthful degraded mode. These replace the removed local KnowledgeRecord/
# promote()/supersede() duplicate-authority path (memory.py) — turning
# Performance evidence into durable knowledge now ALWAYS goes through here,
# and NEVER pretends to have succeeded when Memory refused or was
# unreachable. Performance's own evidence ledger is completely independent
# of these functions succeeding or failing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LessonDeliveryResult:
    """Outcome of proposing a lesson to Memory. `delivered` is the ONLY
    signal that should ever be treated as "this became durable knowledge" —
    a degraded result (delivered=False) is not a promotion, an error, or a
    retry-worthy failure by itself; it's an honest report of what happened."""

    delivered: bool
    candidate_id: str | None = None
    degraded_reason: str | None = None


def propose_lesson_or_degrade(envelope: dict, *, max_retries: int = 3, **kwargs) -> LessonDeliveryResult:
    """Deliver a `memory.performance.propose` envelope via
    `call_memory_cli_with_retry`. On MemoryUnavailableError,
    MemoryContractError, or Memory accepting zero lessons from the batch,
    returns a typed degraded result instead of raising — the truthful
    degraded mode Task 12 requires. Never raises for a reachable-but-
    rejecting Memory or an unreachable one; a caller that wants to
    distinguish "never even tried" from "tried and failed" should inspect
    `degraded_reason`.
    """
    try:
        response = call_memory_cli_with_retry(envelope, max_retries=max_retries, **kwargs)
    except MemoryUnavailableError as exc:
        return LessonDeliveryResult(delivered=False, degraded_reason=f"memory_unavailable: {exc}")
    except MemoryContractError as exc:
        return LessonDeliveryResult(delivered=False, degraded_reason=f"{exc.code}: {exc.message}")
    accepted = response.get("result", {}).get("accepted", [])
    if not accepted:
        rejected = response.get("result", {}).get("rejected", [])
        reason = f"{rejected[0]['code']}: {rejected[0]['message']}" if rejected else "no candidate accepted"
        return LessonDeliveryResult(delivered=False, degraded_reason=reason)
    return LessonDeliveryResult(delivered=True, candidate_id=accepted[0]["candidateId"])


def read_memory_context_or_none(envelope: dict, **kwargs) -> dict | None:
    """Read via `call_memory_cli` (a single attempt — reads are not
    retried by default, matching `memory.context`'s idempotent/side-effect-
    free nature). Returns `None` — not an exception, not a fabricated empty
    result — when Memory is unavailable or rejects the read, so a caller
    can tell "no prior knowledge" apart from "couldn't ask" only by
    checking for `None` explicitly; this function never conflates the two
    into a silent empty success.
    """
    try:
        response = call_memory_cli(envelope, **kwargs)
    except (MemoryUnavailableError, MemoryContractError):
        return None
    return response.get("result")


# Mirrors Memory's own MAX_CONTEXT_SIZE (Memory/src/engine/context.ts).
# Checked client-side before any call is made; Memory's own server-side
# clamp remains the final authority.
_MAX_CONTEXT_SIZE = 100


@dataclass(frozen=True, slots=True)
class MemoryReadResult:
    """Task 14: outcome of a bounded, typed Memory context read.
    `available` is the ONLY signal that should be treated as "this is live
    Memory data" — a degraded result is never cached or treated as durable
    Performance evidence. Unlike `read_memory_context_or_none`, this
    preserves WHICH typed failure occurred (`error_code`), for callers that
    need to distinguish "Memory unreachable" from "Memory rejected the
    request" without catching exceptions themselves.
    """

    available: bool
    records: tuple[dict, ...] = ()
    error_code: str | None = None
    error_message: str | None = None


def read_performance_context(project_key: str, *, size: int = 20, **kwargs) -> MemoryReadResult:
    """Bounded, typed read of current Memory knowledge for Performance
    analysis use (Task 14). Enforces the size bound client-side — fails
    closed with a typed result rather than silently clamping or trusting
    the server alone. Never persists or caches the returned records
    anywhere: this is one snapshot for one-shot use, never a second, stale
    copy of Memory truth. `**kwargs` (context filters, `memory_repo_path`,
    `store_path`, `node_executable`, `timeout_seconds`) are split between
    `build_context_envelope` and `call_memory_cli` by keyword.
    """
    if not (1 <= size <= _MAX_CONTEXT_SIZE):
        return MemoryReadResult(
            available=False,
            error_code="CLIENT_SIZE_OUT_OF_BOUNDS",
            error_message=f"size must be within [1, {_MAX_CONTEXT_SIZE}], got {size}",
        )
    call_kwarg_names = {"memory_repo_path", "store_path", "node_executable", "timeout_seconds"}
    call_kwargs = {k: v for k, v in kwargs.items() if k in call_kwarg_names}
    filters = {k: v for k, v in kwargs.items() if k not in call_kwarg_names}
    envelope = build_context_envelope(project_key, size=size, **filters)
    try:
        response = call_memory_cli(envelope, **call_kwargs)
    except MemoryUnavailableError as exc:
        return MemoryReadResult(available=False, error_code="MEMORY_UNAVAILABLE", error_message=str(exc))
    except MemoryContractError as exc:
        return MemoryReadResult(available=False, error_code=exc.code, error_message=exc.message)
    # dispatcher.ts's memory.context case wraps ContextQueryResult one level
    # deeper than most operations: {ok, result: {result: ContextQueryResult}}.
    records = tuple(response.get("result", {}).get("result", {}).get("records", []))
    return MemoryReadResult(available=True, records=records)


def citation_from_memory_record(record: dict) -> ExternalReference:
    """Task 15: a stable, by-reference citation of one Memory record AT A
    SPECIFIC REVISION — never the mutable "current" state, never a copy of
    its content. Because Memory's revision rows are immutable and
    append-only, `memory.history` can always reproduce this exact cited
    content later, even after the record is revised or superseded — so a
    later Memory change never silently rewrites what a historical
    Performance citation points at. `record` is one entry from
    `read_performance_context`'s `records` (a ContextRecord dict) or its
    nested `record` (a MemoryRecord dict) — either shape works, since both
    carry `recordId`/`revision`.
    """
    memory_record = record["record"] if "record" in record else record
    return ExternalReference(
        provider="memory", kind="record", value=f"{memory_record['recordId']}#rev{memory_record['revision']}"
    )
