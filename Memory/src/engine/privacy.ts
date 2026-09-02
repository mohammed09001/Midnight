/**
 * Field-level privacy and project isolation (Task 37).
 *
 * - Content-class policy (per scope): controls which content classes are
 *   EXPORTABLE without opt-in (default `public` + `internal`) and whether
 *   `sensitive` content is outright FORBIDDEN from exports/excerpts/derived
 *   indexes (even with an explicit opt-in). Applied to the excerpt and
 *   embedding gates.
 * - Export restrictions: `checkExportable` is the single deterministic rule
 *   for whether a record may be exported/excerpted.
 * - Project/workspace isolation is an engine-level `strict`/`open` setting
 *   (default `strict` = local/self-hosted): read/query surfaces require a
 *   scope (project) so an unscoped query cannot silently read across
 *   projects.
 * - Local/self-hosted default: the engine is immutable `selfHosted: true`
 *   (zero external calls); surfaced via `policyStatus`.
 */
import { PrivacyViolationError, ValidationError } from "../contracts/errors.ts";
import type { ContentPolicy, PrivacyPolicy } from "../contracts/types.ts";
import { getScopeImpl } from "./scopes.ts";
import type { MemoryStore } from "./store.ts";

export type { ContentPolicy, PrivacyPolicy };

export const DEFAULT_CONTENT_POLICY: ContentPolicy = {
  exportable: ["public", "internal"],
  forbidSensitive: false,
};

export const DEFAULT_PRIVACY_POLICY: PrivacyPolicy = { content: DEFAULT_CONTENT_POLICY };

export type ProjectIsolation = "strict" | "open";

/** The engine's immutable local/self-hosted default. */
export const SELF_HOSTED_DEFAULT = true as const;

export function parsePrivacyPolicy(raw: unknown): PrivacyPolicy {
  if (typeof raw === "string" && raw.length > 0) {
    try {
      const parsed = JSON.parse(raw) as Partial<PrivacyPolicy>;
      const content = parsed.content;
      if (content !== undefined && typeof content === "object") {
        const exportable = Array.isArray(content.exportable)
          ? content.exportable.filter((c) => c === "public" || c === "internal")
          : DEFAULT_CONTENT_POLICY.exportable;
        return { content: { exportable, forbidSensitive: content.forbidSensitive === true } };
      }
    } catch {
      // fall through to the safe default
    }
  }
  return DEFAULT_PRIVACY_POLICY;
}

/** Deterministic export rule for a record under a content policy. */
export function checkExportable(
  record: { privacyClass: "public" | "internal" | "sensitive" },
  policy: PrivacyPolicy,
  includeSensitive?: boolean,
): { exportable: boolean; reason?: string } {
  const cls = record.privacyClass;
  if (cls === "sensitive") {
    if (policy.content.forbidSensitive) {
      return { exportable: false, reason: "sensitive content is forbidden from exports by the content policy" };
    }
    if (includeSensitive === true) return { exportable: true };
    return { exportable: false, reason: "sensitive content requires explicit opt-in to export" };
  }
  if (policy.content.exportable.includes(cls)) return { exportable: true };
  return { exportable: false, reason: `content class '${cls}' is not in the exportable set` };
}

/** Read the scope's content privacy policy. */
export function getContentPolicy(store: MemoryStore, scopeId: string): PrivacyPolicy {
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT privacy_policy_json FROM memory_scopes WHERE scope_id = ?")
    .get(scopeId) as Record<string, unknown> | undefined;
  return row === undefined ? DEFAULT_PRIVACY_POLICY : parsePrivacyPolicy(row["privacy_policy_json"]);
}

/**
 * Enforce the scope's content policy for exporting/excerpting a record.
 * Throws MEMORY_PRIVACY_VIOLATION when the record is not exportable.
 */
export function assertContentExportable(
  store: MemoryStore,
  scopeId: string,
  record: { privacyClass: "public" | "internal" | "sensitive" },
  includeSensitive?: boolean,
): void {
  const check = checkExportable(record, getContentPolicy(store, scopeId), includeSensitive);
  if (!check.exportable) {
    throw new PrivacyViolationError(check.reason ?? "record is not exportable under the content policy");
  }
}

/** Configure the scope's content privacy policy. */
export function setScopePrivacyPolicyImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  policy: PrivacyPolicy,
): PrivacyPolicy {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  if (policy.content === undefined || typeof policy.content !== "object") {
    throw new ValidationError("policy.content is required");
  }
  const normalized: PrivacyPolicy = {
    content: {
      exportable: (policy.content.exportable ?? []).filter((c) => c === "public" || c === "internal"),
      forbidSensitive: policy.content.forbidSensitive === true,
    },
  };
  const db = store.ensureOpen();
  db.prepare("UPDATE memory_scopes SET privacy_policy_json = ? WHERE scope_id = ?").run(
    JSON.stringify(normalized),
    scope.scopeId,
  );
  store.appendEvent("memory.scope.privacy_policy.updated", {
    scopeId: scope.scopeId,
    projectKey: scope.projectKey,
    content: normalized.content,
  });
  return normalized;
}

/**
 * Enforce project isolation for a read/query surface: under `strict`
 * isolation an unscoped query is refused.
 */
export function assertIsolationScope(
  isolation: ProjectIsolation,
  scope: string | undefined,
  surface: string,
): void {
  if (isolation === "strict" && (scope === undefined || scope === null || scope === "")) {
    throw new ValidationError(
      `project isolation is strict: ${surface} requires a scope (project); pass 'scope' or set project isolation to 'open'`,
    );
  }
}

export interface ScopePolicySummary {
  projectKey: string;
  content: ContentPolicy;
}

export interface PolicyStatus {
  /** Immutable: the engine is local/self-hosted (zero external calls). */
  selfHosted: true;
  projectIsolation: ProjectIsolation;
  scopes: ScopePolicySummary[];
}

/** Report the engine's privacy posture: self-hosted default, isolation, per-scope content policies. */
export function policyStatusImpl(store: MemoryStore, isolation: ProjectIsolation): PolicyStatus {
  const db = store.ensureOpen();
  const rows = db
    .prepare("SELECT project_key, privacy_policy_json FROM memory_scopes ORDER BY project_key")
    .all() as Array<Record<string, unknown>>;
  return {
    selfHosted: SELF_HOSTED_DEFAULT,
    projectIsolation: isolation,
    scopes: rows.map((r) => ({
      projectKey: String(r["project_key"]),
      content: parsePrivacyPolicy(r["privacy_policy_json"]).content,
    })),
  };
}