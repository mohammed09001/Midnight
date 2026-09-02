/**
 * Contradiction detection, grouping, and resolution (Task 10).
 *
 * Detects explicit incompatible claims within overlapping scope/time:
 * same normalized subject + different content, both currently meaningful,
 * with overlapping validity windows. Both claims are PRESERVED as a
 * contradiction set pending policy or user resolution — the engine never
 * silently picks a winner (deterministic detection; resolution is an
 * attributed decision, agents refused).
 *
 * Research notes: deterministic detection + preserved history ADAPTED from
 * getzep/graphiti's contradiction handling (main @ 2026-08-30); LLM-judged
 * auto-resolution REJECTED. Conflict-pending-resolution model ADAPTED from
 * dolthub/dolt's merge-conflicts semantics (main @ 2026-08-30); Dolt itself
 * (branches/merge as V1 store) REJECTED as over-accumulation.
 */
import { ConflictError, NotFoundError, PromotionForbiddenError, ValidationError } from "../contracts/errors.ts";
import type {
  ContradictionGroup,
  ContradictionPair,
  ContradictionResolution,
  MemoryRecord,
} from "../contracts/types.ts";
import { actorKey, newId } from "./ids.ts";
import { getRecordImpl } from "./records.ts";
import { getScopeImpl } from "./scopes.ts";
import { assertMutationAuthorized, withOrigin } from "./authorization.ts";
import type { MemoryStore } from "./store.ts";

function groupRowToGroup(row: Record<string, unknown>): ContradictionGroup {
  const resolutionRaw = row["resolution_json"];
  return {
    groupId: String(row["group_id"]),
    scopeId: String(row["scope_id"]),
    subject: String(row["subject"]),
    recordIds: JSON.parse(String(row["record_ids"])) as string[],
    createdAt: String(row["created_at"]),
    status: String(row["status"] ?? "open") as ContradictionGroup["status"],
    resolution:
      resolutionRaw === null || resolutionRaw === undefined
        ? null
        : (JSON.parse(String(resolutionRaw)) as ContradictionResolution),
  };
}

function getGroupImpl(store: MemoryStore, groupId: string): ContradictionGroup {
  const db = store.ensureOpen();
  const row = db
    .prepare(
      `SELECT group_id, scope_id, subject, record_ids, created_at, status, resolution_json
       FROM contradiction_groups WHERE group_id = ?`,
    )
    .get(groupId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new NotFoundError(`Contradiction group '${groupId}' not found`);
  }
  return groupRowToGroup(row);
}

/** Task 20: non-throwing lookup for callers explaining a record's membership. */
export function getContradictionGroupOrNull(
  store: MemoryStore,
  groupId: string,
): ContradictionGroup | null {
  const db = store.ensureOpen();
  const row = db
    .prepare(
      `SELECT group_id, scope_id, subject, record_ids, created_at, status, resolution_json
       FROM contradiction_groups WHERE group_id = ?`,
    )
    .get(groupId) as Record<string, unknown> | undefined;
  return row === undefined ? null : groupRowToGroup(row);
}

/**
 * Register a contradiction group explicitly from known record ids.
 * (Kept as the grouping primitive used by detection consumers.)
 */
export function registerContradictionImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  subject: string,
  recordIds: string[],
): ContradictionGroup {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  if (!Array.isArray(recordIds) || recordIds.length < 2) {
    throw new ValidationError("registerContradiction requires at least 2 record ids");
  }
  if (typeof subject !== "string" || subject.trim().length === 0) {
    throw new ValidationError("subject is required");
  }
  const db = store.ensureOpen();
  const uniqueIds = [...new Set(recordIds)];
  const now = new Date().toISOString();
  const groupId = newId("ctg");
  db.exec("BEGIN IMMEDIATE;");
  try {
    for (const recordId of uniqueIds) {
      const row = db
        .prepare("SELECT scope_id, status FROM memory_records WHERE record_id = ?")
        .get(recordId) as Record<string, unknown> | undefined;
      if (row === undefined) {
        throw new NotFoundError(`Record '${recordId}' not found`);
      }
      if (String(row["scope_id"]) !== scope.scopeId) {
        throw new ValidationError(
          `Record '${recordId}' is not in scope '${scope.projectKey}'`,
        );
      }
    }
    db.prepare(
      `INSERT INTO contradiction_groups (group_id, scope_id, subject, record_ids, created_at, status)
       VALUES (?, ?, ?, ?, ?, 'open')`,
    ).run(groupId, scope.scopeId, subject.trim(), JSON.stringify(uniqueIds), now);
    for (const recordId of uniqueIds) {
      db.prepare(
        "UPDATE memory_records SET contradiction_group_id = ? WHERE record_id = ?",
      ).run(groupId, recordId);
    }
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }
  store.appendEvent("memory.contradiction.registered", {
    groupId,
    scopeId: scope.scopeId,
    subject: subject.trim(),
    recordIds: uniqueIds,
  });
  return {
    groupId,
    scopeId: scope.scopeId,
    subject: subject.trim(),
    recordIds: uniqueIds,
    createdAt: now,
    status: "open",
    resolution: null,
  };
}

/**
 * Deterministic detection of explicit incompatible claims: ACTIVE records
 * in the same scope sharing a normalized subject but differing in content,
 * whose validity windows overlap, excluding pairs already linked by
 * supersession or already grouped together.
 */
export function findContradictionPairsImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
): ContradictionPair[] {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const db = store.ensureOpen();
  const records = db
    .prepare(
      `SELECT record_id, subject, content_hash, valid_from, valid_until, observed_at,
              supersedes_id, contradiction_group_id
       FROM memory_records
       WHERE scope_id = ? AND status = 'active'`,
    )
    .all(scope.scopeId) as Array<Record<string, unknown>>;

  const mapped = records.map((row) => ({
    recordId: String(row["record_id"]),
    subject: String(row["subject"]),
    contentHash: String(row["content_hash"]),
    validFrom: row["valid_from"] === null ? null : String(row["valid_from"]),
    validUntil: row["valid_until"] === null ? null : String(row["valid_until"]),
    observedAt: String(row["observed_at"]),
    supersedesId: row["supersedes_id"] === null ? null : String(row["supersedes_id"]),
    groupId: row["contradiction_group_id"] === null ? null : String(row["contradiction_group_id"]),
  }));

  const byStart = (r: (typeof mapped)[number]) => r.validFrom ?? r.observedAt;
  const endOrInfinity = (r: (typeof mapped)[number]) => r.validUntil ?? "9999-12-31T23:59:59.999Z";

  const pairs: ContradictionPair[] = [];
  for (let i = 0; i < mapped.length; i++) {
    for (let j = i + 1; j < mapped.length; j++) {
      const a = mapped[i]!;
      const b = mapped[j]!;
      if (a.subject !== b.subject) continue;
      if (a.contentHash === b.contentHash) continue;
      // A supersession link is lineage, not a contradiction.
      if (a.supersedesId === b.recordId || b.supersedesId === a.recordId) continue;
      // Already grouped together → pending resolution, not a new pair.
      if (a.groupId !== null && a.groupId === b.groupId) continue;
      // Temporal overlap of validity windows (open bounds extend forever).
      const overlapStart = byStart(a) > byStart(b) ? byStart(a) : byStart(b);
      const overlapEnd = endOrInfinity(a) < endOrInfinity(b) ? endOrInfinity(a) : endOrInfinity(b);
      if (overlapStart >= overlapEnd) continue;
      pairs.push({
        scopeId: scope.scopeId,
        subject: a.subject,
        recordIdA: a.recordId,
        recordIdB: b.recordId,
        overlapStart,
        overlapEnd: overlapEnd === "9999-12-31T23:59:59.999Z" ? null : overlapEnd,
      });
    }
  }
  return pairs;
}

/** Open contradiction groups for a scope, oldest first. */
export function listOpenContradictionsImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
): ContradictionGroup[] {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const db = store.ensureOpen();
  const rows = db
    .prepare(
      `SELECT group_id, scope_id, subject, record_ids, created_at, status, resolution_json
       FROM contradiction_groups WHERE scope_id = ? AND status = 'open' ORDER BY created_at ASC, group_id ASC`,
    )
    .all(scope.scopeId) as Array<Record<string, unknown>>;
  return rows.map(groupRowToGroup);
}

export interface ContradictionResolutionInput {
  action: "supersede" | "retract";
  winnerRecordId: string;
  actor: { kind: string; name: string };
  reason: string;
  /** Task 35: surface that initiated the mutation (cli/contract/mcp/host). */
  origin?: string;
}

/**
 * Resolve an open contradiction group: either the winner supersedes the
 * losers (lineage retained), or the losers are retracted. Attributed and
 * reasoned; agents cannot resolve (resolution is user/policy territory).
 */
export function resolveContradictionImpl(
  store: MemoryStore,
  groupId: string,
  input: ContradictionResolutionInput,
): ContradictionGroup {
  const group = getGroupImpl(store, groupId);
  if (group.status !== "open") {
    throw new ConflictError(`Contradiction group '${groupId}' is already resolved`);
  }
  if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
    throw new ValidationError("reason is required to resolve a contradiction");
  }
  if (input.action !== "supersede" && input.action !== "retract") {
    throw new ValidationError("resolution action must be 'supersede' or 'retract'");
  }
  // Task 35: an explicit restricted policy may authorize a specific agent;
  // otherwise agents are structurally refused.
  const authorized = assertMutationAuthorized(store, group.scopeId, input.actor, "resolve_contradiction");
  if (!authorized && input.actor.kind === "agent") {
    throw new PromotionForbiddenError(
      "actors of kind 'agent' can never resolve contradictions: resolution is a user or policy decision",
    );
  }
  if (!group.recordIds.includes(input.winnerRecordId)) {
    throw new ValidationError(
      `winnerRecordId must be one of the group's records: ${group.recordIds.join(", ")}`,
    );
  }
  const winner = getRecordImpl(store, input.winnerRecordId);
  if (winner.status !== "active") {
    throw new ConflictError(
      `Winner record '${input.winnerRecordId}' is '${winner.status}'; the winner must be active`,
    );
  }
  const losers = group.recordIds.filter((id) => id !== input.winnerRecordId);
  const now = new Date().toISOString();
  const db = store.ensureOpen();

  db.exec("BEGIN IMMEDIATE;");
  try {
    for (const loserId of losers) {
      if (input.action === "supersede") {
        const loser = getRecordImpl(store, loserId);
        if (loser.status !== "active") continue;
        // Winner supersedes the loser (lineage retained, reason explicit).
        db.prepare(
          "UPDATE memory_records SET status = 'superseded', superseded_by_id = ?, superseded_at = ?, supersede_reason = ?, revised_at = ? WHERE record_id = ?",
        ).run(winner.recordId, now, input.reason.trim(), now, loserId);
      } else {
        const loser = getRecordImpl(store, loserId);
        if (loser.status !== "active") continue;
        const newRevision = loser.revision + 1;
        db.prepare(
          "UPDATE memory_records SET status = 'retracted', revision = ?, revised_at = ? WHERE record_id = ?",
        ).run(newRevision, now, loserId);
        db.prepare(
          `INSERT INTO memory_record_revisions (record_id, revision, content, content_hash, provenance_json, revised_at, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?)`,
        ).run(
          loserId,
          newRevision,
          loser.content,
          loser.contentHash,
          JSON.stringify(loser.provenance),
          now,
          `retracted: contradiction ${groupId} resolved (${input.reason.trim()})`,
        );
      }
    }
    const resolution: ContradictionResolution = {
      action: input.action,
      winnerRecordId: input.winnerRecordId,
      actor: { kind: input.actor.kind as never, name: input.actor.name },
      reason: input.reason.trim(),
      resolvedAt: now,
    };
    db.prepare(
      "UPDATE contradiction_groups SET status = 'resolved', resolution_json = ? WHERE group_id = ?",
    ).run(JSON.stringify(resolution), groupId);
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }

  store.appendEvent("memory.contradiction.resolved", withOrigin({
    groupId,
    action: input.action,
    winnerRecordId: input.winnerRecordId,
    losers,
    actor: actorKey(input.actor as never),
    reason: input.reason.trim(),
  }, input.origin));
  return getGroupImpl(store, groupId);
}
