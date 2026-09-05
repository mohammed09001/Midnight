"""Execution 05: a rebuildable, disposable, query-optimized local read
projection over Performance evidence — a CQRS-style materialized view, never
a second source of truth.

The append-only ``EvidenceLedger``/``evidence.jsonl`` remains the sole
canonical authority for observed evidence (Section B). This module never
writes to it and never decides what evidence is valid on its own — every
row here is derived, byte-for-byte, from what ``EvidenceLedger.replay()``
(the same authoritative parser the ledger itself uses) accepted. If this
database is ever deleted, corrupted, or simply wrong, the only fix is
``rebuild()`` — there is no repair path for the projection itself, because
none is needed: it is disposable by construction.

Real benchmarks (captured before this module existed) showed every
Performance read doing a full O(n) file replay: at 100,000 observations, a
single Activity query cost ~3.9s, scaling linearly with history size. This
module exists to eliminate that on the READ side only — see
``Performance/README.md``'s "Rebuildable read projection" section for the
full measured before/after comparison. The APPEND path's own O(n)
duplicate-check cost is a separate, deliberately untouched problem (see that
same section) — canonical-ledger write correctness must never depend on
this disposable store being fresh.

Checkpoint algorithm (Section D): resuming a projection incrementally never
trusts the whole ledger prefix again. Instead it verifies the ledger's TAIL
— the exact bytes of the last line this projection consumed, re-hashed
directly from disk — against what was recorded at the last checkpoint. This
is an O(1) check (one line, not the whole file), sufficient because the
ledger is strictly append-only under the write discipline enforced by
``EvidenceLedger.append`` (Execution 04): once a line is durably flushed and
the append lock released, it is never rewritten. The accepted, deliberate
limitation: a hand-edit of an OLDER line, made after the checkpoint has
already moved past it, is not re-detected by this O(1) check — a full
Merkle-style chain would catch that too, but is over-engineering for what
this execution asks; ``ledger_doctor.py``'s full scan (Section E) is the
tool for auditing the whole file when that's actually a concern. Any
mismatch here fails closed: the projection is discarded and fully rebuilt
from the real, untouched ``ledger.replay()``, so any genuine corruption
always surfaces as the exact same ``ValueError`` replay already raises
today — this module never invents a different error for the same problem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import EntityKind, Identity, deterministic_identity
from .ledger import EvidenceLedger, _cross_process_lock
from .observation_model import ObservationEnvelope
from .privacy import PrivacyGuard, PrivacyPolicy

PROJECTION_SCHEMA_VERSION = 1
PROJECTION_FILENAME = "projection.sqlite3"

# Section G (SQLite WAL gate): rollback-journal by default. Flip to "WAL"
# only after `tests/test_projection_concurrency.py` measurably justifies it
# — a decision gate, not an assumption (see Performance/README.md).
# `MIDNIGHT_PROJECTION_JOURNAL_MODE` is a test-only override so the
# concurrency test can compare both modes across real subprocesses without
# hardcoding the production default to the untested one.
PROJECTION_JOURNAL_MODE = os.environ.get("MIDNIGHT_PROJECTION_JOURNAL_MODE", "DELETE")
_BUSY_TIMEOUT_MS = 30_000

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    canonical_identity        TEXT PRIMARY KEY,
    project                   TEXT NOT NULL,
    entity_kind                TEXT NOT NULL,
    subject                   TEXT NOT NULL,
    observed_at_raw           TEXT NOT NULL,
    observed_at_utc_micros    INTEGER NOT NULL,
    provider                  TEXT NOT NULL,
    provider_event_id         TEXT NOT NULL,
    observation_type          TEXT NOT NULL,
    layer                     TEXT NOT NULL,
    source_sequence           INTEGER,
    ledger_line_start_offset  INTEGER NOT NULL,
    integrity_checksum        TEXT,
    checksum_status           TEXT NOT NULL,
    attributes_json           TEXT NOT NULL,
    schema_version              INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_activity_keyset
    ON observations (project, entity_kind, observed_at_utc_micros, canonical_identity);
CREATE INDEX IF NOT EXISTS idx_observations_provider_event
    ON observations (project, provider, provider_event_id);

CREATE TABLE IF NOT EXISTS checkpoint (
    id                       INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version           INTEGER NOT NULL,
    project_canonical        TEXT NOT NULL,
    ledger_byte_offset       INTEGER NOT NULL,
    ledger_record_count      INTEGER NOT NULL,
    last_line_start_offset   INTEGER NOT NULL,
    last_line_sha256         TEXT NOT NULL,
    last_canonical_identity  TEXT,
    generation                TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class ProjectionCheckpoint:
    schema_version: int
    project_canonical: str
    ledger_byte_offset: int
    ledger_record_count: int
    last_canonical_identity: str | None
    generation: str


@dataclass(frozen=True, slots=True)
class ProjectionRow:
    canonical_identity: str
    observed_at_raw: str


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """A single indexed observation, in full — for point lookups (e.g. the
    Execution 06 graph materializer confirming one Prompt Run's real
    existence + project scope) where `ProjectionRow`'s narrow activity-list
    shape isn't enough."""

    canonical_identity: str
    project: str
    entity_kind: str
    subject: str
    observed_at_raw: str
    provider: str
    provider_event_id: str
    observation_type: str
    layer: str
    attributes_json: str


@dataclass(frozen=True, slots=True)
class ProjectionStatus:
    healthy: bool
    reason: str | None  # None when healthy; else "missing" | "missing_checkpoint" | "schema_mismatch" | "project_mismatch" | "truncated" | "checkpoint_stale" | "behind"
    record_count: int
    checkpoint: ProjectionCheckpoint | None


def projection_path(data_dir: Path) -> Path:
    return data_dir / PROJECTION_FILENAME


def _projection_lock_path(path: Path) -> Path:
    """A lock dedicated to the projection's own build/update lifecycle —
    deliberately separate from the ledger's append lock (`EvidenceLedger`),
    so concurrent projection rebuilds/updates serialize against each other
    without over-serializing against unrelated ledger appends. Reuses
    `ledger._cross_process_lock`, the same cross-platform advisory lock
    mechanism (Execution 04), rather than inventing a second one.

    Real multi-process testing (`tests/test_projection_concurrency.py`)
    found this necessary: on Windows, two processes concurrently deciding
    "no projection exists, I must build one" both call `discard()`, and an
    unlink() racing another process's still-open SQLite handle on the same
    file raises a native sharing-violation `PermissionError` — a genuine
    cross-process race in the projection's own lifecycle, distinct from and
    in addition to the ledger's append race Execution 04 already closed.
    """
    return path.with_name(path.name + ".lock")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000)
    try:
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        conn.execute(f"PRAGMA journal_mode = {PROJECTION_JOURNAL_MODE}")
        conn.executescript(_SCHEMA_SQL)
    except BaseException:
        # `sqlite3.connect()` already opened a file handle even though setup
        # failed (e.g. the file isn't a valid database) — close it before
        # propagating, or the handle leaks and blocks the caller from
        # deleting/replacing the file (observed on Windows).
        conn.close()
        raise
    return conn


def _discard_unlocked(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = path.with_name(path.name + suffix) if suffix else path
        candidate.unlink(missing_ok=True)


def discard(path: Path) -> None:
    """Delete the projection and its SQLite sidecar files. Always safe —
    the next build()/update() call recreates everything from the ledger.
    Locked, like build()/update(), against a concurrent build racing this
    same file on Windows."""
    with _cross_process_lock(_projection_lock_path(path)):
        _discard_unlocked(path)


def _compute_generation(project_canonical: str, ledger_byte_offset: int, last_canonical_identity: str | None) -> str:
    payload = f"{project_canonical}:{ledger_byte_offset}:{last_canonical_identity or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _checksum_status(envelope: ObservationEnvelope) -> str:
    from .provenance import verify as verify_provenance

    result = verify_provenance(envelope)
    if result is None:
        return "unsealed"
    return "sealed_valid" if result else "sealed_invalid"


def _insert_row(conn: sqlite3.Connection, envelope: ObservationEnvelope, line_start_offset: int) -> None:
    observation = envelope.observation
    observed_at_utc_micros = int(observation.observed_at.astimezone(timezone.utc).timestamp() * 1_000_000)
    conn.execute(
        """
        INSERT OR REPLACE INTO observations (
            canonical_identity, project, entity_kind, subject, observed_at_raw, observed_at_utc_micros,
            provider, provider_event_id, observation_type, layer, source_sequence,
            ledger_line_start_offset, integrity_checksum, checksum_status, attributes_json, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation.identity.canonical,
            envelope.project.canonical,
            observation.identity.kind.value,
            observation.subject.canonical,
            observation.observed_at.isoformat(),
            observed_at_utc_micros,
            envelope.provider,
            envelope.provider_event_id,
            envelope.observation_type.value,
            envelope.layer.value,
            envelope.source_sequence,
            line_start_offset,
            envelope.integrity_checksum,
            _checksum_status(envelope),
            json.dumps(dict(envelope.attributes), sort_keys=True, default=str),
            envelope.schema_version,
        ),
    )


def _raw_line_offsets(ledger_path: Path) -> list[tuple[int, bytes]]:
    """(start_offset, raw_line_bytes) for every non-blank line, in file
    order — mirrors `EvidenceLedger.replay()`'s blank-line skip exactly, so
    the result correlates 1:1 with `replay()`'s yielded envelopes. Only
    safe to call on a file that has already passed `replay()`'s own
    validation (bookkeeping over known-good bytes, not re-validating)."""
    offsets: list[tuple[int, bytes]] = []
    if not ledger_path.exists():
        return offsets
    with ledger_path.open("rb") as handle:
        offset = 0
        for raw_line in handle:
            if raw_line.strip():
                offsets.append((offset, raw_line.rstrip(b"\n")))
            offset += len(raw_line)
    return offsets


def _write_checkpoint(
    conn: sqlite3.Connection,
    *,
    project_canonical: str,
    ledger_byte_offset: int,
    ledger_record_count: int,
    last_line_start_offset: int,
    last_line_sha256: str,
    last_canonical_identity: str | None,
) -> ProjectionCheckpoint:
    generation = _compute_generation(project_canonical, ledger_byte_offset, last_canonical_identity)
    conn.execute(
        """
        INSERT INTO checkpoint (
            id, schema_version, project_canonical, ledger_byte_offset, ledger_record_count,
            last_line_start_offset, last_line_sha256, last_canonical_identity, generation, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            schema_version=excluded.schema_version, project_canonical=excluded.project_canonical,
            ledger_byte_offset=excluded.ledger_byte_offset, ledger_record_count=excluded.ledger_record_count,
            last_line_start_offset=excluded.last_line_start_offset, last_line_sha256=excluded.last_line_sha256,
            last_canonical_identity=excluded.last_canonical_identity, generation=excluded.generation,
            updated_at=excluded.updated_at
        """,
        (
            PROJECTION_SCHEMA_VERSION, project_canonical, ledger_byte_offset, ledger_record_count,
            last_line_start_offset, last_line_sha256, last_canonical_identity, generation,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return ProjectionCheckpoint(
        schema_version=PROJECTION_SCHEMA_VERSION,
        project_canonical=project_canonical,
        ledger_byte_offset=ledger_byte_offset,
        ledger_record_count=ledger_record_count,
        last_canonical_identity=last_canonical_identity,
        generation=generation,
    )


_BUILD_CONSISTENCY_RETRY_ATTEMPTS = 5


def _build_unlocked(ledger: EvidenceLedger, path: Path) -> ProjectionCheckpoint:
    """The real rebuild logic, WITHOUT taking the projection lock — for use
    by callers (`update`'s fallback) that already hold it. Never call this
    directly from outside this module; use `build()`/`rebuild()`."""
    # `ledger.replay()` and `_raw_line_offsets()` are two independent reads
    # of the ledger file; the ledger's OWN append lock (a separate lock from
    # this module's) never blocks concurrent writers on our account, so a
    # writer can legitimately grow the file between the two reads under real
    # concurrent load (confirmed by `tests/test_projection_concurrency.py`
    # against real subprocess writers). That is an ordinary, expected race,
    # not corruption — a bounded retry resolves it; a genuine malformed line
    # instead raises straight out of `ledger.replay()` itself, immediately,
    # never retried.
    last_error: RuntimeError | None = None
    for _attempt in range(_BUILD_CONSISTENCY_RETRY_ATTEMPTS):
        envelopes = list(ledger.replay())
        line_offsets = _raw_line_offsets(ledger.path)
        if len(envelopes) == len(line_offsets):
            break
        last_error = RuntimeError("ledger changed while building the projection")
    else:
        raise last_error  # noqa: RSE102 - exhausted every retry attempt

    _discard_unlocked(path)
    conn = _connect(path)
    try:
        for envelope, (line_offset, _raw) in zip(envelopes, line_offsets):
            _insert_row(conn, envelope, line_offset)

        ledger_byte_offset = ledger.path.stat().st_size if ledger.path.exists() else 0
        if envelopes:
            last_line_start_offset, last_raw_line = line_offsets[-1]
            last_canonical_identity = envelopes[-1].observation.identity.canonical
        else:
            last_line_start_offset, last_raw_line, last_canonical_identity = 0, b"", None
        checkpoint = _write_checkpoint(
            conn,
            project_canonical=ledger.project.canonical,
            ledger_byte_offset=ledger_byte_offset,
            ledger_record_count=len(envelopes),
            last_line_start_offset=last_line_start_offset,
            last_line_sha256=hashlib.sha256(last_raw_line).hexdigest(),
            last_canonical_identity=last_canonical_identity,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return checkpoint


def build(ledger: EvidenceLedger, path: Path) -> ProjectionCheckpoint:
    """Full rebuild from byte 0. Uses the real, untouched `ledger.replay()`
    for all parsing/validation — any real corruption raises the exact same
    `ValueError` replay already produces, unmodified.

    Locked against concurrent `build()`/`update()` calls on this SAME
    projection file (see `_projection_lock_path`) — real multi-process
    testing found this necessary on Windows, where two processes racing to
    `discard()`/recreate the same file can hit a native sharing-violation
    error. This is a separate lock from the ledger's own append lock, so a
    (rare) rebuild never blocks unrelated ledger appends."""
    with _cross_process_lock(_projection_lock_path(path)):
        return _build_unlocked(ledger, path)


def _read_line_at(path: Path, start_offset: int, end_offset: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start_offset)
        raw = handle.read(max(0, end_offset - start_offset))
    return raw.rstrip(b"\n")


def _stored_checkpoint(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT schema_version, project_canonical, ledger_byte_offset, ledger_record_count, "
        "last_line_start_offset, last_line_sha256, last_canonical_identity, generation FROM checkpoint WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    keys = ("schema_version", "project_canonical", "ledger_byte_offset", "ledger_record_count",
            "last_line_start_offset", "last_line_sha256", "last_canonical_identity", "generation")
    return dict(zip(keys, row))


def _checkpoint_from_stored(stored: dict[str, Any]) -> ProjectionCheckpoint:
    return ProjectionCheckpoint(
        schema_version=stored["schema_version"],
        project_canonical=stored["project_canonical"],
        ledger_byte_offset=stored["ledger_byte_offset"],
        ledger_record_count=stored["ledger_record_count"],
        last_canonical_identity=stored["last_canonical_identity"],
        generation=stored["generation"],
    )


def _verify_stored_checkpoint(ledger: EvidenceLedger, stored: dict[str, Any]) -> str | None:
    """Returns None when the stored checkpoint's tail still matches the real
    ledger (O(1) — one line, not the whole file); otherwise a reason code."""
    if stored["schema_version"] != PROJECTION_SCHEMA_VERSION:
        return "schema_mismatch"
    if stored["project_canonical"] != ledger.project.canonical:
        return "project_mismatch"
    current_size = ledger.path.stat().st_size if ledger.path.exists() else 0
    if current_size < stored["ledger_byte_offset"]:
        return "truncated"
    if stored["ledger_record_count"] > 0:
        actual_last_line = _read_line_at(ledger.path, stored["last_line_start_offset"], stored["ledger_byte_offset"])
        if hashlib.sha256(actual_last_line).hexdigest() != stored["last_line_sha256"]:
            return "checkpoint_stale"
    return None


def update(ledger: EvidenceLedger, path: Path) -> ProjectionCheckpoint:
    """Verify the checkpoint's tail (O(1)), then ingest only new bytes since
    it. Falls back to a full rebuild on any mismatch or parse failure —
    corruption always surfaces through the authoritative `ledger.replay()`,
    never a bespoke error from this incremental path.

    Locked against concurrent `build()`/`update()` calls on this same
    projection file — the whole verify-then-ingest decision is made under
    one lock acquisition (never released and re-acquired mid-function, which
    would reopen the exact race this lock exists to close)."""
    with _cross_process_lock(_projection_lock_path(path)):
        return _update_unlocked(ledger, path)


def _update_unlocked(ledger: EvidenceLedger, path: Path) -> ProjectionCheckpoint:
    if not path.exists():
        return _build_unlocked(ledger, path)

    conn = _connect(path)
    try:
        stored = _stored_checkpoint(conn)
    finally:
        conn.close()
    if stored is None:
        return _build_unlocked(ledger, path)

    mismatch_reason = _verify_stored_checkpoint(ledger, stored)
    if mismatch_reason is not None:
        return _build_unlocked(ledger, path)

    current_size = ledger.path.stat().st_size if ledger.path.exists() else 0
    if current_size == stored["ledger_byte_offset"]:
        return _checkpoint_from_stored(stored)  # already caught up

    new_bytes, new_eof_offset = ledger.read_new_bytes(stored["ledger_byte_offset"])
    try:
        new_lines = _parse_new_lines(new_bytes, stored["ledger_byte_offset"], ledger.project)
    except Exception:
        return _build_unlocked(ledger, path)

    conn = _connect(path)
    try:
        for line_offset, envelope in new_lines:
            _insert_row(conn, envelope, line_offset)

        if new_lines:
            last_line_start_offset = new_lines[-1][0]
            last_raw_line = new_bytes[last_line_start_offset - stored["ledger_byte_offset"]: new_eof_offset - stored["ledger_byte_offset"]].rstrip(b"\n")
            last_canonical_identity = new_lines[-1][1].observation.identity.canonical
        else:
            last_line_start_offset = stored["last_line_start_offset"]
            last_raw_line = _read_line_at(ledger.path, stored["last_line_start_offset"], stored["ledger_byte_offset"])
            last_canonical_identity = stored["last_canonical_identity"]

        checkpoint = _write_checkpoint(
            conn,
            project_canonical=ledger.project.canonical,
            ledger_byte_offset=new_eof_offset,
            ledger_record_count=stored["ledger_record_count"] + len(new_lines),
            last_line_start_offset=last_line_start_offset,
            last_line_sha256=hashlib.sha256(last_raw_line).hexdigest(),
            last_canonical_identity=last_canonical_identity,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return checkpoint


def _parse_new_lines(new_bytes: bytes, base_offset: int, project: Identity) -> list[tuple[int, ObservationEnvelope]]:
    results: list[tuple[int, ObservationEnvelope]] = []
    offset = base_offset
    for raw_line in new_bytes.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        if not raw_line.strip():
            continue
        envelope = ObservationEnvelope.from_dict(json.loads(raw_line.decode("utf-8")))
        if envelope.project != project:
            raise PermissionError("cross-project evidence found in ledger")
        results.append((line_start, envelope))
    return results


def rebuild(ledger: EvidenceLedger, path: Path) -> ProjectionCheckpoint:
    """Explicit discard-then-build as one call (Section I). `build()`
    already discards under its own lock — calling `discard()` again here
    first would just be a redundant, unlocked, wasted round trip."""
    return build(ledger, path)


def verify(ledger: EvidenceLedger, path: Path) -> ProjectionStatus:
    """Read-only health check — never mutates the projection or the ledger."""
    if not path.exists():
        return ProjectionStatus(healthy=False, reason="missing", record_count=0, checkpoint=None)
    try:
        conn = _connect(path)
    except sqlite3.DatabaseError:
        # The file exists but is not a valid SQLite database (e.g. a torn
        # write or disk-level corruption) — an explicit finding, not a crash.
        return ProjectionStatus(healthy=False, reason="corrupt", record_count=0, checkpoint=None)
    try:
        stored = _stored_checkpoint(conn)
        if stored is None:
            return ProjectionStatus(healthy=False, reason="missing_checkpoint", record_count=0, checkpoint=None)
        record_count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        checkpoint = _checkpoint_from_stored(stored)
        reason = _verify_stored_checkpoint(ledger, stored)
        if reason is not None:
            return ProjectionStatus(healthy=False, reason=reason, record_count=record_count, checkpoint=checkpoint)
        current_size = ledger.path.stat().st_size if ledger.path.exists() else 0
        if current_size > stored["ledger_byte_offset"]:
            return ProjectionStatus(healthy=False, reason="behind", record_count=record_count, checkpoint=checkpoint)
        return ProjectionStatus(healthy=True, reason=None, record_count=record_count, checkpoint=checkpoint)
    except sqlite3.DatabaseError:
        return ProjectionStatus(healthy=False, reason="corrupt", record_count=0, checkpoint=None)
    finally:
        conn.close()


def query_activity_page(
    path: Path,
    project: Identity,
    *,
    entity_kind: EntityKind,
    limit: int,
    after: tuple[datetime, str] | None,
) -> tuple[list[ProjectionRow], int, bool]:
    """One indexed page over `(observed_at, canonical_identity)` ascending,
    keyset-paginated. Returns (page_rows, total_matching, complete)."""
    conn = _connect(path)
    try:
        total_matching = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE project = ? AND entity_kind = ?",
            (project.canonical, entity_kind.value),
        ).fetchone()[0]

        where = "project = ? AND entity_kind = ?"
        params: list[Any] = [project.canonical, entity_kind.value]
        if after is not None:
            after_micros = int(after[0].astimezone(timezone.utc).timestamp() * 1_000_000)
            where += " AND (observed_at_utc_micros, canonical_identity) > (?, ?)"
            params.extend([after_micros, after[1]])
        rows = conn.execute(
            f"SELECT canonical_identity, observed_at_raw FROM observations WHERE {where} "
            "ORDER BY observed_at_utc_micros ASC, canonical_identity ASC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
    finally:
        conn.close()

    has_more = len(rows) > limit
    page = rows[:limit]
    items = [ProjectionRow(canonical_identity=row[0], observed_at_raw=row[1]) for row in page]
    return items, total_matching, not has_more


def get_observation(path: Path, project: Identity, canonical_identity: str) -> ObservationRecord | None:
    """Point lookup of one observation by its canonical identity, scoped to
    `project` — Execution 06's graph materializer uses this to confirm a
    requested Prompt Run really exists, for the right project, before
    building anything. Returns None (an explicit gap, not an error) when
    absent or when it belongs to a different project."""
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT canonical_identity, project, entity_kind, subject, observed_at_raw, provider, "
            "provider_event_id, observation_type, layer, attributes_json "
            "FROM observations WHERE canonical_identity = ? AND project = ?",
            (canonical_identity, project.canonical),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return ObservationRecord(*row)


def _open_ledger(data_dir: Path, project_key: str) -> EvidenceLedger:
    project = deterministic_identity(EntityKind.PROJECT, project_key)
    return EvidenceLedger(data_dir / "evidence.jsonl", project, PrivacyGuard(PrivacyPolicy()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuildable Performance read projection: build/update/verify/discard/rebuild.")
    parser.add_argument("command", choices=["build", "update", "verify", "discard", "rebuild"])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--project", default="midnight")
    args = parser.parse_args(argv)

    ledger = _open_ledger(args.data_dir, args.project)
    path = projection_path(args.data_dir)

    if args.command == "discard":
        discard(path)
        print(json.dumps({"discarded": True}))
        return 0
    if args.command == "verify":
        status = verify(ledger, path)
        print(json.dumps({
            "healthy": status.healthy, "reason": status.reason, "recordCount": status.record_count,
            "checkpoint": None if status.checkpoint is None else {
                "schemaVersion": status.checkpoint.schema_version, "ledgerByteOffset": status.checkpoint.ledger_byte_offset,
                "ledgerRecordCount": status.checkpoint.ledger_record_count, "generation": status.checkpoint.generation,
            },
        }))
        return 0

    action = {"build": build, "update": update, "rebuild": rebuild}[args.command]
    checkpoint = action(ledger, path)
    print(json.dumps({
        "schemaVersion": checkpoint.schema_version, "ledgerByteOffset": checkpoint.ledger_byte_offset,
        "ledgerRecordCount": checkpoint.ledger_record_count, "generation": checkpoint.generation,
    }))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
