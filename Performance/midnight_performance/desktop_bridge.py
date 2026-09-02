"""Read-only Prompt Run activity bridge for Midnight Desktop.

Midnight Desktop is a consumer of Performance evidence, never a second
Performance engine.  This module is the smallest truthful read boundary that
answers one question: WHEN DID PROMPT RUNS OCCUR?

It deliberately exposes nothing else:

* no prompt content, model output, diffs, commands, transcripts, memory,
  tokens, or model details — only the Prompt Run canonical identity and its
  timezone-aware observation instant;
* reads go exclusively through :class:`performance.query_api.PerformanceQueryAPI`
  with its project authorization; the ledger is never opened outside the
  package and the bridge has no write path;
* output is a bounded, versioned JSON document on stdout, mirroring the
  repo's only cross-process convention (versioned JSON via subprocess CLI,
  as used by ``memory_bridge`` toward Memory's ``contract call``).

The existing query contract caps one page at 100 records and has no cursor,
so the bridge preserves that limit and reports ``complete: false`` whenever
the bounded page does not cover the full matching history.  Callers must
never present a partial page as complete history.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import EntityKind, Identity, deterministic_identity
from .ledger import EvidenceLedger
from .privacy import PrivacyGuard, PrivacyPolicy
from .query_api import PerformanceQueryAPI, QueryAuthorization


DESKTOP_BRIDGE_VERSION = 1
DEFAULT_PROJECT_KEY = "midnight"
DEFAULT_PAGE_LIMIT = 100


def project_identity(project_key: str) -> Identity:
    """Deterministic, replay-stable PROJECT identity for a local project key."""
    return deterministic_identity(EntityKind.PROJECT, project_key)


def open_project_ledger(ledger_path: Path, project_key: str) -> EvidenceLedger:
    """Open the local project ledger exactly as the self-hosted layout does."""
    return EvidenceLedger(ledger_path, project_identity(project_key), PrivacyGuard(PrivacyPolicy()))


def prompt_run_activity(ledger_path: Path, project_key: str, *, limit: int = DEFAULT_PAGE_LIMIT) -> dict[str, object]:
    """Return the bounded Prompt Run activity document for one project.

    The only entity kind requested is PROMPT_RUN; the query API rejects any
    cross-project authorization, so the result is project-scoped by
    construction.  A missing ledger file is an empty history, not an error.
    """
    ledger = open_project_ledger(ledger_path, project_key)
    api = PerformanceQueryAPI(ledger)
    authorization = QueryAuthorization(ledger.project)
    page = api.query_evidence(authorization, kinds=frozenset({EntityKind.PROMPT_RUN}), limit=limit)
    events = [
        {
            "promptRunId": envelope.observation.identity.canonical,
            "occurredAt": envelope.observation.observed_at.isoformat(),
        }
        for envelope in page.items
    ]
    return {
        "version": DESKTOP_BRIDGE_VERSION,
        "project": page.project.canonical,
        "events": events,
        "totalMatching": page.total_matching,
        "limit": page.limit,
        "complete": len(events) >= page.total_matching,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Prompt Run activity document for Midnight Desktop (stdout JSON).",
    )
    parser.add_argument("--data-dir", type=Path, required=True, help="project ledger directory containing evidence.jsonl")
    parser.add_argument("--project", default=DEFAULT_PROJECT_KEY, help="local project key (deterministic identity input)")
    parser.add_argument("--limit", type=int, default=DEFAULT_PAGE_LIMIT, help="maximum Prompt Runs to return (query API caps at 100)")
    args = parser.parse_args(argv)
    document = prompt_run_activity(args.data_dir / "evidence.jsonl", args.project, limit=args.limit)
    json.dump(document, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
