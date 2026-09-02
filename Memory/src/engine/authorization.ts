/**
 * Mutation authorization (Task 35).
 *
 * Requires an explicit project/user policy for mutation operations
 * (promote/revise/delete and related lifecycle mutations) initiated by
 * agents, and logs actor + origin on every mutation.
 *
 * - `open` policy (default): the structural rules apply — agents are blocked
 *   from promote/revise/supersede/lifecycle operations by the existing
 *   structural checks.
 * - `restricted` policy: mutations require the acting actor to be in the
 *   scope's mutation-policy allow list. This is the EXPLICIT project/user
 *   policy — a project can explicitly authorize a specific agent actor for a
 *   mutation it would otherwise never allow.
 *
 * Origin: the surface that initiated the mutation (cli / contract / mcp /
 * host) is recorded on mutation events alongside the actor, so every mutation
 * is attributable to both who and where.
 */
import { MutationForbiddenError, NotFoundError } from "../contracts/errors.ts";
import type { MutationPolicy } from "../contracts/types.ts";
import { actorKey } from "./ids.ts";
import type { MemoryStore } from "./store.ts";

export type MutationOrigin = "cli" | "contract" | "mcp" | "host" | "unknown";

function parsePolicy(raw: unknown): MutationPolicy {
  if (typeof raw === "string" && raw.length > 0) {
    try {
      const parsed = JSON.parse(raw) as Partial<MutationPolicy>;
      if (parsed.mode === "restricted" && Array.isArray(parsed.allow)) {
        return { mode: "restricted", allow: parsed.allow.map(String) };
      }
    } catch {
      // fall through to the safe default
    }
  }
  return { mode: "open", allow: [] };
}

/**
 * Enforce the scope's mutation policy for a mutation operation. `scopeId` is
 * the resolved canonical scope id.
 *
 * Returns `true` when the policy EXPLICITLY authorized this actor (restricted
 * mode + actor in the allow list) — including a specifically authorized agent
 * actor. Returns `false` under `open` mode, where the structural rules apply
 * downstream (agents remain blocked from promote/revise/delete etc.). Under a
 * `restricted` policy an unlisted actor is refused with MutationForbiddenError.
 */
export function assertMutationAuthorized(
  store: MemoryStore,
  scopeId: string,
  actor: { kind: string; name: string },
  operation: string,
): boolean {
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT project_key, mutation_policy_json FROM memory_scopes WHERE scope_id = ?")
    .get(scopeId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new NotFoundError(`No scope for '${scopeId}'`);
  }
  const policy = parsePolicy(row["mutation_policy_json"]);
  if (policy.mode !== "restricted") return false;
  const key = actorKey(actor);
  if (!policy.allow.includes(key)) {
    throw new MutationForbiddenError(
      `mutation '${operation}' by '${key}' is not authorized by scope '${String(row["project_key"])}' mutation policy (restricted): an explicit project/user policy is required for agent-initiated mutations`,
    );
  }
  return true;
}

/** Attach the origin to an event payload when provided. */
export function withOrigin(payload: Record<string, unknown>, origin: MutationOrigin | string | undefined): Record<string, unknown> {
  if (origin === undefined || origin === null) return payload;
  return { ...payload, origin };
}