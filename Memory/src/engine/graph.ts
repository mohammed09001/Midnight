/**
 * Optional relationship-graph projection (Task 24).
 *
 * Projects Memory relationships into a GRAPH for traversal/history
 * experiments WITHOUT making a graph database canonical. The graph is a
 * DERIVED, REBUILDABLE projection computed from canonical records (typed
 * relations with provenance, supersession chains, contradiction groups,
 * entity/external references) — never canonical truth (docs/BOUNDARY.md).
 *
 * - Nodes: records, entities (`entity:<kind>:<name>`, Task 22), and external
 *   references (`engine:<name>:<ref>`, by reference only).
 * - Edges: every typed relation hint (with provenance), supersession links
 *   (`supersedes` / `superseded_by`), and contradiction-group membership
 *   (`contradicts`).
 * - Versioned + rebuildable: recomputed on demand; `rebuildGraphProjection`
 *   forces a fresh build and emits `memory.graph.projection.rebuilt`.
 * - Traversal: bounded BFS from a node with direction/relation-type/depth
 *   filters — the surface for traversal and history (supersession-chain)
 *   experiments.
 *
 * Research: getzep/graphiti's "graph as a rebuildable projection over
 * temporal facts" intent is ADAPTED (main @ 2026-08-30); the graph database /
 * LLM-extraction dependency is REJECTED — Library's graph is a deterministic,
 * self-hosted projection over its own canonical relationships.
 */
import { NotFoundError, ValidationError } from "../contracts/errors.ts";
import type { RelationProvenance } from "../contracts/types.ts";
import { getScopeImpl } from "./scopes.ts";
import { parseEntityTarget } from "./entities.ts";
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import type { MemoryStore } from "./store.ts";

export interface GraphNode {
  /** Canonical node id: record id, `entity:<kind>:<name>`, or `engine:<name>:<ref>`. */
  id: string;
  kind: "record" | "entity" | "external";
  /** Record subject / entity name / external ref. */
  label: string;
  recordId?: string;
  /** Canonical entity key, e.g. "component:api-gateway" (entity nodes). */
  entity?: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  /** Relation type, or "supersedes" / "superseded_by" / "contradicts". */
  type: string;
  /** Source record that declared the edge (typed relations / supersession). */
  recordId?: string;
  provenance?: RelationProvenance;
}

export interface GraphProjection {
  scopeId: string;
  /** Contract version + build counter + build time (fresh per rebuild). */
  version: string;
  schemaVersion: "1";
  builtAt: string;
  nodeCount: number;
  edgeCount: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/** Monotonic in-process build counter (fresh version even within one millisecond). */
let graphBuildCounter = 0;

function resolveNodeTarget(
  nodes: Map<string, GraphNode>,
  target: string,
): string {
  if (target.startsWith("entity:")) {
    const parsed = parseEntityTarget(target);
    if (parsed === null) return target;
    const id = `entity:${parsed.kind}:${parsed.name}`;
    if (!nodes.has(id)) {
      nodes.set(id, { id, kind: "entity", label: parsed.name, entity: `${parsed.kind}:${parsed.name}` });
    }
    return id;
  }
  if (target.startsWith("engine:")) {
    if (!nodes.has(target)) {
      nodes.set(target, { id: target, kind: "external", label: target.slice("engine:".length) });
    }
    return target;
  }
  if (target.startsWith("mem_")) {
    // Record targets must exist in the scope (validated at relation time).
    if (!nodes.has(target)) {
      nodes.set(target, { id: target, kind: "record", label: target });
    }
    return target;
  }
  // Unknown target format: keep as an opaque external-style node for safety.
  if (!nodes.has(target)) {
    nodes.set(target, { id: target, kind: "external", label: target });
  }
  return target;
}

/**
 * Build the derived relationship-graph projection for a scope. Pure function
 * over the canonical store — never writes canonical state.
 */
export function graphProjectionImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
): GraphProjection {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const db = store.ensureOpen();
  const builtAt = new Date().toISOString();

  const records = db
    .prepare(
      `SELECT record_id, subject, relation_hints_json, supersedes_id, superseded_by_id
       FROM memory_records WHERE scope_id = ? AND status != 'deleted'`,
    )
    .all(scope.scopeId) as Array<Record<string, unknown>>;

  const nodes = new Map<string, GraphNode>();
  for (const row of records) {
    const id = String(row["record_id"]);
    nodes.set(id, { id, kind: "record", label: String(row["subject"]), recordId: id });
  }

  const edges: GraphEdge[] = [];
  const seenEdges = new Set<string>();
  const addEdge = (from: string, to: string, type: string, recordId?: string, provenance?: RelationProvenance): void => {
    const key = `${from}|${type}|${to}`;
    if (seenEdges.has(key)) return;
    seenEdges.add(key);
    edges.push({ from, to, type, ...(recordId !== undefined ? { recordId } : {}), ...(provenance !== undefined ? { provenance } : {}) });
  };

  for (const row of records) {
    const recordId = String(row["record_id"]);
    const hints = JSON.parse(String(row["relation_hints_json"])) as Array<{ type: string; target: string; provenance?: RelationProvenance }>;
    for (const hint of hints) {
      const to = resolveNodeTarget(nodes, hint.target);
      addEdge(recordId, to, hint.type, recordId, hint.provenance);
    }
    if (row["supersedes_id"] !== null && row["supersedes_id"] !== undefined) {
      const pred = String(row["supersedes_id"]);
      resolveNodeTarget(nodes, pred);
      addEdge(recordId, pred, "supersedes", recordId);
    }
    if (row["superseded_by_id"] !== null && row["superseded_by_id"] !== undefined) {
      const succ = String(row["superseded_by_id"]);
      resolveNodeTarget(nodes, succ);
      addEdge(recordId, succ, "superseded_by", recordId);
    }
  }

  // Contradiction-group membership → pairwise "contradicts" edges.
  const groups = db
    .prepare("SELECT record_ids FROM contradiction_groups WHERE scope_id = ?")
    .all(scope.scopeId) as Array<Record<string, unknown>>;
  for (const group of groups) {
    const members = JSON.parse(String(group["record_ids"])) as string[];
    for (let i = 0; i < members.length; i++) {
      for (let j = i + 1; j < members.length; j++) {
        addEdge(members[i]!, members[j]!, "contradicts");
      }
    }
  }

  const nodeList = [...nodes.values()].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return {
    scopeId: scope.scopeId,
    version: `${MEMORY_ENGINE_CONTRACT_VERSION}.p${++graphBuildCounter}@${builtAt}`,
    schemaVersion: "1",
    builtAt,
    nodeCount: nodeList.length,
    edgeCount: edges.length,
    nodes: nodeList,
    edges,
  };
}

/** Force a fresh build of the graph projection (observability/recovery path). */
export function rebuildGraphProjectionImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
): GraphProjection {
  const projection = graphProjectionImpl(store, scopeOrProjectKey);
  store.appendEvent("memory.graph.projection.rebuilt", {
    scopeId: projection.scopeId,
    version: projection.version,
  });
  return projection;
}

// ---- traversal ---------------------------------------------------------------

export interface TraversalOptions {
  direction?: "out" | "in" | "both";
  /** Restrict traversal to these edge types (e.g. ["supersedes", "superseded_by"] for history). */
  relationTypes?: string[];
  maxDepth?: number;
}

export interface TraversalNode {
  id: string;
  label: string;
  kind: GraphNode["kind"];
  depth: number;
}

export interface GraphTraversal {
  start: string;
  direction: "out" | "in" | "both";
  relationTypes: string[] | null;
  maxDepth: number;
  nodes: TraversalNode[];
  /** The edges actually traversed (deduplicated). */
  edges: GraphEdge[];
  /** True when the depth bound cut off reachable nodes. */
  truncated: boolean;
}

/**
 * Bounded breadth-first traversal of the graph projection starting from a
 * node id. Supports direction, edge-type filtering, and a depth cap — the
 * surface for relationship traversal and supersession-history experiments.
 */
export function traverseGraphImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  start: string,
  options: TraversalOptions = {},
): GraphTraversal {
  if (typeof start !== "string" || start.trim().length === 0) {
    throw new ValidationError("start must be a non-empty node id");
  }
  const projection = graphProjectionImpl(store, scopeOrProjectKey);
  if (!projection.nodes.some((n) => n.id === start)) {
    throw new NotFoundError(`graph node '${start}' not found in scope '${scopeOrProjectKey}'`);
  }

  const direction = options.direction ?? "both";
  const relationTypes = options.relationTypes !== undefined && options.relationTypes.length > 0
    ? options.relationTypes
    : null;
  const maxDepth = Math.min(Math.max(options.maxDepth ?? 3, 1), 20);

  const outAdj = new Map<string, GraphEdge[]>();
  const inAdj = new Map<string, GraphEdge[]>();
  for (const edge of projection.edges) {
    if (relationTypes !== null && !relationTypes.includes(edge.type)) continue;
    (outAdj.get(edge.from) ?? outAdj.set(edge.from, []).get(edge.from)!).push(edge);
    (inAdj.get(edge.to) ?? inAdj.set(edge.to, []).get(edge.to)!).push(edge);
  }

  const nodeById = new Map(projection.nodes.map((n) => [n.id, n]));
  const neighbors = (id: string): Array<{ edge: GraphEdge; neighborId: string }> => {
    const result: Array<{ edge: GraphEdge; neighborId: string }> = [];
    if (direction === "out" || direction === "both") {
      for (const e of outAdj.get(id) ?? []) result.push({ edge: e, neighborId: e.to });
    }
    if (direction === "in" || direction === "both") {
      for (const e of inAdj.get(id) ?? []) result.push({ edge: e, neighborId: e.from });
    }
    return result;
  };

  const visited = new Map<string, number>([[start, 0]]);
  const queue: Array<{ id: string; depth: number }> = [{ id: start, depth: 0 }];
  const seenEdges = new Set<string>();
  const traversedEdges: GraphEdge[] = [];
  let truncated = false;

  while (queue.length > 0) {
    const { id, depth } = queue.shift()!;
    const next = neighbors(id);
    if (depth >= maxDepth) {
      if (next.length > 0) truncated = true;
      continue;
    }
    for (const { edge, neighborId } of next) {
      const key = `${edge.from}|${edge.type}|${edge.to}`;
      if (!seenEdges.has(key)) {
        seenEdges.add(key);
        traversedEdges.push(edge);
      }
      if (!visited.has(neighborId)) {
        visited.set(neighborId, depth + 1);
        queue.push({ id: neighborId, depth: depth + 1 });
      }
    }
  }

  const nodes: TraversalNode[] = [...visited.entries()]
    .sort((a, b) => a[1] - b[1] || (a[0] < b[0] ? -1 : 1))
    .map(([id, depth]) => {
      const node = nodeById.get(id)!;
      return { id, label: node.label, kind: node.kind, depth };
    });

  return {
    start,
    direction,
    relationTypes,
    maxDepth,
    nodes,
    edges: traversedEdges,
    truncated,
  };
}