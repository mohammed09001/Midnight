/**
 * Wire types for `graph.getPromptRun`'s response — mirrors
 * `Performance/midnight_performance/schemas/graph-prompt-run-response.schema.json`
 * field-for-field, snake_case included. Unlike `activity-response.schema.json`
 * (fully camelCase), the graph contract's top level uses camelCase
 * (`nextCursor`, `truncated`) while nested node/edge/citation objects use
 * snake_case (`semantic_role`, `claim_kind`, `reference_id`) — an existing
 * asymmetry in the Execution 06 contract, not something this execution's
 * frontend introduces or silently renames. `graph_bridge.py` is the source
 * of truth; if that contract is ever normalized, this file changes with it.
 */

export type PriorityTier = "primary" | "on_demand";

export interface GraphNode {
  readonly id: string;
  readonly kind: string;
  readonly layer: string;
  readonly priority_tier: PriorityTier;
  readonly label: string;
  readonly claim_kind: string;
  readonly provenance: readonly string[];
  readonly observed_at: string | null;
  readonly project_context: string | null;
  readonly externally_referenced: boolean;
  readonly gaps: readonly string[];
  readonly source_claim_kind: string | null;
  readonly source_layer: string | null;
}

export interface GraphEdge {
  readonly source: string;
  readonly target: string;
  readonly kind: string;
  readonly claim_kind: string;
  readonly evidence: readonly string[];
  readonly confidence: number | null;
  readonly method: string;
  readonly method_version: string;
  readonly uncertainty: string;
  readonly semantic_role: string | null;
}

export interface EvidenceCitation {
  readonly reference_id: string;
  readonly evidence_kind: string;
  readonly project: string;
  readonly observed_at: string | null;
  readonly source: string | null;
  readonly detail_available: boolean;
  readonly summary: string | null;
}

export type IntegritySeverity = "info" | "warning" | "error";

export interface GraphIntegrityFinding {
  readonly kind: string;
  readonly severity: IntegritySeverity;
  readonly subject_id: string;
  readonly reference_id: string | null;
  readonly evidence: readonly string[];
  readonly uncertainty: string;
}

/**
 * Execution 09 (Memory Temporal Lineage Overlay): the build-time-only
 * pinned state for one cited Memory node — mirrors
 * `memory_temporal_lineage.MemoryCitationState.to_record()` field-for-field.
 * `currentStatusKnown` is always `false` here; a live current read only
 * ever comes from a separate `graph.refreshMemoryCitation` call
 * (`MemoryCitationRefreshDocument` below), never from this array, so a
 * `PromptRunGraphDocument` already fetched never silently gains live data.
 */
export interface MemoryLineageEntry {
  readonly nodeId: string;
  readonly provider: string;
  readonly recordId: string;
  readonly pinnedRevision: number;
  readonly currentStatusKnown: boolean;
  readonly currentRevision: number | null;
  readonly currentStatus: string | null;
  readonly superseded: boolean | null;
  readonly supersededByRecordId: string | null;
  readonly contradictionGroupId: string | null;
  readonly contradictionStatus: string | null;
  readonly contradictionGroupSize: number | null;
  readonly newerRevisionAvailable: boolean | null;
  readonly refreshedAt: string | null;
  readonly gaps: readonly string[];
}

/**
 * Result of one explicit `graph.refreshMemoryCitation` read (Section C):
 * a brand-new projection, never a mutation of any `MemoryLineageEntry`
 * already held from a `PromptRunGraphDocument`.
 */
export interface MemoryCitationRefreshDocument {
  readonly version: 1;
  readonly project: string;
  readonly reference: { readonly provider: string; readonly kind: string; readonly value: string };
  readonly state: Omit<MemoryLineageEntry, "nodeId">;
}

export type TruncationReason = "max_depth" | "layer_filter" | "max_nodes" | "max_edges";

export interface GraphBounds {
  readonly maxDepth: number | null;
  readonly maxNodes: number;
  readonly maxEdges: number;
  readonly allowedLayers: readonly string[] | null;
  readonly focusNode: string | null;
}

/**
 * Execution 10, Section B: a graph document's own self-contained identity
 * descriptor — never itself canonical evidence (Section C), only a
 * fingerprint a cache key is built from (`graphCache.ts`).
 */
export interface GraphProjectionIdentity {
  readonly project: string;
  readonly root: string;
  readonly graphSchemaVersion: 1;
  readonly graphAlgorithmMethod: string;
  readonly graphAlgorithmVersion: string;
  readonly evidenceCheckpoint: string;
}

export interface PromptRunGraphDocument {
  readonly version: 1;
  readonly project: string;
  readonly root: string;
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly citations: readonly EvidenceCitation[];
  readonly memoryLineage: readonly MemoryLineageEntry[];
  readonly gaps: readonly string[];
  readonly truncated: boolean;
  readonly truncationReasons: readonly TruncationReason[];
  readonly cursor: string | null;
  readonly nextCursor: string | null;
  readonly bounds: GraphBounds;
  readonly projectionIdentity: GraphProjectionIdentity;
  readonly integrity: {
    readonly qualifies: boolean;
    readonly findings: readonly GraphIntegrityFinding[];
  };
}
