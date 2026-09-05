"""Read-only Prompt Run activity bridge for Midnight Desktop.

Midnight Desktop is a consumer of Performance evidence, never a second
Performance engine.  This module is the smallest truthful read boundary that
answers one question: WHEN DID PROMPT RUNS OCCUR?

It deliberately exposes nothing else:

* no prompt content, model output, diffs, commands, transcripts, memory,
  tokens, or model details — only the Prompt Run canonical identity and its
  timezone-aware observation instant;
* the ledger is opened bound to exactly one project identity and never
  opened outside this package; the bridge has no write path;
* output is a bounded, versioned JSON document on stdout, mirroring the
  repo's only cross-process convention (versioned JSON via subprocess CLI,
  as used by ``memory_bridge`` toward Memory's ``contract call``), and is
  self-validated against ``schemas/activity-response.schema.json`` before it
  is ever printed.

Execution 03 note — why this reads through the projection rather than
``PerformanceQueryAPI.query_evidence``: that facade always slices
``matching[:limit]`` from index 0, so it has no way to reach a second page
of >100 matching Prompt Runs; extending its shared, multi-consumer contract
(it also backs the generic MCP-shaped read surface in ``read_tools.py``) is
out of proportion to this bridge's narrow scope. ``_MAX_LIMIT`` in
``query_api.py`` is untouched.

Execution 05 note — the O(n) full-ledger replay this function used to do on
every call (measured at ~3.9s at 100,000 observations) is now backed by
``projection_store``'s indexed, rebuildable, disposable read projection
(see that module's docstring and ``Performance/README.md``). The ledger
remains the sole canonical authority; the projection is verified/caught up
via an O(1) checkpoint check on every call before the indexed query runs,
so a stale or corrupt projection is never silently trusted — see
``projection_store.update``. Project scoping is enforced the same way it
always was: by ``EvidenceLedger`` construction and its fail-closed
``replay()`` (used to build/rebuild the projection), not by
``PerformanceQueryAPI._authorize``.

The existing per-page cap remains 100 records; pagination beyond that is a
narrowly-scoped, project-bound, opaque keyset cursor (see ``encode_cursor``/
``decode_cursor``) — never an unbounded offset, and unchanged since
Execution 03. Callers must never present a partial page as complete history
(``complete`` is always accurate).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from datetime import datetime
from pathlib import Path

from . import projection_store
from .contract_schema import validate_activity_response
from .contracts import EntityKind, Identity, deterministic_identity
from .ledger import EvidenceLedger
from .privacy import PrivacyGuard, PrivacyPolicy


DESKTOP_BRIDGE_VERSION = 1
DEFAULT_PROJECT_KEY = "midnight"
DEFAULT_PAGE_LIMIT = 100
CURSOR_FORMAT_VERSION = 1


class InvalidCursorError(ValueError):
    """Raised when a continuation cursor is malformed, garbled, or foreign."""


def project_identity(project_key: str) -> Identity:
    """Deterministic, replay-stable PROJECT identity for a local project key."""
    return deterministic_identity(EntityKind.PROJECT, project_key)


def open_project_ledger(ledger_path: Path, project_key: str) -> EvidenceLedger:
    """Open the local project ledger exactly as the self-hosted layout does."""
    return EvidenceLedger(ledger_path, project_identity(project_key), PrivacyGuard(PrivacyPolicy()))


def encode_cursor(observed_at: datetime, prompt_run_id: str, project: Identity) -> str:
    """Encode an opaque, versioned, project-bound keyset continuation token."""
    payload = json.dumps(
        [CURSOR_FORMAT_VERSION, observed_at.isoformat(), prompt_run_id, project.canonical],
        separators=(",", ":"),
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def decode_cursor(token: str, project: Identity) -> tuple[datetime, str]:
    """Decode and validate a continuation cursor against the bound project.

    A cursor minted for a different project fails closed here rather than
    silently returning a confusing (if harmless) result — reinforcing project
    isolation even at the pagination-token level.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or len(parsed) != 4:
            raise ValueError("cursor payload must be a 4-element array")
        format_version, observed_at_raw, prompt_run_id, project_canonical = parsed
        if format_version != CURSOR_FORMAT_VERSION:
            raise ValueError(f"unsupported cursor format version: {format_version!r}")
        if not isinstance(prompt_run_id, str) or not prompt_run_id.strip():
            raise ValueError("cursor prompt run id must be a non-empty string")
        if project_canonical != project.canonical:
            raise ValueError("cursor was minted for a different project")
        observed_at = datetime.fromisoformat(str(observed_at_raw))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise InvalidCursorError(f"invalid continuation cursor: {exc}") from exc
    return observed_at, prompt_run_id


def prompt_run_activity(
    ledger_path: Path,
    project_key: str,
    *,
    limit: int = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> dict[str, object]:
    """Return one bounded, deterministically-ordered page of Prompt Run activity.

    A missing ledger file is an empty history, not an error. Ordering is
    always ``(observed_at, promptRunId)`` ascending, independent of ledger
    append order, so continuation via ``cursor``/``nextCursor`` is stable
    even if evidence is ever appended out of chronological order.
    """
    if not 1 <= limit <= DEFAULT_PAGE_LIMIT:
        raise ValueError(f"limit must be between 1 and {DEFAULT_PAGE_LIMIT}")

    ledger = open_project_ledger(ledger_path, project_key)
    path = projection_store.projection_path(ledger_path.parent)
    # O(1) checkpoint verify-then-catch-up on every call; falls back to a
    # full, authoritative rebuild (via the real, untouched ledger.replay())
    # on any mismatch, so corruption always raises the same ValueError this
    # function has always raised — never a bespoke error from the fast path.
    checkpoint = projection_store.update(ledger, path)

    after = decode_cursor(cursor, ledger.project) if cursor is not None else None
    rows, total_matching, complete = projection_store.query_activity_page(
        path, ledger.project, entity_kind=EntityKind.PROMPT_RUN, limit=limit, after=after,
    )

    events = [{"promptRunId": row.canonical_identity, "occurredAt": row.observed_at_raw} for row in rows]
    next_cursor = None
    if not complete and rows:
        last = rows[-1]
        next_cursor = encode_cursor(datetime.fromisoformat(last.observed_at_raw), last.canonical_identity, ledger.project)

    document = {
        "version": DESKTOP_BRIDGE_VERSION,
        "project": ledger.project.canonical,
        "events": events,
        "totalMatching": total_matching,
        "limit": limit,
        "complete": complete,
        "cursor": cursor,
        "nextCursor": next_cursor,
        "checkpoint": {
            "schemaVersion": checkpoint.schema_version,
            "ledgerByteOffset": checkpoint.ledger_byte_offset,
            "ledgerRecordCount": checkpoint.ledger_record_count,
            "generation": checkpoint.generation,
        },
    }
    validate_activity_response(document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Prompt Run activity document for Midnight Desktop (stdout JSON).",
    )
    parser.add_argument("--data-dir", type=Path, required=True, help="project ledger directory containing evidence.jsonl")
    parser.add_argument("--project", default=DEFAULT_PROJECT_KEY, help="local project key (deterministic identity input)")
    parser.add_argument("--limit", type=int, default=DEFAULT_PAGE_LIMIT, help="maximum Prompt Runs to return (capped at 100)")
    parser.add_argument("--cursor", default=None, help="opaque continuation cursor from a prior page's nextCursor")
    args = parser.parse_args(argv)
    document = prompt_run_activity(args.data_dir / "evidence.jsonl", args.project, limit=args.limit, cursor=args.cursor)
    json.dump(document, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
