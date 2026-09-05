import type {
  EvidenceCitation,
  GraphEdge,
  GraphNode,
  GraphProjectionIdentity,
  MemoryCitationRefreshDocument,
  MemoryLineageEntry,
  PriorityTier,
  PromptRunGraphDocument,
  TruncationReason,
} from "./types";
import {
  DESKTOP_HOST_URL,
  HOST_CONTRACT_VERSION,
  PerformanceContractVersionError,
  PerformanceHostError,
  PerformanceInvalidResponseError,
  PerformanceUnavailableError,
  type PerformanceFetch,
} from "../activity/performanceSource";

/**
 * Transport + validation for the Midnight Desktop Host's `graph.getPromptRun`
 * operation — mirrors `activity/performanceSource.ts`'s envelope handling
 * exactly (same versioned `{contractVersion, operation, request}` →
 * `{contractVersion, operation, ok, result|error}` convention, same Host
 * error classes) rather than inventing a parallel transport layer.
 *
 * The graph document is structurally interdependent (edges reference node
 * ids by identity) — unlike `parseActivityDocument`'s per-event
 * drop-on-malformed degrade, a malformed node/edge/citation here fails the
 * WHOLE document closed (`PerformanceInvalidResponseError`) rather than
 * silently repairing a graph that could end up missing an edge's endpoint.
 * The Host has already schema-validated this exact document before
 * returning it, so a malformed shape here means a genuine Host/contract
 * bug, not routine bad data.
 */

export const GRAPH_OPERATION = "graph.getPromptRun";

export interface GraphRequestOptions {
  readonly maxDepth?: number;
  readonly maxNodes?: number;
  readonly maxEdges?: number;
  readonly allowedLayers?: readonly string[];
  readonly cursor?: string;
  readonly focusNode?: string;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

const PRIORITY_TIERS: readonly PriorityTier[] = ["primary", "on_demand"];
function parsePriorityTier(value: unknown, index: number): PriorityTier {
  if (typeof value === "string" && (PRIORITY_TIERS as readonly string[]).includes(value)) return value as PriorityTier;
  throw new PerformanceInvalidResponseError(`graph response nodes[${index}].priority_tier is missing or invalid`);
}

function parseNode(raw: unknown, index: number): GraphNode {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError(`graph response nodes[${index}] is not an object`);
  }
  const n = raw as Record<string, unknown>;
  if (typeof n.id !== "string" || !n.id) throw new PerformanceInvalidResponseError(`graph response nodes[${index}].id is missing`);
  if (typeof n.kind !== "string") throw new PerformanceInvalidResponseError(`graph response nodes[${index}].kind is missing`);
  if (typeof n.layer !== "string") throw new PerformanceInvalidResponseError(`graph response nodes[${index}].layer is missing`);
  if (typeof n.label !== "string") throw new PerformanceInvalidResponseError(`graph response nodes[${index}].label is missing`);
  if (typeof n.claim_kind !== "string") throw new PerformanceInvalidResponseError(`graph response nodes[${index}].claim_kind is missing`);
  if (!isStringArray(n.provenance)) throw new PerformanceInvalidResponseError(`graph response nodes[${index}].provenance must be a string array`);
  if (!isStringArray(n.gaps)) throw new PerformanceInvalidResponseError(`graph response nodes[${index}].gaps must be a string array`);
  return {
    id: n.id,
    kind: n.kind,
    layer: n.layer,
    priority_tier: parsePriorityTier(n.priority_tier, index),
    label: n.label,
    claim_kind: n.claim_kind,
    provenance: n.provenance,
    observed_at: (n.observed_at as string | null | undefined) ?? null,
    project_context: (n.project_context as string | null | undefined) ?? null,
    externally_referenced: n.externally_referenced === true,
    gaps: n.gaps,
    source_claim_kind: (n.source_claim_kind as string | null | undefined) ?? null,
    source_layer: (n.source_layer as string | null | undefined) ?? null,
  };
}

function parseEdge(raw: unknown, index: number): GraphEdge {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError(`graph response edges[${index}] is not an object`);
  }
  const e = raw as Record<string, unknown>;
  if (typeof e.source !== "string" || !e.source) throw new PerformanceInvalidResponseError(`graph response edges[${index}].source is missing`);
  if (typeof e.target !== "string" || !e.target) throw new PerformanceInvalidResponseError(`graph response edges[${index}].target is missing`);
  if (typeof e.kind !== "string") throw new PerformanceInvalidResponseError(`graph response edges[${index}].kind is missing`);
  if (!isStringArray(e.evidence)) throw new PerformanceInvalidResponseError(`graph response edges[${index}].evidence must be a string array`);
  return {
    source: e.source,
    target: e.target,
    kind: e.kind,
    claim_kind: typeof e.claim_kind === "string" ? e.claim_kind : "",
    evidence: e.evidence,
    confidence: (e.confidence as number | null | undefined) ?? null,
    method: typeof e.method === "string" ? e.method : "",
    method_version: typeof e.method_version === "string" ? e.method_version : "",
    uncertainty: typeof e.uncertainty === "string" ? e.uncertainty : "",
    semantic_role: (e.semantic_role as string | null | undefined) ?? null,
  };
}

function parseCitation(raw: unknown, index: number): EvidenceCitation {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError(`graph response citations[${index}] is not an object`);
  }
  const c = raw as Record<string, unknown>;
  if (typeof c.reference_id !== "string" || !c.reference_id) {
    throw new PerformanceInvalidResponseError(`graph response citations[${index}].reference_id is missing`);
  }
  if (typeof c.evidence_kind !== "string") throw new PerformanceInvalidResponseError(`graph response citations[${index}].evidence_kind is missing`);
  return {
    reference_id: c.reference_id,
    evidence_kind: c.evidence_kind,
    project: typeof c.project === "string" ? c.project : "",
    observed_at: (c.observed_at as string | null | undefined) ?? null,
    source: (c.source as string | null | undefined) ?? null,
    detail_available: c.detail_available === true,
    summary: (c.summary as string | null | undefined) ?? null,
  };
}

/** Shared by `parsePromptRunGraphDocument`'s `memoryLineage` array and
 * `parseMemoryCitationRefreshDocument`'s `state` (same field shape, minus
 * `nodeId` for the latter — see `MemoryCitationRefreshDocument`). */
function parseMemoryCitationState(raw: unknown, path: string): Omit<MemoryLineageEntry, "nodeId"> {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError(`${path} is not an object`);
  }
  const s = raw as Record<string, unknown>;
  if (typeof s.provider !== "string" || !s.provider) throw new PerformanceInvalidResponseError(`${path}.provider is missing`);
  if (typeof s.recordId !== "string" || !s.recordId) throw new PerformanceInvalidResponseError(`${path}.recordId is missing`);
  if (typeof s.pinnedRevision !== "number") throw new PerformanceInvalidResponseError(`${path}.pinnedRevision is missing`);
  if (!isStringArray(s.gaps)) throw new PerformanceInvalidResponseError(`${path}.gaps must be a string array`);
  return {
    provider: s.provider,
    recordId: s.recordId,
    pinnedRevision: s.pinnedRevision,
    currentStatusKnown: s.currentStatusKnown === true,
    currentRevision: (s.currentRevision as number | null | undefined) ?? null,
    currentStatus: (s.currentStatus as string | null | undefined) ?? null,
    superseded: (s.superseded as boolean | null | undefined) ?? null,
    supersededByRecordId: (s.supersededByRecordId as string | null | undefined) ?? null,
    contradictionGroupId: (s.contradictionGroupId as string | null | undefined) ?? null,
    contradictionStatus: (s.contradictionStatus as string | null | undefined) ?? null,
    contradictionGroupSize: (s.contradictionGroupSize as number | null | undefined) ?? null,
    newerRevisionAvailable: (s.newerRevisionAvailable as boolean | null | undefined) ?? null,
    refreshedAt: (s.refreshedAt as string | null | undefined) ?? null,
    gaps: s.gaps,
  };
}

function parseMemoryLineageEntry(raw: unknown, index: number): MemoryLineageEntry {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError(`graph response memoryLineage[${index}] is not an object`);
  }
  const entry = raw as Record<string, unknown>;
  if (typeof entry.nodeId !== "string" || !entry.nodeId) {
    throw new PerformanceInvalidResponseError(`graph response memoryLineage[${index}].nodeId is missing`);
  }
  return { nodeId: entry.nodeId, ...parseMemoryCitationState(raw, `graph response memoryLineage[${index}]`) };
}

/** Validate an already-decoded `graph.getPromptRun` result. Throws on structural malformation. */
export function parsePromptRunGraphDocument(raw: unknown): PromptRunGraphDocument {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("graph response is not an object");
  }
  const document = raw as Record<string, unknown>;
  if (document.version !== 1) {
    throw new PerformanceInvalidResponseError(`unsupported graph contract version: ${String(document.version)}`);
  }
  if (typeof document.project !== "string" || !document.project.trim()) {
    throw new PerformanceInvalidResponseError("graph response is missing its project identity");
  }
  if (typeof document.root !== "string" || !document.root.trim()) {
    throw new PerformanceInvalidResponseError("graph response is missing its root identity");
  }
  if (!Array.isArray(document.nodes)) throw new PerformanceInvalidResponseError("graph response nodes must be an array");
  if (!Array.isArray(document.edges)) throw new PerformanceInvalidResponseError("graph response edges must be an array");
  if (!Array.isArray(document.citations)) throw new PerformanceInvalidResponseError("graph response citations must be an array");
  if (!Array.isArray(document.memoryLineage)) throw new PerformanceInvalidResponseError("graph response memoryLineage must be an array");
  if (!isStringArray(document.gaps)) throw new PerformanceInvalidResponseError("graph response gaps must be a string array");
  if (typeof document.truncated !== "boolean") throw new PerformanceInvalidResponseError("graph response truncated must be a boolean");
  if (!isStringArray(document.truncationReasons)) throw new PerformanceInvalidResponseError("graph response truncationReasons must be a string array");
  const bounds = document.bounds as Record<string, unknown> | undefined;
  if (typeof bounds !== "object" || bounds === null) throw new PerformanceInvalidResponseError("graph response bounds is missing");
  const projectionIdentity = document.projectionIdentity as Record<string, unknown> | undefined;
  if (
    typeof projectionIdentity !== "object" ||
    projectionIdentity === null ||
    typeof projectionIdentity.evidenceCheckpoint !== "string" ||
    !projectionIdentity.evidenceCheckpoint
  ) {
    throw new PerformanceInvalidResponseError("graph response projectionIdentity is missing or malformed");
  }
  const integrity = document.integrity as Record<string, unknown> | undefined;
  if (typeof integrity !== "object" || integrity === null || typeof integrity.qualifies !== "boolean" || !Array.isArray(integrity.findings)) {
    throw new PerformanceInvalidResponseError("graph response integrity is missing or malformed");
  }

  return {
    version: 1,
    project: document.project,
    root: document.root,
    nodes: document.nodes.map(parseNode),
    edges: document.edges.map(parseEdge),
    citations: document.citations.map(parseCitation),
    memoryLineage: document.memoryLineage.map(parseMemoryLineageEntry),
    gaps: document.gaps,
    truncated: document.truncated,
    truncationReasons: document.truncationReasons as TruncationReason[],
    cursor: (document.cursor as string | null | undefined) ?? null,
    nextCursor: (document.nextCursor as string | null | undefined) ?? null,
    bounds: {
      maxDepth: (bounds.maxDepth as number | null | undefined) ?? null,
      maxNodes: typeof bounds.maxNodes === "number" ? bounds.maxNodes : 0,
      maxEdges: typeof bounds.maxEdges === "number" ? bounds.maxEdges : 0,
      allowedLayers: isStringArray(bounds.allowedLayers) ? bounds.allowedLayers : null,
      focusNode: (bounds.focusNode as string | null | undefined) ?? null,
    },
    projectionIdentity: {
      project: typeof projectionIdentity.project === "string" ? projectionIdentity.project : "",
      root: typeof projectionIdentity.root === "string" ? projectionIdentity.root : "",
      graphSchemaVersion: 1,
      graphAlgorithmMethod: typeof projectionIdentity.graphAlgorithmMethod === "string" ? projectionIdentity.graphAlgorithmMethod : "",
      graphAlgorithmVersion: typeof projectionIdentity.graphAlgorithmVersion === "string" ? projectionIdentity.graphAlgorithmVersion : "",
      evidenceCheckpoint: projectionIdentity.evidenceCheckpoint,
    } as GraphProjectionIdentity,
    integrity: {
      qualifies: integrity.qualifies,
      findings: integrity.findings.map((raw, index) => {
        if (typeof raw !== "object" || raw === null) {
          throw new PerformanceInvalidResponseError(`graph response integrity.findings[${index}] is not an object`);
        }
        const f = raw as Record<string, unknown>;
        return {
          kind: typeof f.kind === "string" ? f.kind : "",
          severity: (f.severity as "info" | "warning" | "error") ?? "info",
          subject_id: typeof f.subject_id === "string" ? f.subject_id : "",
          reference_id: (f.reference_id as string | null | undefined) ?? null,
          evidence: isStringArray(f.evidence) ? f.evidence : [],
          uncertainty: typeof f.uncertainty === "string" ? f.uncertainty : "",
        };
      }),
    },
  };
}

/** Map a Host-reported error code to the exception class its message deserves. */
function toGraphHostError(code: unknown, message: unknown): Error {
  const safeCode = typeof code === "string" ? code : "UNKNOWN";
  const safeMessage = typeof message === "string" && message.trim() ? message : "Desktop Host reported an error";
  if (safeCode === "BRIDGE_UNAVAILABLE" || safeCode === "BRIDGE_TIMEOUT") {
    return new PerformanceUnavailableError(safeMessage);
  }
  return new PerformanceHostError(safeCode, safeMessage);
}

function parseHostEnvelope(raw: unknown): PromptRunGraphDocument {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("Desktop Host response is not an object");
  }
  const envelope = raw as Record<string, unknown>;
  if (envelope.contractVersion !== HOST_CONTRACT_VERSION) {
    throw new PerformanceContractVersionError(
      `unsupported Desktop Host contractVersion: ${String(envelope.contractVersion)}`,
    );
  }
  if (envelope.ok === false) {
    const error = envelope.error as Record<string, unknown> | undefined;
    throw toGraphHostError(error?.code, error?.message);
  }
  if (envelope.ok !== true) {
    throw new PerformanceInvalidResponseError("Desktop Host response envelope is missing 'ok'");
  }
  return parsePromptRunGraphDocument(envelope.result);
}

export async function fetchPromptRunGraph(
  promptRunId: string,
  options: GraphRequestOptions = {},
  fetchImpl: PerformanceFetch = fetch,
  url: string = DESKTOP_HOST_URL,
): Promise<PromptRunGraphDocument> {
  const request: Record<string, unknown> = { promptRunId };
  if (options.maxDepth !== undefined) request.maxDepth = options.maxDepth;
  if (options.maxNodes !== undefined) request.maxNodes = options.maxNodes;
  if (options.maxEdges !== undefined) request.maxEdges = options.maxEdges;
  if (options.allowedLayers !== undefined) request.allowedLayers = options.allowedLayers;
  if (options.cursor !== undefined) request.cursor = options.cursor;
  if (options.focusNode !== undefined) request.focusNode = options.focusNode;

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contractVersion: HOST_CONTRACT_VERSION, operation: GRAPH_OPERATION, request }),
    });
  } catch (cause) {
    throw new PerformanceUnavailableError(cause instanceof Error ? cause.message : String(cause));
  }
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new PerformanceInvalidResponseError("Desktop Host response is not valid JSON");
  }
  return parseHostEnvelope(raw);
}

/**
 * Execution 09, Section C: transport for `graph.refreshMemoryCitation` —
 * deliberately separate from `fetchPromptRunGraph` above (own operation
 * name, own response parser). A caller decides what to do with the
 * returned `MemoryCitationRefreshDocument`; this function never touches or
 * re-fetches any previously held `PromptRunGraphDocument`.
 */
export const REFRESH_MEMORY_CITATION_OPERATION = "graph.refreshMemoryCitation";

function parseMemoryCitationRefreshDocument(raw: unknown): MemoryCitationRefreshDocument {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("refresh response is not an object");
  }
  const document = raw as Record<string, unknown>;
  if (document.version !== 1) {
    throw new PerformanceInvalidResponseError(`unsupported refresh contract version: ${String(document.version)}`);
  }
  if (typeof document.project !== "string" || !document.project.trim()) {
    throw new PerformanceInvalidResponseError("refresh response is missing its project identity");
  }
  const reference = document.reference as Record<string, unknown> | undefined;
  if (
    typeof reference !== "object" ||
    reference === null ||
    typeof reference.provider !== "string" ||
    typeof reference.kind !== "string" ||
    typeof reference.value !== "string"
  ) {
    throw new PerformanceInvalidResponseError("refresh response reference is missing or malformed");
  }
  return {
    version: 1,
    project: document.project,
    reference: { provider: reference.provider, kind: reference.kind, value: reference.value },
    state: parseMemoryCitationState(document.state, "refresh response state"),
  };
}

function parseRefreshHostEnvelope(raw: unknown): MemoryCitationRefreshDocument {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("Desktop Host response is not an object");
  }
  const envelope = raw as Record<string, unknown>;
  if (envelope.contractVersion !== HOST_CONTRACT_VERSION) {
    throw new PerformanceContractVersionError(
      `unsupported Desktop Host contractVersion: ${String(envelope.contractVersion)}`,
    );
  }
  if (envelope.ok === false) {
    const error = envelope.error as Record<string, unknown> | undefined;
    throw toGraphHostError(error?.code, error?.message);
  }
  if (envelope.ok !== true) {
    throw new PerformanceInvalidResponseError("Desktop Host response envelope is missing 'ok'");
  }
  return parseMemoryCitationRefreshDocument(envelope.result);
}

export async function fetchRefreshMemoryCitation(
  referenceValue: string,
  fetchImpl: PerformanceFetch = fetch,
  url: string = DESKTOP_HOST_URL,
): Promise<MemoryCitationRefreshDocument> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contractVersion: HOST_CONTRACT_VERSION,
        operation: REFRESH_MEMORY_CITATION_OPERATION,
        request: { referenceValue },
      }),
    });
  } catch (cause) {
    throw new PerformanceUnavailableError(cause instanceof Error ? cause.message : String(cause));
  }
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new PerformanceInvalidResponseError("Desktop Host response is not valid JSON");
  }
  return parseRefreshHostEnvelope(raw);
}
