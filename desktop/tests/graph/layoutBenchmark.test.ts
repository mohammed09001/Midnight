import { describe, expect, it } from "vitest";
import { layoutGraph } from "../../src/graph/layout";
import type { GraphEdge, GraphNode } from "../../src/graph/types";

/**
 * Execution 10, Section D (scale measurements) / Section H (large graph
 * benchmark). Mirrors `Performance/scripts/generate_graph_fixtures.py`'s
 * `generate_synthetic_layout_fixture` shape (same layer spread, same
 * shallow-tree edge fanout) but built in-process rather than depending on
 * that script's git-ignored, machine-local output file — this test must
 * run the same way on a fresh clone with no prior Python run.
 *
 * These numbers answer ONE question only: does `layoutGraph()` (elkjs, in
 * the main thread) stay usable as node count grows. They say nothing about
 * fetch/resolution latency (that's `generate_graph_fixtures.py`'s own,
 * separately-measured `measure_fetch_latency`) — the two are never
 * conflated. Real capture today produces far smaller graphs than any of
 * these sizes (Execution 06/10 READMEs); this exists to find the point
 * where "improve server slicing" stops being enough and "move layout to a
 * worker" or a renderer swap (Section D's escalation order) would become
 * the next lever — not to assert a specific pass/fail threshold.
 */

const LAYERS = ["prompt", "execution", "repository/change", "verification", "feedback", "outcome"];

function node(id: string, layer: string): GraphNode {
  return {
    id, kind: "tool_observation", layer, priority_tier: "on_demand", label: id, claim_kind: "derived",
    provenance: [], observed_at: null, project_context: null, externally_referenced: false, gaps: [],
    source_claim_kind: null, source_layer: null,
  };
}

function edge(source: string, target: string, index: number): GraphEdge {
  return {
    source, target, kind: "reference", claim_kind: "derived", evidence: [`synthetic-${index}`], confidence: null,
    method: "synthetic-benchmark", method_version: "1", uncertainty: "synthetic layout-timing fixture, not real evidence",
    semantic_role: "used_tool",
  };
}

function buildSyntheticGraph(nodeCount: number, edgeFanout = 2): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const root = "root";
  const nodes: GraphNode[] = [{ ...node(root, "prompt"), kind: "prompt_run", priority_tier: "primary" }];
  const edges: GraphEdge[] = [];
  const ids = [root];
  for (let i = 1; i < nodeCount; i += 1) {
    const layer = LAYERS[i % LAYERS.length];
    const nodeId = `n${i}`;
    nodes.push(node(nodeId, layer));
    for (let fanout = 0; fanout < Math.min(edgeFanout, ids.length); fanout += 1) {
      const source = ids[(i * 7 + fanout) % ids.length];
      edges.push(edge(source, nodeId, i * 10 + fanout));
    }
    ids.push(nodeId);
  }
  return { nodes, edges };
}

describe("layoutGraph scale benchmark (Execution 10, Section D)", () => {
  // Only 50/200 run as part of the regular automated suite: real
  // measurement here (Section D) found elkjs main-thread layout takes
  // ~34s at 1,000 synthetic nodes and exhausts the default Node heap
  // (OOM crash) at 5,000 — running those sizes on every `npm test` would
  // make the suite catastrophically slow/flaky, not more trustworthy.
  // The 1,000/5,000 findings are real, reproduced manually, and reported
  // in `Performance/README.md`'s Execution 10 section rather than re-run
  // here automatically.
  it.each([50, 200])("lays out a %i-node synthetic graph and completes", async (nodeCount) => {
    const { nodes, edges } = buildSyntheticGraph(nodeCount);
    const start = performance.now();
    const layout = await layoutGraph(nodes, edges);
    const elapsedMs = performance.now() - start;
    // eslint-disable-next-line no-console
    console.log(`[layout-benchmark] ${nodeCount} nodes, ${edges.length} edges: ${elapsedMs.toFixed(1)}ms`);
    expect(layout.nodes).toHaveLength(nodeCount);
  }, 15_000);
});
