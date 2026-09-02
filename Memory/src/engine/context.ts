/**
 * Context → Memory retrieval (Task 31).
 *
 * A bounded, context-oriented query surface for the Context Engine to assemble
 * provenance-rich context packs from Memory. Supports EXPLICIT SIZE / TIME /
 * PROJECT filters and returns PROVENANCE-RICH results: every record is wrapped
 * with its structural authority assessment, source kind, validity-at-instant
 * answer, evidence count and confidence — never an opaque list.
 *
 * - Project: `scope` (required — context is per-project).
 * - Size: `size` is a hard, bounded cap on returned records (1..100, default 20).
 * - Time: `at` (validity-window containment, default now) plus an optional
 *   `time.from`/`time.until` observed-window filter.
 * - Provenance filters: `kinds`, `sourceKinds`, `minConfidence`,
 *   `minAuthority` (structural authority tier), `includeRetracted`.
 * - Bounded diagnostics: `totalMatches` (records matching the filters) and
 *   `truncated` (true when more matched than returned).
 *
 * Deterministic, provider-free; pattern ADAPTED from the Context-engine pack
 * assembly intent — Memory provides bounded, provenance-attributable records
 * and never assembles packs itself (docs/BOUNDARY.md).
 */
import { ValidationError } from "../contracts/errors.ts";
import type {
  AuthorityAssessment,
  AuthorityTier,
  MemoryRecord,
  RecordKind,
  SourceKind,
} from "../contracts/types.ts";
import { authorityOf } from "./authority.ts";
import { AUTHORITY_TIER_VALUE } from "./ranking.ts";
import { rowToRecord } from "./records.ts";
import { getScopeImpl } from "./scopes.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import type { MemoryStore } from "./store.ts";

export const DEFAULT_CONTEXT_SIZE = 20;
export const MAX_CONTEXT_SIZE = 100;
/** Candidate fetch cap so authority filtering stays bounded. */
const CONTEXT_FETCH_CAP = 500;

export interface ContextTimeFilter {
  /** Only records whose observed time is at/after this instant. */
  from?: string;
  /** Only records whose observed time is before this instant. */
  until?: string;
}

export interface ContextQuery {
  /** Project (scope id or project key). Required — context is per-project. */
  scope: string;
  /** Optional free-text topic refinement (subject/content contains). */
  query?: string;
  /** Bounded budget: max records to return (1..100, default 20). */
  size?: number;
  /** Validity instant to evaluate records at (default now). */
  at?: string;
  /** Optional observed-time window filter. */
  time?: ContextTimeFilter;
  kinds?: RecordKind[];
  sourceKinds?: SourceKind[];
  /** Structural authority floor: only records at/above this tier are returned. */
  minAuthority?: AuthorityTier;
  minConfidence?: number;
  includeRetracted?: boolean;
}

export interface ContextRecord {
  record: MemoryRecord;
  /** Structural authority (never content-fluency based). */
  authority: AuthorityAssessment;
  sourceKind: SourceKind;
  /** Validity-window answer evaluated at the query instant. */
  validity: { at: string; currentlyValid: boolean };
  evidenceCount: number;
  confidence: number;
}

export interface ContextQueryResult {
  scopeId: string;
  size: number;
  returned: number;
  totalMatches: number;
  truncated: boolean;
  at: string;
  time: ContextTimeFilter | null;
  records: ContextRecord[];
}

function currentlyValid(record: MemoryRecord, at: string): boolean {
  return (
    record.status === "active" &&
    (record.validFrom === null || record.validFrom <= at) &&
    (record.validUntil === null || record.validUntil > at)
  );
}

/**
 * Bounded context-oriented retrieval with explicit size/time/project filters
 * and provenance-rich results.
 */
export function contextQueryImpl(
  store: MemoryStore,
  query: ContextQuery,
): ContextQueryResult {
  const scope = getScopeImpl(store, query.scope);
  const at = query.at ?? new Date().toISOString();
  assertIsoTimestamp(at, "at");
  if (query.time !== undefined) {
    if (query.time.from !== undefined) assertIsoTimestamp(query.time.from, "time.from");
    if (query.time.until !== undefined) assertIsoTimestamp(query.time.until, "time.until");
  }
  if (query.minConfidence !== undefined && (query.minConfidence < 0 || query.minConfidence > 1)) {
    throw new ValidationError("minConfidence must be in [0,1]");
  }
  const size = Math.min(Math.max(query.size ?? DEFAULT_CONTEXT_SIZE, 1), MAX_CONTEXT_SIZE);
  const db = store.ensureOpen();

  const clauses = [
    "r.scope_id = ?",
    "r.status != 'deleted'",
    "(r.valid_from IS NULL OR r.valid_from <= ?)",
    "(r.valid_until IS NULL OR r.valid_until > ?)",
  ];
  const params: Array<string | number> = [scope.scopeId, at, at];
  if (query.includeRetracted !== true) {
    clauses.push("r.status != 'retracted'");
  }
  if (query.kinds !== undefined && query.kinds.length > 0) {
    clauses.push(`r.kind IN (${query.kinds.map(() => "?").join(", ")})`);
    params.push(...query.kinds);
  }
  if (query.sourceKinds !== undefined && query.sourceKinds.length > 0) {
    clauses.push(`json_extract(r.provenance_json, '$.sourceKind') IN (${query.sourceKinds.map(() => "?").join(", ")})`);
    params.push(...query.sourceKinds);
  }
  if (query.minConfidence !== undefined) {
    clauses.push("r.confidence >= ?");
    params.push(query.minConfidence);
  }
  if (query.time?.from !== undefined) {
    clauses.push("r.observed_at >= ?");
    params.push(query.time.from);
  }
  if (query.time?.until !== undefined) {
    clauses.push("r.observed_at < ?");
    params.push(query.time.until);
  }
  if (query.query !== undefined && query.query.trim().length > 0) {
    const like = `%${escapeLike(query.query.trim())}%`;
    clauses.push("(r.subject LIKE ? ESCAPE '\\' OR r.content LIKE ? ESCAPE '\\')");
    params.push(like, like);
  }

  const totalRow = db
    .prepare(`SELECT COUNT(*) AS n FROM memory_records r WHERE ${clauses.join(" AND ")}`)
    .get(...params) as Record<string, unknown>;
  const totalMatches = Number(totalRow["n"]);

  const rows = db
    .prepare(
      `SELECT r.* FROM memory_records r WHERE ${clauses.join(" AND ")}
       ORDER BY r.observed_at DESC, r.record_id DESC LIMIT ?`,
    )
    .all(...params, Math.min(totalMatches, CONTEXT_FETCH_CAP)) as Array<Record<string, unknown>>;

  const minAuthorityValue =
    query.minAuthority !== undefined ? (AUTHORITY_TIER_VALUE[query.minAuthority] ?? 0) : undefined;

  let records: ContextRecord[] = rows.map((row) => {
    const record = rowToRecord(row);
    const authority = authorityOf(record.provenance, record.epistemicClass);
    return {
      record,
      authority,
      sourceKind: record.provenance.sourceKind,
      validity: { at, currentlyValid: currentlyValid(record, at) },
      evidenceCount: record.evidenceRefs.length,
      confidence: record.confidence,
    };
  });

  if (minAuthorityValue !== undefined) {
    records = records.filter((r) => (AUTHORITY_TIER_VALUE[r.authority.tier] ?? 0) >= minAuthorityValue);
  }

  // Context-friendly deterministic ordering: current first, then authority,
  // then recency. Stable via record id.
  records.sort((a, b) => {
    if (a.validity.currentlyValid !== b.validity.currentlyValid) {
      return a.validity.currentlyValid ? -1 : 1;
    }
    const av = AUTHORITY_TIER_VALUE[a.authority.tier] ?? 0;
    const bv = AUTHORITY_TIER_VALUE[b.authority.tier] ?? 0;
    if (av !== bv) return bv - av;
    if (a.record.observedAt !== b.record.observedAt) {
      return a.record.observedAt < b.record.observedAt ? 1 : -1;
    }
    return a.record.recordId < b.record.recordId ? 1 : -1;
  });

  const returned = records.slice(0, size);

  return {
    scopeId: scope.scopeId,
    size,
    returned: returned.length,
    totalMatches,
    truncated: totalMatches > returned.length,
    at,
    time: query.time ?? null,
    records: returned,
  };
}

function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, (c) => `\\${c}`);
}