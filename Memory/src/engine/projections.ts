/**
 * Unified index rebuild and corruption recovery (Task 26).
 *
 * Rebuild the lexical / embedding / graph / entity projections from canonical
 * records and prove that a corrupted derived projection NEVER corrupts Memory
 * truth. Canonical records (and the immutable revision log) are the only
 * truth; every derived projection (FTS index, embedding tables, on-demand
 * entity/graph projections) is disposable and rebuildable.
 *
 * - checkProjectionIntegrity: verifies each stored projection against
 *   canonical records (FTS entry counts vs indexable records; embedding rows
 *   vs canonical records + build metadata). Graph/entity projections are
 *   computed on demand and have no stored state to corrupt.
 * - rebuildAllProjections: rebuilds every projection from canonical records
 *   (the recovery path), emitting the per-projection events.
 * - repairProjections: detects corrupted projections and rebuilds only those.
 */
import type { MemoryStore } from "./store.ts";
import { rebuildSearchIndexImpl } from "./retrieval.ts";
import { rebuildEntityProjectionImpl } from "./entities.ts";
import { rebuildGraphProjectionImpl } from "./graph.ts";
import { getScopeImpl } from "./scopes.ts";
import {
  rebuildEmbeddingProjectionImpl,
  type EmbeddingBuildOptions,
  type EmbeddingProvider,
} from "./embeddings.ts";

export type ProjectionName = "lexical" | "embedding" | "graph" | "entity";

export interface ProjectionStatus {
  name: ProjectionName;
  status: "ok" | "corrupted" | "unavailable" | "not_built";
  detail?: string;
}

export interface ProjectionIntegrityReport {
  healthy: boolean;
  scopeId: string | null;
  checkedAt: string;
  projections: ProjectionStatus[];
}

export interface RebuildResult {
  rebuilt: ProjectionName[];
  report: ProjectionIntegrityReport;
}

export interface RepairResult {
  repaired: ProjectionName[];
  report: ProjectionIntegrityReport;
}

function allScopes(store: MemoryStore): Array<{ scopeId: string; projectKey: string }> {
  const db = store.ensureOpen();
  const rows = db
    .prepare("SELECT scope_id, project_key FROM memory_scopes ORDER BY project_key")
    .all() as Array<Record<string, unknown>>;
  return rows.map((r) => ({ scopeId: String(r["scope_id"]), projectKey: String(r["project_key"]) }));
}

/**
 * First searchable token of a subject (same unicode tokenization as the FTS
 * query builder), or null when the subject has no tokens (cannot be probed).
 */
function firstSubjectToken(subject: string): string | null {
  const tokens = subject
    .toLowerCase()
    .split(/[^\p{L}\p{N}_]+/u)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  return tokens[0] ?? null;
}

/**
 * Lexical (FTS) integrity: probe every canonical indexable record — a record
 * is indexable when status != 'deleted' — and verify it is retrievable from
 * the FTS index by its first subject token. A missing index entry (e.g. a
 * deleted/trigger-dropped entry) is detected even though FTS5 external-content
 * tables still materialize the row and FTS5 'integrity-check' does not flag it.
 */
function checkLexical(store: MemoryStore, scopeId: string | null): ProjectionStatus {
  const db = store.ensureOpen();
  const params: Array<string | number> = [];
  let where = "r.status != 'deleted'";
  if (scopeId !== null) {
    where += " AND r.scope_id = ?";
    params.push(scopeId);
  }
  const records = db
    .prepare(`SELECT r.record_id, r.subject FROM memory_records r WHERE ${where}`)
    .all(...params) as Array<Record<string, unknown>>;

  let missing = 0;
  for (const row of records) {
    const recordId = String(row["record_id"]);
    const token = firstSubjectToken(String(row["subject"]));
    if (token === null) continue;
    const probe = db
      .prepare("SELECT 1 FROM memory_fts WHERE memory_fts MATCH ? AND rowid IN (SELECT rowid FROM memory_records WHERE record_id = ?)")
      .get(`"${token}"`, recordId);
    if (probe === undefined) missing++;
  }

  if (missing === 0) {
    return { name: "lexical", status: "ok", detail: `${records.length} indexable record(s) probed and found in the fts index` };
  }
  return { name: "lexical", status: "corrupted", detail: `${missing} indexable record(s) are missing from the fts index (of ${records.length})` };
}

function checkEmbedding(store: MemoryStore, provider: EmbeddingProvider | null, scopeId: string | null): ProjectionStatus {
  if (provider === null) {
    return { name: "embedding", status: "unavailable", detail: "no embedding provider configured" };
  }
  const db = store.ensureOpen();
  // Global orphans: embedding rows whose record no longer exists. An orphan is
  // always corruption regardless of scope (the row cannot be scope-identified).
  const orphanCount = Number(
    (db
      .prepare("SELECT COUNT(*) AS n FROM memory_embeddings e LEFT JOIN memory_records r ON r.record_id = e.record_id WHERE r.record_id IS NULL")
      .get() as Record<string, unknown>)["n"],
  );
  if (orphanCount > 0) {
    return { name: "embedding", status: "corrupted", detail: `${orphanCount} embedding row(s) reference missing records` };
  }

  if (scopeId !== null) {
    const meta = db.prepare("SELECT record_count FROM memory_embedding_projections WHERE scope_id = ?").get(scopeId) as Record<string, unknown> | undefined;
    if (meta === undefined) {
      return { name: "embedding", status: "not_built", detail: "no embedding projection built for this scope" };
    }
    const actual = Number(
      (db
        .prepare("SELECT COUNT(*) AS n FROM memory_embeddings e JOIN memory_records r ON r.record_id = e.record_id WHERE r.scope_id = ?")
        .get(scopeId) as Record<string, unknown>)["n"],
    );
    if (actual !== Number(meta["record_count"])) {
      return { name: "embedding", status: "corrupted", detail: `projection metadata says ${meta["record_count"]} rows but ${actual} exist` };
    }
    return { name: "embedding", status: "ok", detail: `${actual} embedding rows consistent with metadata` };
  }

  // No scope: verify every stored projection's metadata against actual rows.
  const metas = db
    .prepare("SELECT scope_id, record_count FROM memory_embedding_projections")
    .all() as Array<Record<string, unknown>>;
  if (metas.length === 0) {
    return { name: "embedding", status: "not_built", detail: "no embedding projection built" };
  }
  for (const meta of metas) {
    const sid = String(meta["scope_id"]);
    const actual = Number(
      (db
        .prepare("SELECT COUNT(*) AS n FROM memory_embeddings e JOIN memory_records r ON r.record_id = e.record_id WHERE r.scope_id = ?")
        .get(sid) as Record<string, unknown>)["n"],
    );
    if (actual !== Number(meta["record_count"])) {
      return { name: "embedding", status: "corrupted", detail: `scope ${sid}: metadata says ${meta["record_count"]} rows but ${actual} exist` };
    }
  }
  return { name: "embedding", status: "ok", detail: "all embedding projections consistent" };
}

function checkOnDemand(name: ProjectionName): ProjectionStatus {
  return { name, status: "ok", detail: "computed on demand; no stored state to corrupt" };
}

/**
 * Verify each derived projection against canonical records. Never throws for
 * a detected mismatch — corruption is reported in the status.
 */
export function checkProjectionIntegrityImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  scopeOrProjectKey?: string,
): ProjectionIntegrityReport {
  const scopeId = scopeOrProjectKey !== undefined ? storeScopeId(store, scopeOrProjectKey) : null;
  const projections: ProjectionStatus[] = [
    checkLexical(store, scopeId),
    checkEmbedding(store, provider, scopeId),
    checkOnDemand("graph"),
    checkOnDemand("entity"),
  ];
  return {
    healthy: projections.every((p) => p.status !== "corrupted"),
    scopeId,
    checkedAt: new Date().toISOString(),
    projections,
  };
}

function storeScopeId(store: MemoryStore, scopeOrProjectKey: string): string {
  return getScopeImpl(store, scopeOrProjectKey).scopeId;
}

function resolveScopes(store: MemoryStore, scope?: string): Array<{ scopeId: string; projectKey: string }> {
  if (scope === undefined) return allScopes(store);
  const info = getScopeImpl(store, scope);
  return [{ scopeId: info.scopeId, projectKey: info.projectKey }];
}

/**
 * Rebuild every derived projection from canonical records (the recovery
 * path). Graph/entity are recomputed per scope; lexical is rebuilt; the
 * embedding projection is rebuilt per scope only when a provider is
 * configured (reported unavailable otherwise).
 */
export function rebuildAllProjectionsImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  options: EmbeddingBuildOptions & { scope?: string } = {},
): RebuildResult {
  const rebuilt: ProjectionName[] = [];
  const scopes = resolveScopes(store, options.scope);

  rebuildSearchIndexImpl(store);
  rebuilt.push("lexical");

  for (const scope of scopes) {
    rebuildEntityProjectionImpl(store, scope.scopeId);
    rebuilt.push("entity");
    rebuildGraphProjectionImpl(store, scope.scopeId);
    rebuilt.push("graph");
  }
  if (provider !== null) {
    for (const scope of scopes) {
      rebuildEmbeddingProjectionImpl(store, provider, scope.scopeId, { includeSensitive: options.includeSensitive });
      rebuilt.push("embedding");
    }
  }

  const report = checkProjectionIntegrityImpl(store, provider, options.scope);
  return { rebuilt: [...new Set(rebuilt)], report };
}

/**
 * Detect corrupted projections and rebuild only those. Canonical records are
 * never touched by the repair.
 */
export function repairProjectionsImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  options: EmbeddingBuildOptions & { scope?: string } = {},
): RepairResult {
  const report = checkProjectionIntegrityImpl(store, provider, options.scope);
  const repaired: ProjectionName[] = [];
  for (const p of report.projections) {
    if (p.status !== "corrupted") continue;
    if (p.name === "lexical") {
      rebuildSearchIndexImpl(store);
      repaired.push("lexical");
    } else if (p.name === "embedding") {
      const scopes = resolveScopes(store, options.scope);
      for (const scope of scopes) {
        rebuildEmbeddingProjectionImpl(store, provider!, scope.scopeId, { includeSensitive: options.includeSensitive });
      }
      repaired.push("embedding");
    }
  }
  const freshReport = checkProjectionIntegrityImpl(store, provider, options.scope);
  return { repaired, report: freshReport };
}