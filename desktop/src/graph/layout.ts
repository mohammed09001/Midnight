import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkNode } from "elkjs/lib/elk-api";
import type { GraphEdge, GraphNode } from "./types";

/**
 * elkjs layered/Sugiyama layout, keyed off each node's backend `layer`
 * (Performance's own causal-domain grouping — `visual_intelligence.py`'s
 * `_layer()`: prompt → execution → repository/change → file → symbol →
 * verification → feedback → outcome → experiment/dataset → memory →
 * analysis). Elk's
 * partitioning feature — not automatic layer inference from edges alone —
 * is used deliberately, so the rendered layers always match the domain
 * concept the backend already assigned, even for isolated nodes with no
 * edges establishing their rank.
 *
 * Uses `elkjs/lib/elk.bundled.js` (synchronous pure-JS build, no Web Worker)
 * — offloading layout to a worker is deferred as a follow-on optimization,
 * not required for V1's bounded (≤200-node) graphs.
 */

const LAYER_ORDER: readonly string[] = [
  "prompt",
  "execution",
  "repository/change",
  "file",
  "symbol",
  "verification",
  "feedback",
  "outcome",
  "experiment/dataset",
  "memory",
  "analysis",
];

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 56;

export interface PositionedNode {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface GraphLayout {
  readonly nodes: readonly PositionedNode[];
  readonly width: number;
  readonly height: number;
}

function partitionFor(layer: string): number {
  const index = LAYER_ORDER.indexOf(layer);
  return index === -1 ? LAYER_ORDER.length : index;
}

export async function layoutGraph(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
): Promise<GraphLayout> {
  if (nodes.length === 0) return { nodes: [], width: 0, height: 0 };

  const elk = new ELK();
  const nodeIds = new Set(nodes.map((node) => node.id));
  const elkGraph: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.partitioning.activate": "true",
      "elk.spacing.nodeNode": "48",
      "elk.layered.spacing.nodeNodeBetweenLayers": "96",
    },
    children: nodes.map((node) => ({
      id: node.id,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      layoutOptions: { "elk.partitioning.partition": String(partitionFor(node.layer)) },
    })),
    // Self-edges are already impossible (`GraphEdge.__post_init__` rejects
    // them server-side); a stray edge pointing outside this bounded page
    // (e.g. beyond `maxNodes`) is dropped rather than fed to elk, which
    // requires both endpoints to be real children.
    edges: edges
      .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
      .map((edge, index) => ({ id: `e${index}`, sources: [edge.source], targets: [edge.target] })),
  };

  const result = await elk.layout(elkGraph);
  const positioned: PositionedNode[] = (result.children ?? []).map((child) => ({
    id: child.id ?? "",
    x: child.x ?? 0,
    y: child.y ?? 0,
    width: child.width ?? NODE_WIDTH,
    height: child.height ?? NODE_HEIGHT,
  }));
  return { nodes: positioned, width: result.width ?? 0, height: result.height ?? 0 };
}
