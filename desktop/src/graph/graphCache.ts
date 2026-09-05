import type { GraphBounds, GraphProjectionIdentity } from "./types";

/**
 * Execution 10, Section C: a client-side cache for REBUILDABLE data only —
 * layout coordinates, keyed off a graph document's own `projectionIdentity`
 * plus the exact node/edge set actually laid out. The key is a lookup
 * fingerprint, never itself treated as canonical evidence (Section C:
 * "do not call a cache hash canonical evidence") — it is built entirely
 * from fields the document already reports, so a real evidence change
 * (a new `evidenceCheckpoint`) or a different slice naturally produces a
 * different key and therefore a cache miss, never a stale hit.
 *
 * Deliberately does NOT cache `PromptRunGraphDocument` fetches themselves:
 * this document's own `evidenceCheckpoint` is only knowable AFTER a fetch
 * completes, so a document-level cache can never validate its own key
 * before making the same network round-trip it was meant to avoid. Layout
 * coordinates have no such problem — once a document is in hand, its
 * `projectionIdentity` is already known, and re-laying-out the exact same
 * visible node/edge set (e.g. toggling a layer filter back and forth) is
 * pure, expensive (elk), and safe to skip on a cache hit.
 */
export interface GraphCacheSlice {
  readonly maxDepth?: number | null;
  readonly maxNodes?: number;
  readonly maxEdges?: number;
  readonly allowedLayers?: readonly string[] | null;
  readonly focusNode?: string | null;
  readonly cursor?: string | null;
}

export function buildGraphCacheKey(
  identity: Pick<GraphProjectionIdentity, "project" | "root" | "graphSchemaVersion" | "graphAlgorithmMethod" | "graphAlgorithmVersion" | "evidenceCheckpoint">,
  slice: GraphCacheSlice,
  /** Only meaningful for a cache whose VALUE embeds live Memory current-state
   * (this module's layout cache does not — a refreshed `MemoryLineageEntry`
   * never changes node positions). Included so a future cache that does
   * embed Memory state stays correct by construction, per Section C. */
  memoryCheckpoint: string | null = null,
): string {
  return JSON.stringify([
    identity.project,
    identity.root,
    identity.graphSchemaVersion,
    identity.graphAlgorithmMethod,
    identity.graphAlgorithmVersion,
    identity.evidenceCheckpoint,
    slice.maxDepth ?? null,
    slice.maxNodes ?? null,
    slice.maxEdges ?? null,
    slice.allowedLayers ? [...slice.allowedLayers].sort() : null,
    slice.focusNode ?? null,
    slice.cursor ?? null,
    memoryCheckpoint,
  ]);
}

export function sliceFromBounds(bounds: GraphBounds, cursor: string | null): GraphCacheSlice {
  return {
    maxDepth: bounds.maxDepth,
    maxNodes: bounds.maxNodes,
    maxEdges: bounds.maxEdges,
    allowedLayers: bounds.allowedLayers,
    focusNode: bounds.focusNode,
    cursor,
  };
}

/**
 * A small, bounded LRU cache. Project isolation is structural, not an
 * afterthought filter: `project` is always the first key segment
 * `buildGraphCacheKey` writes, so two projects' entries can never collide
 * under the same key even if every other field happened to match.
 */
export class GraphCache<TValue> {
  private readonly maxEntries: number;
  private readonly store = new Map<string, TValue>();

  constructor(maxEntries = 20) {
    if (maxEntries < 1) throw new Error("maxEntries must be positive");
    this.maxEntries = maxEntries;
  }

  get(key: string): TValue | undefined {
    const value = this.store.get(key);
    if (value === undefined) return undefined;
    // Re-insert to move this key to the end of Map's iteration order —
    // the eviction loop below always drops the FRONT (least recently used).
    this.store.delete(key);
    this.store.set(key, value);
    return value;
  }

  set(key: string, value: TValue): void {
    this.store.delete(key);
    this.store.set(key, value);
    while (this.store.size > this.maxEntries) {
      const oldest = this.store.keys().next().value;
      if (oldest === undefined) break;
      this.store.delete(oldest);
    }
  }

  clear(): void {
    this.store.clear();
  }

  get size(): number {
    return this.store.size;
  }
}
