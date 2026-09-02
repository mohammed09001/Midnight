/**
 * Search → Memory history (Task 30).
 *
 * Stores USEFUL SEARCH INTENT / SESSION HISTORY as retrieval context WITHOUT
 * promoting every candidate repository as durable knowledge. Search sessions
 * are an append-only, scoped log of search intents (by the Search engine) —
 * explicitly NOT durable records and NOT promotable candidates. Candidate
 * repositories surfaced by a search are recorded BY REFERENCE only and are
 * never promoted.
 *
 * - Append-oriented: sessions accumulate (like candidates/events); no delete,
 *   no TTL truth.
 * - Bounded: intent length and result/candidate ref counts are capped; list
 *   results are limited.
 * - Never promoted: recording a session never creates a record or a
 *   promotable candidate — the history is retrieval context only.
 * - Privacy: intents are stored as context; callers must not place secrets in
 *   intent text (secrets belong to the secure credential layer).
 */
import { NotFoundError, ValidationError } from "../contracts/errors.ts";
import type { Actor, EvidenceRef } from "../contracts/types.ts";
import { newId } from "./ids.ts";
import { getScopeImpl, assertScopeNotDeleted } from "./scopes.ts";
import { LIMITS, validateActor, validateEvidenceRef } from "./validation.ts";
import type { ActorInput } from "./records.ts";
import type { MemoryStore } from "./store.ts";

/** Bounded: max characters in a search intent. */
export const MAX_SEARCH_INTENT = 1024;
/** Bounded: max result refs per session. */
export const MAX_SEARCH_RESULT_REFS = 32;
/** Bounded: max candidate-repository refs per session. */
export const MAX_SEARCH_CANDIDATE_REFS = 32;

export interface SearchSessionInput {
  /** Scope (project key or scope id) the search ran in. */
  scope: string;
  /** The search intent/query (useful retrieval context). */
  intent: string;
  /** Who performed the search (optional). */
  actor?: ActorInput;
  /** When the search occurred (defaults to now). */
  observedAt?: string;
  /** Search results referenced BY REFERENCE (e.g. engine "repository_search"). */
  resultRefs?: EvidenceRef[];
  /** Candidate repositories surfaced — by reference, NEVER promoted to durable knowledge. */
  candidateRefs?: EvidenceRef[];
  /** Optional free-text note about the session. */
  note?: string;
}

export interface SearchSession {
  searchSessionId: string;
  scopeId: string;
  intent: string;
  actor: Actor | null;
  observedAt: string;
  createdAt: string;
  resultRefs: EvidenceRef[];
  candidateRefs: EvidenceRef[];
  note: string | null;
}

function requireIntent(intent: unknown): string {
  if (typeof intent !== "string" || intent.trim().length === 0) {
    throw new ValidationError("intent is required (the search intent/query to store as history)");
  }
  if (intent.trim().length > MAX_SEARCH_INTENT) {
    throw new ValidationError(`intent exceeds ${MAX_SEARCH_INTENT} characters`);
  }
  return intent.trim();
}

function validateRefs(value: unknown, field: string, max: number): EvidenceRef[] {
  const refs: EvidenceRef[] = [];
  if (value === undefined || value === null) return refs;
  if (!Array.isArray(value)) throw new ValidationError(`${field} must be an array`);
  if (value.length > max) throw new ValidationError(`${field} exceeds ${max} entries`);
  for (const [i, ref] of value.entries()) {
    refs.push(validateEvidenceRef(ref, `${field}[${i}]`));
  }
  return refs;
}

/** Append a search session as retrieval context (never a record or promotable candidate). */
export function recordSearchSessionImpl(store: MemoryStore, input: SearchSessionInput): SearchSession {
  const scope = getScopeImpl(store, input.scope);
  assertScopeNotDeleted(scope);
  const intent = requireIntent(input.intent);
  const observedAt = input.observedAt ?? new Date().toISOString();
  if (Number.isNaN(Date.parse(observedAt))) {
    throw new ValidationError("observedAt must be an ISO 8601 timestamp");
  }
  const actor = input.actor !== undefined ? validateActor(input.actor) : null;
  const resultRefs = validateRefs(input.resultRefs, "resultRefs", MAX_SEARCH_RESULT_REFS);
  const candidateRefs = validateRefs(input.candidateRefs, "candidateRefs", MAX_SEARCH_CANDIDATE_REFS);
  const note = input.note !== undefined && input.note !== null
    ? (() => {
        if (typeof input.note !== "string" || input.note.trim().length === 0) return null;
        if (input.note.trim().length > LIMITS.note) throw new ValidationError(`note exceeds ${LIMITS.note} characters`);
        return input.note.trim();
      })()
    : null;

  const db = store.ensureOpen();
  const searchSessionId = newId("ses");
  const createdAt = new Date().toISOString();
  db.prepare(
    `INSERT INTO memory_search_sessions (
       search_session_id, scope_id, intent, actor_json, observed_at, created_at,
       result_refs_json, candidate_refs_json, note
     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    searchSessionId,
    scope.scopeId,
    intent,
    actor === null ? null : JSON.stringify(actor),
    observedAt,
    createdAt,
    JSON.stringify(resultRefs),
    JSON.stringify(candidateRefs),
    note,
  );
  store.appendEvent("memory.search.session.recorded", {
    searchSessionId,
    scopeId: scope.scopeId,
    observedAt,
  });
  return {
    searchSessionId,
    scopeId: scope.scopeId,
    intent,
    actor,
    observedAt,
    createdAt,
    resultRefs,
    candidateRefs,
    note,
  };
}

/** List stored search-session history, newest first (retrieval context). */
export function listSearchSessionsImpl(
  store: MemoryStore,
  filter: { scope?: string; limit?: number } = {},
): SearchSession[] {
  const db = store.ensureOpen();
  const clauses: string[] = [];
  const params: Array<string | number> = [];
  if (filter.scope !== undefined) {
    const scope = getScopeImpl(store, filter.scope);
    clauses.push("scope_id = ?");
    params.push(scope.scopeId);
  }
  const limit = Math.min(Math.max(filter.limit ?? 100, 1), 1000);
  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const rows = db
    .prepare(
      `SELECT search_session_id, scope_id, intent, actor_json, observed_at, created_at,
              result_refs_json, candidate_refs_json, note
       FROM memory_search_sessions ${where} ORDER BY created_at DESC, search_session_id DESC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  return rows.map(rowToSession);
}

function rowToSession(row: Record<string, unknown>): SearchSession {
  const actorRaw = row["actor_json"];
  const note = row["note"];
  return {
    searchSessionId: String(row["search_session_id"]),
    scopeId: String(row["scope_id"]),
    intent: String(row["intent"]),
    actor:
      actorRaw === null || actorRaw === undefined
        ? null
        : (JSON.parse(String(actorRaw)) as Actor),
    observedAt: String(row["observed_at"]),
    createdAt: String(row["created_at"]),
    resultRefs: JSON.parse(String(row["result_refs_json"])) as EvidenceRef[],
    candidateRefs: JSON.parse(String(row["candidate_refs_json"])) as EvidenceRef[],
    note: note === null || note === undefined ? null : String(note),
  };
}

/** Look up a single session by id (typed not-found). */
export function getSearchSessionImpl(store: MemoryStore, searchSessionId: string): SearchSession {
  const db = store.ensureOpen();
  const row = db
    .prepare(
      `SELECT search_session_id, scope_id, intent, actor_json, observed_at, created_at,
              result_refs_json, candidate_refs_json, note
       FROM memory_search_sessions WHERE search_session_id = ?`,
    )
    .get(searchSessionId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new NotFoundError(`Search session '${searchSessionId}' not found`);
  }
  return rowToSession(row);
}