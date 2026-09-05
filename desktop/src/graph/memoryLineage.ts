import type { MemoryLineageEntry, PromptRunGraphDocument } from "./types";

/**
 * Unlike `citations.ts`'s evidence-citation join (which reconstructs the
 * node ↔ citation relationship from edge evidence, because
 * `EvidenceCitation` carries no node id of its own), `MemoryLineageEntry`
 * already carries its owning `nodeId` directly (`graph_bridge.py`'s
 * `_build_memory_lineage` sets it explicitly) — so this join is a plain
 * lookup, no edge-evidence indirection needed.
 */
export function memoryLineageForNode(document: PromptRunGraphDocument, nodeId: string): MemoryLineageEntry | null {
  // `document.memoryLineage` is guaranteed present for any document that
  // went through `parsePromptRunGraphDocument` (the real Host path) — this
  // falls back to `[]` only for `App.tsx`'s dev-only `?fixtureUrl=` escape
  // hatch, which loads raw JSON without that validation and can point at a
  // pre-Execution-09 fixture that predates this field.
  return (document.memoryLineage ?? []).find((entry) => entry.nodeId === nodeId) ?? null;
}
