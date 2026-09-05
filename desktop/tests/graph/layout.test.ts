import { describe, expect, it } from "vitest";
import { layoutGraph } from "../../src/graph/layout";
import type { GraphEdge, GraphNode } from "../../src/graph/types";

function node(id: string, layer: string): GraphNode {
  return {
    id, kind: "prompt_run", layer, priority_tier: "primary", label: id, claim_kind: "derived", provenance: [], observed_at: null,
    project_context: null, externally_referenced: false, gaps: [], source_claim_kind: null, source_layer: null,
  };
}

function edge(source: string, target: string): GraphEdge {
  return {
    source, target, kind: "reference", claim_kind: "derived", evidence: [], confidence: null,
    method: "relationship-graph", method_version: "1", uncertainty: "direct reification", semantic_role: "executed_by",
  };
}

describe("layoutGraph", () => {
  it("returns no positions for an empty graph", async () => {
    const layout = await layoutGraph([], []);
    expect(layout.nodes).toEqual([]);
  });

  it("positions an isolated node with zero edges (the isolated-root case)", async () => {
    const layout = await layoutGraph([node("root", "prompt")], []);
    expect(layout.nodes).toHaveLength(1);
    expect(layout.nodes[0].id).toBe("root");
    expect(Number.isFinite(layout.nodes[0].x)).toBe(true);
    expect(Number.isFinite(layout.nodes[0].y)).toBe(true);
  });

  it("places nodes from an earlier backend layer above nodes from a later one", async () => {
    const layout = await layoutGraph(
      [node("root", "prompt"), node("agent", "execution"), node("verification", "verification")],
      [edge("root", "agent"), edge("root", "verification")],
    );
    const byId = new Map(layout.nodes.map((n) => [n.id, n]));
    expect(byId.get("root")!.y).toBeLessThan(byId.get("agent")!.y);
    expect(byId.get("agent")!.y).toBeLessThan(byId.get("verification")!.y);
  });

  it("drops edges whose endpoints fall outside the supplied node set (a truncated page)", async () => {
    const layout = await layoutGraph([node("root", "prompt")], [edge("root", "not-in-this-page")]);
    expect(layout.nodes).toHaveLength(1);
  });
});
