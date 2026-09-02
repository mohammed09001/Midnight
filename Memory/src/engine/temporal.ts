/**
 * Temporal validity and historical truth (Task 5).
 *
 * Bi-temporal model (pattern adapted from getzep/graphiti's temporal
 * knowledge graph design — invalidate, never delete; graph store itself
 * REJECTED as out of Memory boundary):
 *
 * - Valid time:   `observedAt` (when the claim held in the source reality),
 *                 bounded by `validFrom`/`validUntil`.
 * - Transaction time: `createdAt`/`revisedAt` (when the Memory store learned
 *                 or changed it), plus `supersededAt` (when invalidated by a
 *                 successor).
 *
 * Historical queries reconstruct what was believed at a past point T
 * WITHOUT overwriting or rewriting the past: superseded/retracted records
 * remain queryable with their full chain.
 */
import { NotFoundError, ValidationError } from "../contracts/errors.ts";
import type { MemoryRecord, Provenance } from "../contracts/types.ts";
import { rowToRecord } from "./records.ts";
import { getScopeImpl } from "./scopes.ts";
import type { MemoryStore } from "./store.ts";

export interface RecordRevision {
  revision: number;
  content: string;
  contentHash: string;
  provenance: Provenance;
  revisedAt: string;
  reason: string | null;
}

export interface RecordHistory {
  recordId: string;
  subject: string;
  scopeId: string;
  /** Complete supersession chain, ordered oldest → newest, incl. this record. */
  chain: Array<{
    recordId: string;
    content: string;
    status: string;
    observedAt: string;
    supersededAt: string | null;
    /** Task 11: explicit supersession reason (on the superseded entries). */
    supersededReason: string | null;
  }>;
  /** Immutable revision rows for the requested record. */
  revisions: RecordRevision[];
}

export interface AsOfQuery {
  scope?: string;
  /** ISO 8601 instant to reconstruct belief state at. Required. */
  asOf: string;
  /** Include retracted records that were still believed at T. Default true. */
  includeRetracted?: boolean;
  limit?: number;
}

const ISO_LIKE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export function assertIsoTimestamp(value: string, field: string): void {
  if (typeof value !== "string" || !ISO_LIKE.test(value) || Number.isNaN(Date.parse(value))) {
    throw new ValidationError(`${field} must be an ISO 8601 timestamp`);
  }
}

export function getRecordHistoryImpl(
  store: MemoryStore,
  recordId: string,
): RecordHistory {
  const record = requireRecord(store, recordId);
  const db = store.ensureOpen();

  const revisionRows = db
    .prepare(
      `SELECT revision, content, content_hash, provenance_json, revised_at, reason
       FROM memory_record_revisions WHERE record_id = ? ORDER BY revision`,
    )
    .all(recordId) as Array<Record<string, unknown>>;

  const chainIds = collectChain(store, record);
  const chain = chainIds.map((id) => {
    const row = requireRecord(store, id);
    return {
      recordId: row.recordId,
      content: row.content,
      status: row.status,
      observedAt: row.observedAt,
      supersededAt: row.supersededAt,
      supersededReason: row.supersededReason,
    };
  });

  return {
    recordId,
    subject: record.subject,
    scopeId: record.scopeId,
    chain,
    revisions: revisionRows.map((r) => ({
      revision: Number(r["revision"]),
      content: String(r["content"]),
      contentHash: String(r["content_hash"]),
      provenance: JSON.parse(String(r["provenance_json"])) as Provenance,
      revisedAt: String(r["revised_at"]),
      reason: r["reason"] === null ? null : String(r["reason"]),
    })),
  };
}

/** Follow supersedes_id backwards and superseded_by_id forwards. */
function collectChain(store: MemoryStore, record: MemoryRecord): string[] {
  const predecessors: string[] = [];
  let cursor: MemoryRecord = record;
  const guard = new Set<string>([record.recordId]);
  while (cursor.supersedesId !== null && !guard.has(cursor.supersedesId)) {
    guard.add(cursor.supersedesId);
    predecessors.unshift(cursor.supersedesId);
    cursor = requireRecord(store, cursor.supersedesId);
  }
  const successors: string[] = [];
  cursor = record;
  while (cursor.supersededById !== null && !guard.has(cursor.supersededById)) {
    guard.add(cursor.supersededById);
    successors.push(cursor.supersededById);
    cursor = requireRecord(store, cursor.supersededById);
  }
  return [...predecessors, record.recordId, ...successors];
}

/**
 * Reconstruct what was believed at instant T:
 * - learned no later than T            (created_at ≤ T)
 * - validity window contains T         (validFrom ≤ T < validUntil, nulls open)
 * - not superseded before T            (superseded_at null or > T)
 * - retracted only before T if flag    (retraction applies from its
 *   retraction revision time forward; historical belief can include it)
 */
/** Shared clause/param builder — order-sensitive; a COUNT reuse must not rebuild it. */
function buildAsOfClauses(
  store: MemoryStore,
  query: AsOfQuery,
): { clauses: string[]; params: Array<string | number> } {
  const params: Array<string | number> = [query.asOf, query.asOf, query.asOf, query.asOf];
  const clauses = [
    "created_at <= ?",
    "(valid_from IS NULL OR valid_from <= ?)",
    "(valid_until IS NULL OR valid_until > ?)",
    "(superseded_at IS NULL OR superseded_at > ?)",
    // Task 13: tombstoned records are removed from every belief view —
    // their content no longer exists to reconstruct.
    "deleted_at IS NULL",
    // Archived records were still believed until they were archived.
    "(status != 'archived' OR archived_at IS NULL OR archived_at > ?)",
  ];
  params.push(query.asOf);
  if (query.includeRetracted === false) {
    // Hard exclusion requested by the caller.
    clauses.push("status != 'retracted'");
  } else {
    // Belief semantics: a retracted record was believed until its retraction
    // instant (stamped in revised_at by retractRecordImpl), never after.
    clauses.push("(status != 'retracted' OR revised_at > ?)");
    params.push(query.asOf);
  }
  if (query.scope !== undefined) {
    // Accept both project keys and scope ids, like searchRecordsImpl.
    const scope = getScopeImpl(store, query.scope);
    clauses.push("scope_id = ?");
    params.push(scope.scopeId);
  }
  return { clauses, params };
}

export function queryRecordsAsOfImpl(
  store: MemoryStore,
  query: AsOfQuery,
): MemoryRecord[] {
  assertIsoTimestamp(query.asOf, "asOf");
  const db = store.ensureOpen();
  const { clauses, params } = buildAsOfClauses(store, query);
  const limit = Math.min(Math.max(query.limit ?? 100, 1), 1000);
  const rows = db
    .prepare(
      `SELECT * FROM memory_records WHERE ${clauses.join(" AND ")}
       ORDER BY created_at DESC, record_id DESC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  return rows.map((row) => requireRecord(store, String(row["record_id"])));
}

// ---- Task 20: retrieval trace for the bi-temporal as-of query -------------

export interface AsOfMatchReason {
  filter: string;
  reason: string;
}

export interface AsOfTrace {
  appliedFilters: Record<string, unknown>;
  asOf: string;
  totalMatches: number;
  truncated: boolean;
  matches: Record<string, AsOfMatchReason[]>;
}

function explainAsOfMatch(query: AsOfQuery, record: MemoryRecord): AsOfMatchReason[] {
  const asOf = query.asOf;
  const reasons: AsOfMatchReason[] = [
    { filter: "createdAt", reason: `createdAt '${record.createdAt}' <= asOf '${asOf}'` },
    {
      filter: "validFrom",
      reason:
        record.validFrom === null
          ? "validFrom is null (open start)"
          : `validFrom '${record.validFrom}' <= asOf '${asOf}'`,
    },
    {
      filter: "validUntil",
      reason:
        record.validUntil === null
          ? "validUntil is null (open end)"
          : `validUntil '${record.validUntil}' > asOf '${asOf}'`,
    },
    {
      filter: "supersededAt",
      reason:
        record.supersededAt === null
          ? "not superseded"
          : `supersededAt '${record.supersededAt}' > asOf '${asOf}' (still believed at that instant)`,
    },
  ];
  if (record.status === "retracted") {
    reasons.push({
      filter: "retracted",
      reason:
        query.includeRetracted === false
          ? "included despite retraction: includeRetracted must be non-false to reach here"
          : `retracted at revisedAt '${record.revisedAt}' > asOf '${asOf}' (still believed at that instant)`,
    });
  }
  return reasons;
}

/** Task 20: `queryRecordsAsOfImpl`, plus which filters applied and why each record matched. */
export function queryRecordsAsOfTracedImpl(
  store: MemoryStore,
  query: AsOfQuery,
): { records: MemoryRecord[]; trace: AsOfTrace } {
  assertIsoTimestamp(query.asOf, "asOf");
  const db = store.ensureOpen();
  const { clauses, params } = buildAsOfClauses(store, query);
  const limit = Math.min(Math.max(query.limit ?? 100, 1), 1000);
  const where = `WHERE ${clauses.join(" AND ")}`;
  const rows = db
    .prepare(
      `SELECT * FROM memory_records ${where} ORDER BY created_at DESC, record_id DESC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  const records = rows.map((row) => requireRecord(store, String(row["record_id"])));
  const totalRow = db
    .prepare(`SELECT COUNT(*) AS n FROM memory_records ${where}`)
    .get(...params) as Record<string, unknown>;
  const totalMatches = Number(totalRow["n"]);
  const matches: Record<string, AsOfMatchReason[]> = {};
  for (const record of records) {
    matches[record.recordId] = explainAsOfMatch(query, record);
  }
  const appliedFilters: Record<string, unknown> = {};
  if (query.scope !== undefined) appliedFilters["scope"] = query.scope;
  if (query.includeRetracted !== undefined) appliedFilters["includeRetracted"] = query.includeRetracted;
  return {
    records,
    trace: {
      appliedFilters,
      asOf: query.asOf,
      totalMatches,
      truncated: totalMatches > records.length,
      matches,
    },
  };
}

function requireRecord(store: MemoryStore, recordId: string): MemoryRecord {
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT * FROM memory_records WHERE record_id = ?")
    .get(recordId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new NotFoundError(`Record '${recordId}' not found`);
  }
  return rowToRecord(row);
}
