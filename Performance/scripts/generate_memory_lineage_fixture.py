#!/usr/bin/env python3
"""Execution 09, Visible Verification: a real, schema-validated graph
fixture with one pinned Memory citation node, for `desktop/src/App.tsx`'s
`?fixtureUrl=` dev escape hatch (same precedent as
`generate_repository_entity_fixture.py`: a real `prompt_run_graph()` call,
never hand-built JSON).

The cited record id below is deliberately a placeholder that does not exist
in any real Memory store — opening the fixture and clicking "Refresh current
state" therefore demonstrates the truthful degraded mode (Section E: Memory
reachable, record not found in the bounded read window) out of the box, with
no setup required. To see the LIVE pinned-vs-current distinction instead,
seed a real record for this project's Memory scope first:

    python -c "from midnight_performance import EntityKind, deterministic_identity, project_key_for_identity; \\
        print(project_key_for_identity(deterministic_identity(EntityKind.PROJECT, 'midnight')))"
    # then, from Memory/:
    node --experimental-strip-types src/cli/cli.ts scope create --key <printed key> --name Demo
    node --experimental-strip-types src/cli/cli.ts record add --scope <printed key> \\
        --subject demo --content "..." --evidence external:demo-1 --source-kind user_note
    # then rerun this script with --record-id <the returned recordId>

Not a pytest test — a manual/CI dev tool. Run:
`python scripts/generate_memory_lineage_fixture.py`
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from midnight_performance.contracts import ExternalReference
from midnight_performance.graph_bridge import prompt_run_graph
from midnight_performance.prompt_capture import record_prompt_run

PROJECT_KEY = "midnight"
DEFAULT_RECORD_ID = "mem_00000000000000000000000000"
DEFAULT_OUT_PATH = Path(__file__).resolve().parent.parent.parent / "desktop" / "public" / "fixtures" / "memory-lineage-demo.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record-id", default=DEFAULT_RECORD_ID, help="a real or placeholder Memory recordId")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--out-path", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args(argv)

    data_dir = Path(tempfile.mkdtemp())
    _, canonical = record_prompt_run(
        data_dir / "evidence.jsonl", PROJECT_KEY, "demo-provider", "memory-lineage-demo-1",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    citation = ExternalReference(provider="memory", kind="record", value=f"{args.record_id}#rev{args.revision}")
    document = prompt_run_graph(data_dir, PROJECT_KEY, canonical, memory_references=(citation,))

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    args.out_path.write_text(json.dumps(document, indent=2, sort_keys=True))
    print(f"wrote {args.out_path}")
    print(f"memoryLineage: {document['memoryLineage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
