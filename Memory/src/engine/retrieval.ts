/**
 * Deterministic retrieval baseline (Tasks 14–16).
 *
 * - Lexical/BM25 search (Task 15): SQLite FTS5 external-content index over
 *   memory_records — a rebuildable derived index, never canonical truth.
 *   Ranking via bm25() with column weights (subject > tags > content).
 *   unicode61 tokenizer: case-insensitive, no stemming — exact-term search
 *   with per-hit explanations and query diagnostics.
 *   Research: pattern ADAPTED from mem0's multi-signal retrieval (BM25
 *   keyword signal; semantic + entity signals DEFERRED — no provider);
 *   FTS5 behaviors per sqlite.org/fts5.html (accessed 2026-08-30).
 * - Temporal retrieval (Task 16): explicit validity semantics answering
 *   "current records", "what was true at T" (as-of), and "how did this
 *   decision evolve" (timeline). Pattern ADAPTED from getzep/graphiti
 *   temporal validity windows (main @ 2026-08-30).
 */
import type { MemoryRecord } from "../contracts/types.ts";
import { ValidationError } from "../contracts/errors.ts";
import { rowToRecord } from "./records.ts";
import { getScopeImpl } from "./scopes.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import type { MemoryStore } from "./store.ts";

/** Column weights: subject matters most, then tags, then content. */
const FTS_WEIGHTS = [5.0, 1.0, 3.0] as const;

export interface LexicalSearchFilter {
  scope?: string;
  /** Status filter; default view excludes tombstones ("all" includes). */
  status?: MemoryRecord["status"] | "all";
  limit?: number;
}

export interface LexicalHit {
  record: MemoryRecord;
  /** BM25 relevance, positive = better (negated FTS5 bm25()). */
  score: number;
  /** Exact-term explanation: which indexed fields matched. */
  explanation: {
    subjectMatched: boolean;
    contentMatched: boolean;
    tagsMatched: boolean;
    snippet: string;
  };
}

export interface LexicalSearchResult {
  query: string;
  /** Deterministic tokenization of the query (the actual MATCH terms). */
  terms: string[];
  hits: LexicalHit[];
  diagnostics: {
    totalMatches: number;
    tokenizer: "unicode61";
    indexMode: "fts5-external-content";
    truncated: boolean;
  };
}

/**
 * Extract bareword tokens from a free-text query and build a safe FTS5
 * MATCH expression: each token is quoted (no FTS5 syntax injection) and
 * terms are combined with implicit AND.
 */
export function buildFtsQuery(query: string): string[] {
  if (typeof query !== "string" || query.trim().length === 0) {
    throw new ValidationError("query must be a non-empty string");
  }
  const tokens = query
    .split(/[^\p{L}\p{N}_]+/u)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  if (tokens.length === 0) {
    throw new ValidationError("query contains no searchable terms");
  }
  return tokens;
}

export function lexicalSearchImpl(
  store: MemoryStore,
  query: string,
  filter: LexicalSearchFilter = {},
): LexicalSearchResult {
  const terms = buildFtsQuery(query);
  const matchExpression = terms.map((t) => `"${t}"`).join(" ");
  const db = store.ensureOpen();

  const clauses = ["memory_fts MATCH ?"];
  const params: Array<string | number> = [matchExpression];
  if (filter.status !== undefined && filter.status !== "all") {
    clauses.push("memory_records.status = ?");
    params.push(filter.status);
  } else if (filter.status === undefined) {
    clauses.push("memory_records.status != 'deleted'");
  }
  if (filter.scope !== undefined) {
    const scope = getScopeImpl(store, filter.scope);
    clauses.push("memory_records.scope_id = ?");
    params.push(scope.scopeId);
  }
  const limit = Math.min(Math.max(filter.limit ?? 20, 1), 100);

  const rows = db
    .prepare(
      `SELECT memory_records.*,
              bm25(memory_fts, ${FTS_WEIGHTS.join(", ")}) AS bm25_score,
              highlight(memory_fts, 0, '<', '>') AS hl_subject,
              highlight(memory_fts, 1, '<', '>') AS hl_content,
              highlight(memory_fts, 2, '<', '>') AS hl_tags,
              snippet(memory_fts, 1, '<', '>', '…', 16) AS snippet
       FROM memory_fts JOIN memory_records ON memory_records.rowid = memory_fts.rowid
       WHERE ${clauses.join(" AND ")}
       ORDER BY bm25_score ASC
       LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;

  const totalRow = db
    .prepare(
      `SELECT COUNT(*) AS n FROM memory_fts JOIN memory_records ON memory_records.rowid = memory_fts.rowid
       WHERE ${clauses.join(" AND ")}`,
    )
    .get(...params) as Record<string, unknown>;

  const hits: LexicalHit[] = rows.map((row) => {
    const hlSubject = String(row["hl_subject"] ?? "");
    const hlContent = String(row["hl_content"] ?? "");
    const hlTags = String(row["hl_tags"] ?? "");
    const rawScore = Number(row["bm25_score"]);
    return {
      record: rowToRecord(row),
      score: Number.isFinite(rawScore) ? -rawScore : 0,
      explanation: {
        subjectMatched: hlSubject.includes("<"),
        contentMatched: hlContent.includes("<"),
        tagsMatched: hlTags.includes("<"),
        snippet: String(row["snippet"] ?? "").replace(/[<>]/g, ""),
      },
    };
  });

  return {
    query,
    terms,
    hits,
    diagnostics: {
      totalMatches: Number(totalRow["n"]),
      tokenizer: "unicode61",
      indexMode: "fts5-external-content",
      truncated: Number(totalRow["n"]) > hits.length,
    },
  };
}

/**
 * Rebuild the lexical index from canonical memory_records — the index is a
 * discardable derived artifact; this is the recovery path.
 */
export function rebuildSearchIndexImpl(store: MemoryStore): { rebuilt: true } {
  const db = store.ensureOpen();
  db.exec("INSERT INTO memory_fts(memory_fts) VALUES ('rebuild')");
  store.appendEvent("memory.index.rebuilt", { index: "memory_fts" });
  return { rebuilt: true };
}

// ---- Task 16: temporal retrieval -------------------------------------------

export interface CurrentQuery {
  scope: string;
  /** Optional exact subject filter ("the current decision about X"). */
  subject?: string;
  /** Instant to resolve "current" at; defaults to now. */
  at?: string;
  limit?: number;
}

/** Shared clause/param builder for the current-view query. */
function buildCurrentClauses(
  store: MemoryStore,
  query: CurrentQuery,
  at: string,
): { clauses: string[]; params: Array<string | number> } {
  const scope = getScopeImpl(store, query.scope);
  const clauses = [
    "scope_id = ?",
    "status = 'active'",
    "(valid_from IS NULL OR valid_from <= ?)",
    "(valid_until IS NULL OR valid_until > ?)",
  ];
  const params: Array<string | number> = [scope.scopeId, at, at];
  if (query.subject !== undefined) {
    clauses.push("subject = ?");
    params.push(query.subject);
  }
  return { clauses, params };
}

/** "What is the current decision/knowledge?" — validity-aware active view. */
export function currentRecordsImpl(
  store: MemoryStore,
  query: CurrentQuery,
): MemoryRecord[] {
  const at = query.at ?? new Date().toISOString();
  assertIsoTimestamp(at, "at");
  const db = store.ensureOpen();
  const { clauses, params } = buildCurrentClauses(store, query, at);
  const limit = Math.min(Math.max(query.limit ?? 100, 1), 1000);
  const rows = db
    .prepare(
      `SELECT * FROM memory_records WHERE ${clauses.join(" AND ")}
       ORDER BY observed_at DESC, record_id DESC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  return rows.map(rowToRecord);
}

// ---- Task 20: retrieval trace for the current-view query -------------------

export interface CurrentMatchReason {
  filter: string;
  reason: string;
}

export interface CurrentTrace {
  appliedFilters: Record<string, unknown>;
  at: string;
  totalMatches: number;
  truncated: boolean;
  matches: Record<string, CurrentMatchReason[]>;
}

function explainCurrentMatch(
  query: CurrentQuery,
  record: MemoryRecord,
  at: string,
): CurrentMatchReason[] {
  const reasons: CurrentMatchReason[] = [
    { filter: "status", reason: `status '${record.status}' === 'active'` },
    {
      filter: "validFrom",
      reason:
        record.validFrom === null
          ? "validFrom is null (open start)"
          : `validFrom '${record.validFrom}' <= at '${at}'`,
    },
    {
      filter: "validUntil",
      reason:
        record.validUntil === null
          ? "validUntil is null (open end)"
          : `validUntil '${record.validUntil}' > at '${at}'`,
    },
  ];
  if (query.subject !== undefined) {
    reasons.push({ filter: "subject", reason: `subject '${record.subject}' === '${query.subject}'` });
  }
  return reasons;
}

/** Task 20: `currentRecordsImpl`, plus which filters applied and why each record matched. */
export function currentRecordsTracedImpl(
  store: MemoryStore,
  query: CurrentQuery,
): { records: MemoryRecord[]; trace: CurrentTrace } {
  const at = query.at ?? new Date().toISOString();
  assertIsoTimestamp(at, "at");
  const db = store.ensureOpen();
  const { clauses, params } = buildCurrentClauses(store, query, at);
  const limit = Math.min(Math.max(query.limit ?? 100, 1), 1000);
  const where = `WHERE ${clauses.join(" AND ")}`;
  const rows = db
    .prepare(
      `SELECT * FROM memory_records ${where} ORDER BY observed_at DESC, record_id DESC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  const records = rows.map(rowToRecord);
  const totalRow = db
    .prepare(`SELECT COUNT(*) AS n FROM memory_records ${where}`)
    .get(...params) as Record<string, unknown>;
  const totalMatches = Number(totalRow["n"]);
  const matches: Record<string, CurrentMatchReason[]> = {};
  for (const record of records) {
    matches[record.recordId] = explainCurrentMatch(query, record, at);
  }
  const appliedFilters: Record<string, unknown> = {};
  if (query.subject !== undefined) appliedFilters["subject"] = query.subject;
  return {
    records,
    trace: { appliedFilters, at, totalMatches, truncated: totalMatches > records.length, matches },
  };
}

export interface TimelineEntry {
  recordId: string;
  /** When this version of the claim held (valid time). */
  observedAt: string;
  /** When the store learned it (transaction time). */
  createdAt: string;
  status: MemoryRecord["status"];
  content: string;
  supersedesId: string | null;
  supersededAt: string | null;
  supersededReason: string | null;
}

/**
 * "How did the decision about X change across time?" — the full evolution
 * of a subject: every non-deleted record with the exact subject, ordered
 * oldest → newest by valid time, including invalidated versions and the
 * explicit reasons they were retired.
 */
export function decisionTimelineImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  subject: string,
): TimelineEntry[] {
  if (typeof subject !== "string" || subject.trim().length === 0) {
    throw new ValidationError("subject is required for a decision timeline");
  }
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const db = store.ensureOpen();
  const rows = db
    .prepare(
      `SELECT record_id, observed_at, created_at, status, content,
              supersedes_id, superseded_at, supersede_reason
       FROM memory_records
       WHERE scope_id = ? AND subject = ? AND status != 'deleted'
       ORDER BY COALESCE(valid_from, observed_at) ASC, created_at ASC, record_id ASC`,
    )
    .all(scope.scopeId, subject) as Array<Record<string, unknown>>;
  return rows.map((row) => ({
    recordId: String(row["record_id"]),
    observedAt: String(row["observed_at"]),
    createdAt: String(row["created_at"]),
    status: String(row["status"]) as MemoryRecord["status"],
    content: String(row["content"]),
    supersedesId: row["supersedes_id"] === null ? null : String(row["supersedes_id"]),
    supersededAt: row["superseded_at"] === null ? null : String(row["superseded_at"]),
    supersededReason:
      row["supersede_reason"] === null || row["supersede_reason"] === undefined
        ? null
        : String(row["supersede_reason"]),
  }));
}
