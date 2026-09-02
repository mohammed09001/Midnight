/**
 * Scope identity and contradiction-group ownership (Task 2).
 *
 * Scopes are the stable project/workspace identity contract: derived
 * deterministically from the caller-owned projectKey (never a path), so
 * identities survive client restarts and project-path moves.
 */
import type { ContradictionGroup, IntakePolicy, MutationPolicy, PrivacyPolicy, ScopeInfo } from "../contracts/types.ts";
import { parsePrivacyPolicy, DEFAULT_PRIVACY_POLICY } from "./privacy.ts";
import {
  ConflictError,
  CorrectionForbiddenError,
  NotFoundError,
  ValidationError,
} from "../contracts/errors.ts";
import { LIMITS } from "./validation.ts";
import { validateProjectKey } from "./validation.ts";
import { actorKey, newId, scopeIdFromProjectKey } from "./ids.ts";
import { assertMutationAuthorized, withOrigin } from "./authorization.ts";
import type { MemoryStore } from "./store.ts";

function checkDisplayName(displayName: unknown): string {
  if (typeof displayName !== "string" || displayName.length === 0) {
    throw new ValidationError("displayName is required");
  }
  if (displayName.length > LIMITS.displayName) {
    throw new ValidationError(`displayName exceeds ${LIMITS.displayName} characters`);
  }
  return displayName.trim();
}

export function createScopeImpl(
  store: MemoryStore,
  projectKey: string,
  displayName: string,
): ScopeInfo {
  const key = validateProjectKey(projectKey);
  const name = checkDisplayName(displayName);
  const db = store.ensureOpen();
  const scopeId = scopeIdFromProjectKey(key);
  const existing = db
    .prepare(
      `SELECT scope_id, project_key, display_name, created_at, intake_policy_json,
              deleted_at, deleted_by, delete_reason
       FROM memory_scopes WHERE project_key = ? OR scope_id = ?`,
    )
    .get(key, scopeId) as Record<string, unknown> | undefined;
  if (existing !== undefined) {
    if (String(existing["display_name"]) === name) {
      // Task 13: a deleted scope's identity is retired, never reused —
      // even with an identical display name.
      if (
        existing["deleted_at"] !== null &&
        existing["deleted_at"] !== undefined
      ) {
        throw new ConflictError(
          `Scope '${key}' was deleted at ${existing["deleted_at"]}; its identity is retired — choose a new project key`,
        );
      }
      // Idempotent creation with identical identity: not a conflict.
      return rowToScope(existing);
    }
    throw new ConflictError(
      `Scope '${key}' already exists with display name '${existing["display_name"]}'`,
    );
  }
  const createdAt = new Date().toISOString();
  db.prepare(
    `INSERT INTO memory_scopes (scope_id, project_key, display_name, created_at)
     VALUES (?, ?, ?, ?)`,
  ).run(scopeId, key, name, createdAt);
  store.appendEvent("memory.scope.created", { scopeId, projectKey: key });
  return {
    scopeId,
    projectKey: key,
    displayName: name,
    createdAt,
    intakePolicy: { mode: "open", allow: [] },
    mutationPolicy: { mode: "open", allow: [] },
    privacyPolicy: DEFAULT_PRIVACY_POLICY,
    deletedAt: null,
    deletedBy: null,
    deleteReason: null,
  };
}

/**
 * Task 13: project deletion with propagation. The scope row and its
 * deterministic identity are RETAINED (retired, never reused); every
 * record in the scope is tombstoned (mode "tombstone") or hard-purged
 * (mode "purge"); open contradiction groups are force-resolved as
 * informational closures. Attributed, reasoned, non-agent.
 */
export function deleteScopeImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  input: {
    actor: { kind: string; name: string };
    reason: string;
    mode?: "tombstone" | "purge";
    origin?: string;
  },
): ScopeInfo {
  const reason = requireDeleteReason(input.reason);
  const mode = input.mode ?? "tombstone";
  if (mode !== "tombstone" && mode !== "purge") {
    throw new ValidationError("deletion mode must be 'tombstone' or 'purge'");
  }
  const scope = getScopeImpl(store, scopeOrProjectKey);
  if (scope.deletedAt !== null) {
    throw new ConflictError(`Scope '${scope.projectKey}' is already deleted`);
  }
  // Task 35: an explicit restricted policy may authorize a specific agent;
  // otherwise agents are structurally refused.
  const authorized = assertMutationAuthorized(store, scope.scopeId, input.actor, "delete_scope");
  if (!authorized && input.actor.kind === "agent") {
    throw new CorrectionForbiddenError(
      "actors of kind 'agent' cannot delete projects: project deletion is a user or authorized-engine decision",
    );
  }
  const db = store.ensureOpen();
  const now = new Date().toISOString();
  const recordIds = db
    .prepare("SELECT record_id FROM memory_records WHERE scope_id = ?")
    .all(scope.scopeId) as Array<Record<string, unknown>>;
  const { deleteRecordImpl, purgeRecordImpl } = retentionFns();

  db.exec("BEGIN IMMEDIATE;");
  try {
    db.prepare(
      "UPDATE memory_scopes SET deleted_at = ?, deleted_by = ?, delete_reason = ? WHERE scope_id = ?",
    ).run(now, actorKey(input.actor), reason, scope.scopeId);
    // Close open contradiction groups as informational closures.
    db.prepare(
      "UPDATE contradiction_groups SET status = 'resolved', resolution_json = ? WHERE scope_id = ? AND status = 'open'",
    ).run(
      JSON.stringify({
        action: "retract",
        winnerRecordId: "",
        actor: { kind: input.actor.kind, name: input.actor.name },
        reason: `scope deleted: ${reason}`,
        resolvedAt: now,
      }),
      scope.scopeId,
    );
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }
  // Propagate per-record (tombstone/purge) outside the scope transaction —
  // each performs its own integrity work and event.
  for (const row of recordIds) {
    const recordId = String(row["record_id"]);
    if (mode === "purge") {
      purgeRecordImpl(store, recordId, { actor: input.actor, reason: `project deleted: ${reason}` });
    } else {
      deleteRecordImpl(store, recordId, { actor: input.actor, reason: `project deleted: ${reason}` });
    }
  }
  // Drop pending candidates — intake for a deleted project is meaningless.
  db.prepare("DELETE FROM memory_candidates WHERE scope_id = ?").run(scope.scopeId);
  // Drop search-session history — retrieval context for a deleted project is meaningless.
  db.prepare("DELETE FROM memory_search_sessions WHERE scope_id = ?").run(scope.scopeId);
  store.appendEvent("memory.scope.deleted", withOrigin({
    scopeId: scope.scopeId,
    projectKey: scope.projectKey,
    actor: actorKey(input.actor),
    reason,
    mode,
    affectedRecords: recordIds.length,
  }, input.origin));
  return getScopeImpl(store, scope.scopeId);
}

function requireDeleteReason(reason: unknown): string {
  if (typeof reason !== "string" || reason.trim().length === 0) {
    throw new ValidationError("reason is required for project deletion");
  }
  return reason.trim();
}

// Lazy binding to avoid an import cycle at module load (retention imports scopes).
import * as retention from "./retention.ts";
function retentionFns() {
  return {
    deleteRecordImpl: retention.deleteRecordImpl,
    purgeRecordImpl: retention.purgeRecordImpl,
  };
}

export function getScopeImpl(store: MemoryStore, scopeOrProjectKey: string): ScopeInfo {
  const db = store.ensureOpen();
  const derived = scopeIdFromProjectKey(scopeOrProjectKey);
  const row = db
    .prepare(
      `SELECT scope_id, project_key, display_name, created_at, intake_policy_json,
              deleted_at, deleted_by, delete_reason
       FROM memory_scopes WHERE scope_id = ? OR project_key = ?`,
    )
    .get(scopeOrProjectKey, scopeOrProjectKey) as Record<string, unknown> | undefined;
  if (row !== undefined) return rowToScope(row);
  // Also accept the deterministic scope id itself.
  const byDerived = db
    .prepare(
      `SELECT scope_id, project_key, display_name, created_at, intake_policy_json,
              deleted_at, deleted_by, delete_reason
       FROM memory_scopes WHERE scope_id = ?`,
    )
    .get(derived) as Record<string, unknown> | undefined;
  if (byDerived !== undefined) return rowToScope(byDerived);
  throw new NotFoundError(`No scope for '${scopeOrProjectKey}'`);
}

function rowToScope(row: Record<string, unknown>): ScopeInfo {
  let intakePolicy: IntakePolicy = { mode: "open", allow: [] };
  const rawPolicy = row["intake_policy_json"];
  if (rawPolicy !== null && rawPolicy !== undefined) {
    try {
      const parsed = JSON.parse(String(rawPolicy)) as Partial<IntakePolicy>;
      if (parsed.mode === "allowlist" && Array.isArray(parsed.allow)) {
        intakePolicy = { mode: "allowlist", allow: parsed.allow.map(String) };
      }
    } catch {
      // Corrupt policy JSON falls back to the safe default (open) rather
      // than blocking all intake; setScopeIntakePolicy rewrites it cleanly.
    }
  }
  let mutationPolicy: MutationPolicy = { mode: "open", allow: [] };
  const rawMutation = row["mutation_policy_json"];
  if (rawMutation !== null && rawMutation !== undefined) {
    try {
      const parsed = JSON.parse(String(rawMutation)) as Partial<MutationPolicy>;
      if (parsed.mode === "restricted" && Array.isArray(parsed.allow)) {
        mutationPolicy = { mode: "restricted", allow: parsed.allow.map(String) };
      }
    } catch {
      // Corrupt policy JSON falls back to the safe default (open).
    }
  }
  let privacyPolicy: PrivacyPolicy = DEFAULT_PRIVACY_POLICY;
  const rawPrivacy = row["privacy_policy_json"];
  if (rawPrivacy !== null && rawPrivacy !== undefined) {
    privacyPolicy = parsePrivacyPolicy(rawPrivacy);
  }
  return {
    scopeId: String(row["scope_id"]),
    projectKey: String(row["project_key"]),
    displayName: String(row["display_name"]),
    createdAt: String(row["created_at"]),
    intakePolicy,
    mutationPolicy,
    privacyPolicy,
    deletedAt: row["deleted_at"] === null || row["deleted_at"] === undefined ? null : String(row["deleted_at"]),
    deletedBy: row["deleted_by"] === null || row["deleted_by"] === undefined ? null : String(row["deleted_by"]),
    deleteReason: row["delete_reason"] === null || row["delete_reason"] === undefined ? null : String(row["delete_reason"]),
  };
}

/**
 * Task 13: guard — deleted scopes refuse all writes. Identity is retained
 * (the deterministic scope id is never reused for new content).
 */
export function assertScopeNotDeleted(scope: ScopeInfo): void {
  if (scope.deletedAt !== null) {
    throw new ConflictError(
      `Scope '${scope.projectKey}' was deleted at ${scope.deletedAt}; its identity is retired and cannot accept new content`,
    );
  }
}

/**
 * Task 8: configure the candidate intake authorization policy for a scope.
 * Allowlist entries are canonical actor keys ("engine:repository_sync",
 * "user:kim", "agent:worker-a", "tool:importer").
 */
export function setScopeIntakePolicyImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  policy: IntakePolicy,
): ScopeInfo {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  if (
    policy.mode !== "open" && policy.mode !== "allowlist"
  ) {
    throw new ValidationError("intake policy mode must be 'open' or 'allowlist'");
  }
  const allow = policy.mode === "allowlist" ? [...new Set(policy.allow)] : [];
  if (policy.mode === "allowlist") {
    if (allow.length === 0) {
      throw new ValidationError("allowlist intake requires at least one authorized caller key");
    }
    for (const entry of allow) {
      if (typeof entry !== "string" || !/^(human|agent|engine|tool):.+$/.test(entry)) {
        throw new ValidationError(
          `allowlist entries must be canonical actor keys like 'engine:repository_sync' or 'user:kim' (got '${entry}')`,
        );
      }
    }
  }
  const db = store.ensureOpen();
  db.prepare("UPDATE memory_scopes SET intake_policy_json = ? WHERE scope_id = ?").run(
    JSON.stringify({ mode: policy.mode, allow }),
    scope.scopeId,
  );
  store.appendEvent("memory.scope.intake_policy.updated", {
    scopeId: scope.scopeId,
    projectKey: scope.projectKey,
    mode: policy.mode,
    allow,
  });
  return getScopeImpl(store, scope.scopeId);
}

/**
 * Task 35: configure the mutation authorization policy for a scope. Under
 * `open` (default) the structural rules apply (agents are blocked from
 * promote/revise/delete etc.). Under `restricted`, mutations require the
 * actor to be in `allow` — the explicit project/user policy that can also
 * explicitly authorize specific agent actors.
 */
export function setScopeMutationPolicyImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  policy: MutationPolicy,
): ScopeInfo {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  if (policy.mode !== "open" && policy.mode !== "restricted") {
    throw new ValidationError("mutation policy mode must be 'open' or 'restricted'");
  }
  const allow = policy.mode === "restricted" ? [...new Set(policy.allow)] : [];
  if (policy.mode === "restricted") {
    if (allow.length === 0) {
      throw new ValidationError("restricted mutation policy requires at least one authorized actor key");
    }
    for (const entry of allow) {
      if (typeof entry !== "string" || !/^(human|agent|engine|tool):.+$/.test(entry)) {
        throw new ValidationError(
          `mutation policy allow entries must be canonical actor keys like 'agent:worker-a' or 'human:kim' (got '${entry}')`,
        );
      }
    }
  }
  const db = store.ensureOpen();
  db.prepare("UPDATE memory_scopes SET mutation_policy_json = ? WHERE scope_id = ?").run(
    JSON.stringify({ mode: policy.mode, allow }),
    scope.scopeId,
  );
  store.appendEvent("memory.scope.mutation_policy.updated", {
    scopeId: scope.scopeId,
    projectKey: scope.projectKey,
    mode: policy.mode,
    allow,
  });
  return getScopeImpl(store, scope.scopeId);
}
