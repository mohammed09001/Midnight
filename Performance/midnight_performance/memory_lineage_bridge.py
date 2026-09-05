"""Execution 09, Section C: `graph.refreshMemoryCitation` — the read-only
Desktop bridge that produces a NEW `MemoryCitationState` projection for one
already-cited Memory reference, entirely independent of any previously built
`PerformanceGraph` document. Mirrors `graph_bridge.py`'s pattern exactly: a
pure function, project-scoped, self-validated JSON on stdout, no write path.

This module never proposes, promotes, revises, or otherwise mutates
anything in Memory — it only ever reaches Memory through
`memory_temporal_lineage.refresh_state`, which itself only ever calls the
existing read-only `memory.context` operation. It does not touch
Performance's own evidence ledger/projection store at all (no `--data-dir`):
refreshing a Memory citation's current state has nothing to do with
Performance's own evidence, by design (Section A's boundary).
"""

from __future__ import annotations

import argparse
import json
import sys

from .contract_schema import validate_memory_citation_refresh_response
from .contracts import EntityKind, ExternalReference, deterministic_identity
from .memory_bridge import MalformedMemoryRecordError, project_key_for_identity
from .memory_temporal_lineage import MEMORY_LINEAGE_VERSION, pinned_state, refresh_state

MEMORY_LINEAGE_BRIDGE_VERSION = MEMORY_LINEAGE_VERSION

# stdout stays reserved exclusively for the schema-validated success
# document (mirroring every other bridge in this package); a bad request
# is reported as JSON on stderr with a distinct exit code instead.
EXIT_INVALID_REQUEST = 4


def refresh_memory_citation(
    project_key: str,
    reference: ExternalReference,
    *,
    memory_repo_path: str,
    store_path: str | None = None,
    node_executable: str = "node",
    timeout_seconds: float = 8.0,
    size: int = 100,
) -> dict:
    """`project_key` is the Performance LOCAL project key (mirrors every
    other bridge's `--project` convention, e.g. `graph_bridge.py`) — mapped
    to a Memory scope key here via the existing identity-mapping bridge
    (`project_key_for_identity`), never passed through raw."""
    project = deterministic_identity(EntityKind.PROJECT, project_key)
    memory_scope_key = project_key_for_identity(project)
    pinned = pinned_state(reference)
    state = refresh_state(
        pinned,
        memory_scope_key,
        size=size,
        memory_repo_path=memory_repo_path,
        store_path=store_path,
        node_executable=node_executable,
        timeout_seconds=timeout_seconds,
    )
    document = {
        "version": MEMORY_LINEAGE_BRIDGE_VERSION,
        "project": project.canonical,
        "reference": {"provider": reference.provider, "kind": reference.kind, "value": reference.value},
        "state": state.to_record(),
    }
    validate_memory_citation_refresh_response(document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only refresh of one Memory citation's current state (stdout JSON).",
    )
    parser.add_argument("--project", required=True, help="local project key (deterministic identity input)")
    parser.add_argument("--reference-provider", default="memory")
    parser.add_argument("--reference-kind", default="record")
    parser.add_argument("--reference-value", required=True, help="the pinned '<recordId>#rev<revision>' citation value")
    parser.add_argument("--memory-repo-path", required=True)
    parser.add_argument("--store-path", default=None)
    parser.add_argument("--node-executable", default="node")
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    args = parser.parse_args(argv)
    try:
        reference = ExternalReference(
            provider=args.reference_provider, kind=args.reference_kind, value=args.reference_value
        )
        document = refresh_memory_citation(
            args.project,
            reference,
            memory_repo_path=args.memory_repo_path,
            store_path=args.store_path,
            node_executable=args.node_executable,
            timeout_seconds=args.timeout_seconds,
        )
    except (ValueError, MalformedMemoryRecordError) as exc:
        json.dump({"error": "invalid_request", "message": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return EXIT_INVALID_REQUEST
    json.dump(document, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
