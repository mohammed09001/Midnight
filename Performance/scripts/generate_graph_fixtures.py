#!/usr/bin/env python3
"""Execution 07, Section G: fixtures and timing for two DISTINCT
performance questions the graph feature raises — never conflated with each
other, and never presented as more than what each actually is.

1. FETCH/RESOLUTION LATENCY at growing REAL ledger sizes: seeds N genuine
   PROMPT_RUN occurrences (the same real evidence shape `record_prompt_run`
   writes) via `benchmark_evidence_reads.py`'s own direct-seed methodology
   (bypassing the append path's O(n) duplicate check, which is prohibitive
   at these sizes — that cost is Execution 05's own separately-documented,
   deliberately-unfixed finding, not something this script re-measures),
   then times `graph_bridge.py`'s REAL CLI resolving one Prompt Run's graph
   — the same subprocess the Desktop Host itself spawns. Proves Execution
   05's O(1) projection lookup keeps `graph.getPromptRun` fast as ledger
   history grows, the same shape of claim Execution 05 already established
   for `activity.listPromptRuns`.

2. LAYOUT TIMING at growing graph sizes: today's real capture pipeline
   writes only bare PROMPT_RUN occurrences (Executions 04-06's documented,
   still-current scope) — no real Prompt Run can produce a graph with more
   than its own isolated root node through genuine evidence. A synthetic
   multi-node/edge fixture is written instead, schema-shaped identically to
   a real `graph-prompt-run-response.schema.json` document but permanently
   marked `"synthetic": true` (a key no real bridge response ever sets) —
   for the Desktop frontend's own `layoutGraph()` (elkjs) to time directly,
   never claimed as observed evidence.

Not a pytest test — a manual/CI dev tool, mirroring
`benchmark_evidence_reads.py`'s own framing. Run:
`python scripts/generate_graph_fixtures.py`
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from midnight_performance.contracts import ClaimKind, EntityKind, Observation, deterministic_identity
from midnight_performance.observation_model import EvidenceSourceKind, ObservationEnvelope, ObservationLayer, ObservationType
from midnight_performance.privacy import PrivacyGuard, PrivacyPolicy
from midnight_performance.prompt_capture import record_prompt_run

PROJECT_KEY = "graph-fixture-project"
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
DEFAULT_LEDGER_SIZES = (10, 1_000, 10_000)
# Execution 10, Section D: 50/200/1,000/5,000 -- the exact scale points that
# execution's measurement requirement names. 200 == graph_bridge.py's
# DEFAULT_MAX_NODES; 1,000/5,000 exist to find out whether server-side
# slicing (already the default) is enough, or whether layout itself needs
# further work (worker offload, or a renderer swap) before the product ever
# shows that many nodes at once — which today's default it deliberately
# never does (Section D: "the product does not need to show 5,000 by
# default").
DEFAULT_GRAPH_SIZES = (50, 200, 1_000, 5_000)
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "graph-fixtures"

# The one Prompt Run every ledger size below always contains, at a fixed,
# reproducible identity — so the SAME resolution is timed at every size,
# isolating "does history size matter" from "which record was picked."
TARGET_STABLE_KEY = "fixture-provider:target-run"


def _seed_ledger_direct(ledger_path: Path, count: int) -> str:
    """Writes `count` real-shaped PROMPT_RUN occurrences directly to the
    ledger file (bypassing `EvidenceLedger.append`'s own O(n) duplicate
    check — see module docstring), including the one fixed TARGET run every
    size is resolved against. Returns the target's canonical identity."""
    project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
    guard = PrivacyGuard(PrivacyPolicy())
    lines: list[str] = []
    target_canonical = ""
    stable_keys = [TARGET_STABLE_KEY] + [f"fixture-provider:evt-{i}" for i in range(count - 1)]
    for i, stable_key in enumerate(stable_keys):
        identity = deterministic_identity(EntityKind.PROMPT_RUN, stable_key)
        if stable_key == TARGET_STABLE_KEY:
            target_canonical = identity.canonical
        observation = Observation(
            identity=identity, claim_kind=ClaimKind.OBSERVED,
            subject=deterministic_identity(EntityKind.PROMPT_VERSION, stable_key),
            payload={}, observed_at=BASE + timedelta(seconds=i), source="fixture-provider",
        )
        envelope = ObservationEnvelope(
            observation=observation, project=project, observation_type=ObservationType.PROMPT,
            layer=ObservationLayer.NORMALIZED, provider="fixture-provider", provider_event_id=stable_key.split(":", 1)[1],
            source_kind=EvidenceSourceKind.PROVIDER_HOOK, attributes={"occurrence_only": True},
        )
        protected = replace(envelope, observation=guard.protect(envelope.observation))
        lines.append(json.dumps(protected.to_dict(), sort_keys=True, default=str))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target_canonical


def measure_fetch_latency(sizes: tuple[int, ...] = DEFAULT_LEDGER_SIZES) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for size in sorted(sizes):
        tmp = Path(tempfile.mkdtemp())
        try:
            data_dir = tmp
            canonical = _seed_ledger_direct(data_dir / "evidence.jsonl", size)
            start = time.perf_counter()
            completed = subprocess.run(
                [sys.executable, "-m", "midnight_performance.graph_bridge",
                 "--data-dir", str(data_dir), "--project", PROJECT_KEY, "--prompt-run-id", canonical],
                capture_output=True, text=True, timeout=120,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            if completed.returncode != 0:
                raise RuntimeError(f"graph_bridge CLI failed at ledger size {size}: {completed.stderr}")
            results.append({"ledgerSize": size, "elapsedMs": round(elapsed_ms, 2)})
        finally:
            shutil.rmtree(tmp)
    return results


def generate_synthetic_layout_fixture(node_count: int, *, edge_fanout: int = 2) -> dict[str, object]:
    """A synthetic, schema-shaped graph document for `layoutGraph()` timing
    ONLY (see module docstring). Nodes are spread across the real backend
    layer vocabulary (`visual_intelligence._layer`) so layout exercises
    real partitioning; edges form a shallow tree (each later node points
    back to one of finitely many earlier ones), never a self-edge —
    matching `GraphEdge.__post_init__`'s real invariant."""
    layers = ["prompt", "execution", "repository/change", "verification", "feedback", "outcome"]
    root = deterministic_identity(EntityKind.PROMPT_RUN, "synthetic-fixture-root").canonical
    nodes: list[dict[str, object]] = [{
        "id": root, "kind": "prompt_run", "layer": "prompt", "priority_tier": "primary", "label": "Synthetic Root",
        "claim_kind": "derived", "provenance": [], "observed_at": None, "project_context": None,
        "externally_referenced": False, "gaps": [], "source_claim_kind": None, "source_layer": None,
    }]
    edges: list[dict[str, object]] = []
    ids = [root]
    for i in range(1, node_count):
        layer = layers[i % len(layers)]
        node_id = deterministic_identity(EntityKind.TOOL_OBSERVATION, f"synthetic-fixture-node-{i}").canonical
        nodes.append({
            "id": node_id, "kind": "tool_observation", "layer": layer, "priority_tier": "on_demand", "label": f"Synthetic Node {i}",
            "claim_kind": "derived", "provenance": [], "observed_at": None, "project_context": None,
            "externally_referenced": False, "gaps": [], "source_claim_kind": None, "source_layer": None,
        })
        for fanout in range(min(edge_fanout, len(ids))):
            source = ids[(i * 7 + fanout) % len(ids)]
            edges.append({
                "source": source, "target": node_id, "kind": "reference", "claim_kind": "derived",
                "evidence": [f"synthetic-{i}-{fanout}"], "confidence": None, "method": "synthetic-fixture",
                "method_version": "1", "uncertainty": "synthetic layout-timing fixture, not real evidence",
                "semantic_role": "used_tool",
            })
        ids.append(node_id)
    return {
        "version": 1, "synthetic": True,
        "project": deterministic_identity(EntityKind.PROJECT, PROJECT_KEY).canonical,
        "root": root, "nodes": nodes, "edges": edges, "citations": [], "memoryLineage": [], "gaps": [],
        "truncated": False, "truncationReasons": [], "cursor": None, "nextCursor": None,
        "bounds": {"maxDepth": None, "maxNodes": node_count, "maxEdges": len(edges), "allowedLayers": None, "focusNode": None},
        "projectionIdentity": {
            "project": deterministic_identity(EntityKind.PROJECT, PROJECT_KEY).canonical, "root": root,
            "graphSchemaVersion": 1, "graphAlgorithmMethod": "synthetic-fixture", "graphAlgorithmVersion": "1",
            "evidenceCheckpoint": f"synthetic-{node_count}",
        },
        "integrity": {"qualifies": True, "findings": []},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ledger-sizes", type=int, nargs="+", default=list(DEFAULT_LEDGER_SIZES))
    parser.add_argument("--graph-sizes", type=int, nargs="+", default=list(DEFAULT_GRAPH_SIZES))
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("Fetch/resolution latency - real graph_bridge.py CLI, real ledger, growing size:")
    print(f"{'ledger size':>12} | {'elapsed(ms)':>11}")
    fetch_results = measure_fetch_latency(tuple(args.ledger_sizes))
    for row in fetch_results:
        print(f"{row['ledgerSize']:>12} | {row['elapsedMs']:>11.2f}")
    (args.out_dir / "fetch-latency.json").write_text(json.dumps(fetch_results, indent=2))

    print("\nWriting synthetic layout-timing fixtures (never real evidence)...")
    for size in args.graph_sizes:
        fixture = generate_synthetic_layout_fixture(size)
        path = args.out_dir / f"layout-fixture-{size}-nodes.json"
        path.write_text(json.dumps(fixture, indent=2))
        print(f"  wrote {path.name} ({size} nodes, {len(fixture['edges'])} edges)")

    print(f"\nFixtures written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
