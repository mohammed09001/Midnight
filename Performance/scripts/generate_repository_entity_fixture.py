#!/usr/bin/env python3
"""Execution 08, Visible Verification: real before/after graph documents
proving `ChangeSet -> FileChange -> CodeRegion/Symbol` depth against a real
~5-file fixture repository (a clean Python function/class, a Python file
later given a syntax error, a `.ts` file, a config file, a binary file, and
one real rename pair) — never fabricated or synthetic-flagged JSON.

Not a pytest test — a manual/CI dev tool, mirroring `generate_graph_fixtures
.py`'s own framing. Run: `python scripts/generate_repository_entity_fixture.py`

Writes two real, schema-validated documents to `--out-dir`:
  - `before.json` — today's real capability: the bare PromptRun -> ChangeSet
    depth, no `resolved_entities` supplied (zero code changed for this half).
  - `after.json`  — the same PromptRun, now with `resolved_entities` wired
    via the real `resolve_repository_entities()` — FileChange/CodeRegion/
    Symbol nodes, and the `.ts` file's honest file-level gap.

`desktop/src/App.tsx`'s `?fixtureUrl=` dev-only escape hatch renders either
document directly via the real `<PerformanceGraph>` component, since the
real Desktop Host deliberately never accepts caller-supplied structural
evidence over HTTP (see `graph_bridge.py`'s `resolved_entities` docstring).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from midnight_performance.graph_bridge import prompt_run_graph
from midnight_performance.prompt_capture import record_prompt_run
from midnight_performance.prompt_run import PromptRun
from midnight_performance.repository_capture import RepositorySnapshot, compare
from midnight_performance.repository_entity_resolution import resolve_repository_entities

PROJECT_KEY = "repository-entity-fixture-project"
REPOSITORY_KEY = "midnight"
CHANGE_SET_ID = "cs-fixture-1"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "repository-entity-fixture"

PYTHON_SOURCE_V1 = b'''def greet(name):
    return f"hello {name}"


class Greeter:
    def hello(self):
        return "hi"
'''

TYPESCRIPT_SOURCE_V1 = b"""export function add(a: number, b: number): number {
  return a + b;
}
"""

TYPESCRIPT_SOURCE_V2 = b"""export function add(a: number, b: number): number {
  return a + b + 1;
}

export function subtract(a: number, b: number): number {
  return a - b;
}
"""

PYTHON_SYNTAX_ERROR_SOURCE = b"def broken(:\n    pass\n"
CONFIG_SOURCE = b'{"name": "fixture-project", "version": "1.0.0"}\n'
BINARY_SOURCE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _write_before_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "greet.py").write_bytes(PYTHON_SOURCE_V1)
    (root / "src" / "app.ts").write_bytes(TYPESCRIPT_SOURCE_V1)
    (root / "package.json").write_bytes(CONFIG_SOURCE)
    (root / "logo.bin").write_bytes(BINARY_SOURCE)


def _write_after_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    # Same bytes as before_repo's greet.py, new path — real rename evidence
    # via SHA-256 hash correlation (design decision 1), not a guess.
    (root / "src" / "greet_renamed.py").write_bytes(PYTHON_SOURCE_V1)
    # Real content change -> a genuine CodeRegion line-hunk (TS never gets Symbol truth).
    (root / "src" / "app.ts").write_bytes(TYPESCRIPT_SOURCE_V2)
    # A newly-created Python file with a real syntax error -> an honest gap, zero fabricated symbols.
    (root / "src" / "broken.py").write_bytes(PYTHON_SYNTAX_ERROR_SOURCE)
    (root / "package.json").write_bytes(CONFIG_SOURCE)
    (root / "logo.bin").write_bytes(BINARY_SOURCE)


def _read_bytes(root: Path, path: str) -> bytes:
    return (root / path).read_bytes()


def build_fixture_document(data_dir: Path, *, with_resolved_entities: bool) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as before_dir, tempfile.TemporaryDirectory() as after_dir:
        before_root, after_root = Path(before_dir), Path(after_dir)
        _write_before_repo(before_root)
        _write_after_repo(after_root)
        # Real rename evidence: same bytes, new path — matches the real
        # SHA-256 hash-correlation `compare()` performs (design decision 1).
        before_snapshot = RepositorySnapshot.capture(before_root)
        after_snapshot = RepositorySnapshot.capture(after_root)
        evidence = compare(before_snapshot, after_snapshot)

        content_before = {path: _read_bytes(before_root, path) for path in before_snapshot.files}
        content_after = {path: _read_bytes(after_root, path) for path in after_snapshot.files}

        resolved_entities = None
        entity_labels = None
        if with_resolved_entities:
            entities, _gaps, entity_labels = resolve_repository_entities(
                repository_key=REPOSITORY_KEY, change_set_id=CHANGE_SET_ID, evidence=evidence,
                content_before=content_before, content_after=content_after,
            )
            resolved_entities = {CHANGE_SET_ID: entities}

    _, canonical = record_prompt_run(
        data_dir / "evidence.jsonl", PROJECT_KEY, "fixture-provider", "repository-entity-fixture-run",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    known = PromptRun("fixture-provider:repository-entity-fixture-run", None, change_set_ids=(CHANGE_SET_ID,), gaps=("unavailable:prompt_version",))
    return prompt_run_graph(
        data_dir, PROJECT_KEY, canonical, known_evidence=known,
        resolved_entities=resolved_entities, entity_labels=entity_labels,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    before_tmp = Path(tempfile.mkdtemp())
    try:
        before_document = build_fixture_document(before_tmp, with_resolved_entities=False)
    finally:
        shutil.rmtree(before_tmp)
    (args.out_dir / "before.json").write_text(json.dumps(before_document, indent=2, sort_keys=True))
    print(f"wrote {args.out_dir / 'before.json'} — {len(before_document['nodes'])} nodes (ChangeSet-only depth)")

    after_tmp = Path(tempfile.mkdtemp())
    try:
        after_document = build_fixture_document(after_tmp, with_resolved_entities=True)
    finally:
        shutil.rmtree(after_tmp)
    (args.out_dir / "after.json").write_text(json.dumps(after_document, indent=2, sort_keys=True))
    kinds = sorted({node["kind"] for node in after_document["nodes"]})
    print(f"wrote {args.out_dir / 'after.json'} — {len(after_document['nodes'])} nodes, kinds present: {kinds}")
    print(f"gaps: {after_document['gaps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
