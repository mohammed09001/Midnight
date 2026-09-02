/**
 * Retention, archival, and deletion semantics (Task 13).
 *
 * Lifecycle states: active → archived (cold, restorable) / superseded /
 * retracted / expired → deleted (tombstone: content scrubbed, row and
 * lineage retained). The ONLY hard delete is the privacy purge, which
 * removes the record row, its revision log, and every inbound pointer —
 * attributed, reasoned, and event-logged; never performed by agents.
 *
 * Source-evidence expiry: records reference evidence BY REFERENCE in other
 * engines. When that source expires, the record SURVIVES (memory is
 * durable and never silently invalidated) but its verifiability degrades:
 * expired evidence is flagged on read and reported by a sweep.
 */
import { ConflictError, CorrectionForbiddenError, NotFoundError, ValidationError } from "../contracts/errors.ts";
import type {
  EvidenceRef,
  MemoryRecord,
  PrivacyClass,
} from "../contracts/types.ts";
import { actorKey } from "./ids.ts";
import { getRecordImpl, rowToRecord } from "./records.ts";
import { getScopeImpl } from "./scopes.ts";
import { assertMutationAuthorized, withOrigin } from "./authorization.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import type { MemoryStore } from "./store.ts";

const TOMBSTONE_HASH = "tombstoned";

function requireReason(reason: unknown, what: string): string {
  if (typeof reason !== "string" || reason.trim().length === 0) {
    throw new ValidationError(`reason is required for ${what}`);
  }
  return reason.trim();
}

function refuseAgents(kind: string, what: string): void {
  if (kind === "agent") {
    throw new CorrectionForbiddenError(
      `actors of kind 'agent' cannot ${what}: lifecycle decisions belong to users or authorized engines`,
    );
  }
}

/** Task 13: archive — cold storage, excluded from current views, restorable. */
export function archiveRecordImpl(
  store: MemoryStore,
  recordId: string,
  input: { actor: { kind: string; name: string }; reason: string; origin?: string },
): MemoryRecord {
  const reason = requireReason(input.reason, "archiving");
  const record = getRecordImpl(store, recordId);
  // Task 35: an explicit restricted policy may authorize a specific agent.
  const authorized = assertMutationAuthorized(store, record.scopeId, input.actor, "archive");
  if (!authorized) refuseAgents(input.actor.kind, "archive records");
  if (record.status !== "active") {
    throw new ConflictError(
      `Record '${recordId}' is '${record.status}'; only active records can be archived`,
    );
  }
  const now = new Date().toISOString();
  store.ensureOpen()
    .prepare("UPDATE memory_records SET status = 'archived', archived_at = ?, revised_at = ? WHERE record_id = ?")
    .run(now, now, recordId);
  store.appendEvent("memory.record.archived", withOrigin({ recordId, actor: actorKey(input.actor as never), reason }, input.origin));
  return getRecordImpl(store, recordId);
}

/** Task 13: restore an archived record to active. */
export function restoreRecordImpl(
  store: MemoryStore,
  recordId: string,
  input: { actor: { kind: string; name: string }; reason: string; origin?: string },
): MemoryRecord {
  const reason = requireReason(input.reason, "restoring");
  const record = getRecordImpl(store, recordId);
  const authorized = assertMutationAuthorized(store, record.scopeId, input.actor, "restore");
  if (!authorized) refuseAgents(input.actor.kind, "restore records");
  if (record.status !== "archived") {
    throw new ConflictError(
      `Record '${recordId}' is '${record.status}'; only archived records can be restored`,
    );
  }
  const now = new Date().toISOString();
  store.ensureOpen()
    .prepare("UPDATE memory_records SET status = 'active', archived_at = NULL, revised_at = ? WHERE record_id = ?")
    .run(now, recordId);
  store.appendEvent("memory.record.restored", withOrigin({ recordId, actor: actorKey(input.actor as never), reason }, input.origin));
  return getRecordImpl(store, recordId);
}

/**
 * Task 13: tombstone deletion — the record's payload is scrubbed, but the
 * row, its identity, and its lineage pointers remain so chains and events
 * stay coherent. Tombstoned records are excluded from all views.
 */
export function deleteRecordImpl(
  store: MemoryStore,
  recordId: string,
  input: { actor: { kind: string; name: string }; reason: string; origin?: string },
): MemoryRecord {
  const reason = requireReason(input.reason, "deletion");
  const record = getRecordImpl(store, recordId);
  const authorized = assertMutationAuthorized(store, record.scopeId, input.actor, "delete");
  if (!authorized) refuseAgents(input.actor.kind, "delete records");
  if (record.status === "deleted") {
    throw new ConflictError(`Record '${recordId}' is already deleted`);
  }
  const now = new Date().toISOString();
  const db = store.ensureOpen();
  db.prepare(
    `UPDATE memory_records SET
       status = 'deleted', content = '', content_hash = ?,
       evidence_json = '[]', relation_hints_json = '[]', tags_json = '[]',
       valid_from = NULL, valid_until = NULL,
       deleted_at = ?, deleted_by = ?, delete_reason = ?, revised_at = ?
     WHERE record_id = ?`,
  ).run(TOMBSTONE_HASH, now, actorKey(input.actor as never), reason, now, recordId);
  // Task 45: tombstone scrubs the content — the derived vector of the
  // scrubbed content must not persist or rank (deletion propagates to the
  // derived embedding store; the lexical index re-indexes via triggers).
  db.prepare("DELETE FROM memory_embeddings WHERE record_id = ?").run(recordId);
  store.appendEvent("memory.record.deleted", withOrigin({
    recordId,
    actor: actorKey(input.actor as never),
    reason,
    mode: "tombstone",
  }, input.origin));
  return getRecordImpl(store, recordId);
}

/** Clean every pointer another row holds toward a purged record id. */
function scrubPointersTo(store: MemoryStore, recordId: string): void {
  const db = store.ensureOpen();
  // Self/lineage FKs on other records.
  db.prepare("UPDATE memory_records SET supersedes_id = NULL WHERE supersedes_id = ?").run(recordId);
  db.prepare("UPDATE memory_records SET superseded_by_id = NULL WHERE superseded_by_id = ?").run(recordId);
  // Candidate promotion pointers.
  db.prepare("UPDATE memory_candidates SET promoted_record_id = NULL WHERE promoted_record_id = ?").run(recordId);
  // Relation hints held by other records in the same scope.
  const holders = db
    .prepare("SELECT record_id, relation_hints_json FROM memory_records WHERE relation_hints_json LIKE ?")
    .all(`%${recordId}%`) as Array<Record<string, unknown>>;
  for (const row of holders) {
    const hints = JSON.parse(String(row["relation_hints_json"])) as Array<{ target: string }>;
    const filtered = JSON.stringify(hints.filter((h) => h.target !== recordId));
    db.prepare("UPDATE memory_records SET relation_hints_json = ? WHERE record_id = ?").run(
      filtered,
      String(row["record_id"]),
    );
  }
  // Contradiction group membership.
  const groups = db
    .prepare("SELECT group_id, record_ids FROM contradiction_groups WHERE record_ids LIKE ?")
    .all(`%${recordId}%`) as Array<Record<string, unknown>>;
  for (const row of groups) {
    const ids = JSON.parse(String(row["record_ids"])) as string[];
    const filtered = JSON.stringify(ids.filter((id) => id !== recordId));
    db.prepare("UPDATE contradiction_groups SET record_ids = ? WHERE group_id = ?").run(
      filtered,
      String(row["group_id"]),
    );
  }
}

/**
 * Task 13: privacy-driven HARD deletion — removes the record row, its
 * entire revision log, and all inbound pointers. The only true deletion in
 * the engine. Content never appears in the event stream.
 */
export function purgeRecordImpl(
  store: MemoryStore,
  recordId: string,
  input: { actor: { kind: string; name: string }; reason: string; origin?: string },
): { purged: boolean } {
  const reason = requireReason(input.reason, "purging");
  const record = getRecordImpl(store, recordId); // 404s if absent
  const authorized = assertMutationAuthorized(store, record.scopeId, input.actor, "purge");
  if (!authorized) refuseAgents(input.actor.kind, "purge records");
  const db = store.ensureOpen();
  db.exec("BEGIN IMMEDIATE;");
  try {
    scrubPointersTo(store, recordId);
    // Task 45: the privacy purge propagates to the derived embedding store —
    // no trace of the purged content may persist in rebuildable state either.
    db.prepare("DELETE FROM memory_embeddings WHERE record_id = ?").run(recordId);
    db.prepare("DELETE FROM memory_record_revisions WHERE record_id = ?").run(recordId);
    db.prepare("DELETE FROM memory_records WHERE record_id = ?").run(recordId);
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }
  store.appendEvent("memory.record.purged", withOrigin({
    recordId,
    scopeId: record.scopeId,
    actor: actorKey(input.actor as never),
    reason,
  }, input.origin));
  return { purged: true };
}

/** True when a single evidence ref carries an expiresAt earlier than `at`. */
export function isEvidenceRefExpired(ref: EvidenceRef, at: string): boolean {
  if (ref.expiresAt === undefined) return false;
  const t = Date.parse(at);
  if (Number.isNaN(t)) throw new ValidationError("at must be an ISO 8601 timestamp");
  const exp = Date.parse(ref.expiresAt);
  return !Number.isNaN(exp) && exp < t;
}

/** True when every evidence ref of the record carries an expiresAt < at. */
export function evidenceAllExpired(record: MemoryRecord, at: string): boolean {
  if (record.evidenceRefs.length === 0) return false;
  return record.evidenceRefs.every((ref) => isEvidenceRefExpired(ref, at));
}

/** Task 13: records whose source evidence has fully lapsed at `at`. */
export function listEvidenceExpiredImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  at: string,
): MemoryRecord[] {
  assertIsoTimestamp(at, "at");
  const db = store.ensureOpen();
  const scopeInfo = getScopeImpl(store, scopeOrProjectKey);
  const rows = db
    .prepare(
      `SELECT * FROM memory_records
       WHERE scope_id = ? AND status IN ('active','archived') AND evidence_json LIKE '%expiresAt%'`,
    )
    .all(scopeInfo.scopeId) as Array<Record<string, unknown>>;
  return rows.map(rowToRecord).filter((r) => evidenceAllExpired(r, at));
}

/**
 * Task 13: sweep — emit an observability event listing records whose
 * source evidence has expired. The records themselves are NOT mutated:
 * what happens next (retract/archive/re-verify) is a policy decision.
 */
export function sweepExpiredEvidenceImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  at: string,
): { expiredCount: number; recordIds: string[] } {
  const expired = listEvidenceExpiredImpl(store, scopeOrProjectKey, at);
  if (expired.length > 0) {
    store.appendEvent("memory.evidence.expired", {
      scopeId: expired[0]!.scopeId,
      recordIds: expired.map((r) => r.recordId),
      at,
    });
  }
  return { expiredCount: expired.length, recordIds: expired.map((r) => r.recordId) };
}

/**
 * Task 13: privacy-driven bulk purge — hard-delete every record of the
 * given privacy class(es) in a scope (or everywhere when scope omitted).
 */
export function purgeByPrivacyImpl(
  store: MemoryStore,
  input: {
    actor: { kind: string; name: string };
    reason: string;
    privacyClasses: Array<Exclude<PrivacyClass, "secret">>;
    scope?: string;
    origin?: string;
  },
): { purgedCount: number; recordIds: string[] } {
  refuseAgents(input.actor.kind, "purge records");
  const reason = requireReason(input.reason, "privacy purging");
  if (!Array.isArray(input.privacyClasses) || input.privacyClasses.length === 0) {
    throw new ValidationError("privacyClasses must list at least one class");
  }
  const db = store.ensureOpen();
  const clauses = input.privacyClasses.map(() => "privacy_class = ?").join(" OR ");
  const params: Array<string | number> = [...input.privacyClasses];
  let scopeFilter = "";
  if (input.scope !== undefined) {
    const scope = getScopeImpl(store, input.scope);
    scopeFilter = " AND scope_id = ?";
    params.push(scope.scopeId);
  }
  const targets = db
    .prepare(`SELECT record_id FROM memory_records WHERE (${clauses})${scopeFilter}`)
    .all(...params) as Array<Record<string, unknown>>;
  const ids = targets.map((r) => String(r["record_id"]));
  for (const id of ids) {
    purgeRecordImpl(store, id, { actor: input.actor, reason, origin: input.origin });
  }
  return { purgedCount: ids.length, recordIds: ids };
}
