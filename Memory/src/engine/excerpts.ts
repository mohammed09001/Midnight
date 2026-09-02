/**
 * Context-safe memory excerpts (Task 36).
 *
 * Returns BOUNDED excerpts or structured facts suitable for Context Packs
 * WITHOUT leaking restricted source payloads:
 *
 * - Bounded: `maxExcerpts` caps the pack; `maxContentChars` bounds each
 *   excerpt (over-long content is ellipsized and flagged `truncated`).
 * - Privacy-safe: `sensitive` records are EXCLUDED by default (opt-in
 *   `includeSensitive`), consistent with the embedding privacy gate; source
 *   payloads are never included — excerpts carry the Memory statement plus
 *   provenance METADATA (sourceKind/authority/validity), never evidence
 *   payloads (evidence stays by reference only). Tombstoned records are
 *   excluded.
 * - Structured facts: each excerpt is a bounded, structured fact suitable for
 *   a Context Pack: recordId, subject, excerpted content, tags, sourceKind,
 *   authority tier, validity-at-instant, confidence, privacyClass.
 *
 * Deterministic, provider-free; `memoryExcerpt` redacts sensitive content
 * rather than leaking it.
 */
import { PrivacyViolationError, ValidationError } from "../contracts/errors.ts";
import type {
  AuthorityTier,
  MemoryRecord,
  PrivacyClass,
  RecordKind,
  SourceKind,
} from "../contracts/types.ts";
import { authorityOf } from "./authority.ts";
import { AUTHORITY_TIER_VALUE } from "./ranking.ts";
import { rowToRecord } from "./records.ts";
import { getScopeImpl } from "./scopes.ts";
import { getContentPolicy, checkExportable } from "./privacy.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import type { MemoryStore } from "./store.ts";

export const DEFAULT_MAX_EXCERPTS = 20;
export const MAX_EXCERPTS_LIMIT = 100;
export const DEFAULT_MAX_CONTENT_CHARS = 200;
export const MIN_CONTENT_CHARS = 20;

const ELLIPSIS = "…";

export interface ContextExcerpt {
  recordId: string;
  subject: string;
  /** Bounded excerpt of the record content (ellipsized when over-length). */
  content: string;
  /** True when the source content exceeded `maxContentChars`. */
  truncated: boolean;
  /** Task 38: stored content is untrusted DATA — never policy/instructions. */
  trust: "untrusted-data";
  tags: string[];
  sourceKind: SourceKind;
  authorityTier: AuthorityTier;
  currentlyValid: boolean;
  confidence: number;
  privacyClass: Exclude<PrivacyClass, "secret">;
}

export interface ExcerptPack {
  scopeId: string;
  builtAt: string;
  maxExcerpts: number;
  maxContentChars: number;
  excerpts: ContextExcerpt[];
  /** Records skipped because they are `sensitive` and not opted in. */
  skippedSensitive: number;
  diagnostics: { totalMatches: number; truncated: boolean };
}

export interface ContextExcerptQuery {
  scope: string;
  at?: string;
  maxExcerpts?: number;
  maxContentChars?: number;
  /** Privacy gate: include `sensitive` records. Default false. */
  includeSensitive?: boolean;
  sourceKinds?: SourceKind[];
  kinds?: RecordKind[];
  minConfidence?: number;
  minAuthority?: AuthorityTier;
}

function currentlyValid(record: MemoryRecord, at: string): boolean {
  return (
    record.status === "active" &&
    (record.validFrom === null || record.validFrom <= at) &&
    (record.validUntil === null || record.validUntil > at)
  );
}

function excerptContent(content: string, maxChars: number): { content: string; truncated: boolean } {
  if (content.length <= maxChars) return { content, truncated: false };
  return { content: `${content.slice(0, maxChars)}${ELLIPSIS}`, truncated: true };
}

function recordsExcludedByPolicy(
  db: { prepare(sql: string): { all(...p: unknown[]): Array<Record<string, unknown>> } },
  scopeId: string,
  policy: ReturnType<typeof getContentPolicy>,
): number {
  const rows = db
    .prepare("SELECT privacy_class FROM memory_records WHERE scope_id = ? AND status != 'deleted'")
    .all(scopeId) as Array<Record<string, unknown>>;
  return rows.filter((r) => !checkExportable({ privacyClass: String(r["privacy_class"]) as "public" | "internal" | "sensitive" }, policy).exportable).length;
}

function toExcerpt(record: MemoryRecord, at: string, maxChars: number): ContextExcerpt {
  const excerpt = excerptContent(record.content, maxChars);
  return {
    recordId: record.recordId,
    subject: record.subject,
    content: excerpt.content,
    truncated: excerpt.truncated,
    trust: "untrusted-data",
    tags: [...record.tags],
    sourceKind: record.provenance.sourceKind,
    authorityTier: authorityOf(record.provenance, record.epistemicClass).tier,
    currentlyValid: currentlyValid(record, at),
    confidence: record.confidence,
    privacyClass: record.privacyClass,
  };
}

/**
 * Build a bounded, context-safe excerpt pack for a scope. Privacy gate:
 * `sensitive` records are excluded unless `includeSensitive`. Source payloads
 * never leak — only the Memory statement + provenance metadata are returned.
 */
export function buildContextExcerptsImpl(
  store: MemoryStore,
  query: ContextExcerptQuery,
): ExcerptPack {
  const scope = getScopeImpl(store, query.scope);
  const at = query.at ?? new Date().toISOString();
  assertIsoTimestamp(at, "at");
  if (query.minConfidence !== undefined && (query.minConfidence < 0 || query.minConfidence > 1)) {
    throw new ValidationError("minConfidence must be in [0,1]");
  }
  const maxExcerpts = Math.min(Math.max(query.maxExcerpts ?? DEFAULT_MAX_EXCERPTS, 1), MAX_EXCERPTS_LIMIT);
  const maxContentChars = Math.max(query.maxContentChars ?? DEFAULT_MAX_CONTENT_CHARS, MIN_CONTENT_CHARS);
  const includeSensitive = query.includeSensitive === true;
  const db = store.ensureOpen();

  const clauses = [
    "r.scope_id = ?",
    "r.status != 'deleted'",
    "(r.valid_from IS NULL OR r.valid_from <= ?)",
    "(r.valid_until IS NULL OR r.valid_until > ?)",
    "r.status != 'retracted'",
  ];
  const params: Array<string | number> = [scope.scopeId, at, at];
  // Task 37: content-class policy — sensitive is excluded unless opted in and
  // not forbidden; non-exportable classes are filtered post-query.
  const policy = getContentPolicy(store, scope.scopeId);
  if (!includeSensitive || policy.content.forbidSensitive) {
    clauses.push("r.privacy_class != 'sensitive'");
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

  const totalRow = db
    .prepare(`SELECT COUNT(*) AS n FROM memory_records r WHERE ${clauses.join(" AND ")}`)
    .get(...params) as Record<string, unknown>;
  const totalMatches = Number(totalRow["n"]);

  const rows = db
    .prepare(
      `SELECT r.* FROM memory_records r WHERE ${clauses.join(" AND ")}
       ORDER BY r.observed_at DESC, r.record_id DESC LIMIT ?`,
    )
    .all(...params, Math.min(totalMatches, 500)) as Array<Record<string, unknown>>;

  const minAuthorityValue =
    query.minAuthority !== undefined ? (AUTHORITY_TIER_VALUE[query.minAuthority] ?? 0) : undefined;

  let records = rows.map(rowToRecord);
  if (minAuthorityValue !== undefined) {
    records = records.filter((r) => (AUTHORITY_TIER_VALUE[authorityOf(r.provenance, r.epistemicClass).tier] ?? 0) >= minAuthorityValue);
  }
  // Task 37: content-class policy — only exportable records may be excerpted.
  records = records.filter((r) => checkExportable(r, policy, includeSensitive).exportable);
  const skippedSensitive = recordsExcludedByPolicy(db, scope.scopeId, policy);

  // Deterministic context ordering: current → authority → recency.
  records.sort((a, b) => {
    const av = currentlyValid(a, at);
    const bv = currentlyValid(b, at);
    if (av !== bv) return av ? -1 : 1;
    const ava = AUTHORITY_TIER_VALUE[authorityOf(a.provenance, a.epistemicClass).tier] ?? 0;
    const bva = AUTHORITY_TIER_VALUE[authorityOf(b.provenance, b.epistemicClass).tier] ?? 0;
    if (ava !== bva) return bva - ava;
    if (a.observedAt !== b.observedAt) return a.observedAt < b.observedAt ? 1 : -1;
    return a.recordId < b.recordId ? 1 : -1;
  });

  const excerpts = records.slice(0, maxExcerpts).map((r) => toExcerpt(r, at, maxContentChars));

  return {
    scopeId: scope.scopeId,
    builtAt: new Date().toISOString(),
    maxExcerpts,
    maxContentChars,
    excerpts,
    skippedSensitive,
    diagnostics: { totalMatches, truncated: totalMatches > excerpts.length },
  };
}

export interface MemoryExcerptOptions {
  at?: string;
  maxContentChars?: number;
  /** Privacy gate: allow revealing `sensitive` content. Default false (redacted). */
  includeSensitive?: boolean;
}

/**
 * A single-record context-safe excerpt. Sensitive content is REDACTED by
 * default rather than leaked; `includeSensitive` explicitly opts in.
 */
export function memoryExcerptImpl(
  store: MemoryStore,
  recordId: string,
  options: MemoryExcerptOptions = {},
): ContextExcerpt {
  const db = store.ensureOpen();
  const row = db.prepare("SELECT * FROM memory_records WHERE record_id = ?").get(recordId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new ValidationError(`Record '${recordId}' not found`);
  }
  const record = rowToRecord(row);
  if (record.status === "deleted") {
    throw new PrivacyViolationError("tombstoned records cannot be excerpted (content is scrubbed)");
  }
  const includeSensitive = options.includeSensitive === true;
  if (record.privacyClass === "sensitive" && !includeSensitive) {
    // Redact rather than leak restricted content into a context pack.
    return {
      recordId: record.recordId,
      subject: record.subject,
      content: "[sensitive content excluded]",
      truncated: false,
      trust: "untrusted-data",
      tags: [...record.tags],
      sourceKind: record.provenance.sourceKind,
      authorityTier: authorityOf(record.provenance, record.epistemicClass).tier,
      currentlyValid: currentlyValid(record, options.at ?? new Date().toISOString()),
      confidence: record.confidence,
      privacyClass: record.privacyClass,
    };
  }
  return toExcerpt(record, options.at ?? new Date().toISOString(), Math.max(options.maxContentChars ?? DEFAULT_MAX_CONTENT_CHARS, MIN_CONTENT_CHARS));
}