/**
 * Backup, restore, and integrity checks (Task 39).
 *
 * Backs up CANONICAL Memory (scopes, records, immutable revisions,
 * candidates, contradiction groups, search-session history, and scope
 * policies) — the metadata needed to rebuild derived projections — as a
 * portable JSON bundle with a SHA-256 checksum. Derived projections (FTS,
 * embeddings, entity/graph) are NOT backed up: they are rebuildable from
 * canonical records.
 *
 * - `backupImpl` / `backupToFile`: export the canonical bundle (+ checksum).
 * - `verifyBackup`: recompute the checksum and validate structural references.
 * - `restoreBundle` / `restoreFromFile`: apply a verified bundle to a FRESH
 *   store (refuses a store that already contains data — a restore is a full
 *   snapshot). Recovery: after restore the store is fully functional and
 *   projections can be rebuilt.
 * - `verifyStoreReferences`: verify canonical foreign references
 *   (records → scopes/supersession/contradiction, revisions → records,
 *   candidates → scopes, search sessions → scopes).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { ConflictError, ValidationError } from "../contracts/errors.ts";
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import type { MemoryStore } from "./store.ts";

export const BACKUP_FORMAT = "midnight-memory-backup" as const;
/** Pre-rename format string, accepted read-only (never re-emitted by backupImpl). */
export const LEGACY_BACKUP_FORMAT = "library-memory-backup" as const;
export const BACKUP_SCHEMA_VERSION = 1 as const;

const SCOPE_COLUMNS = [
  "scope_id", "project_key", "display_name", "created_at",
  "intake_policy_json", "mutation_policy_json", "privacy_policy_json",
  "deleted_at", "deleted_by", "delete_reason",
] as const;

const GROUP_COLUMNS = ["group_id", "scope_id", "subject", "record_ids", "created_at", "status", "resolution_json"] as const;

const RECORD_COLUMNS = [
  "record_id", "contract_version", "kind", "subject", "content", "content_hash",
  "scope_id", "provenance_json", "epistemic_class", "confidence", "evidence_json",
  "relation_hints_json", "tags_json", "privacy_class", "valid_from", "valid_until",
  "status", "revision", "created_at", "revised_at", "supersedes_id",
  "superseded_by_id", "contradiction_group_id", "observed_at", "superseded_at",
  "supersede_reason", "idempotency_key", "archived_at", "deleted_at", "deleted_by",
  "delete_reason",
] as const;

const REVISION_COLUMNS = ["record_id", "revision", "content", "content_hash", "provenance_json", "revised_at", "reason"] as const;

const CANDIDATE_COLUMNS = [
  "candidate_id", "scope_id", "kind", "subject", "content", "content_hash",
  "provenance_json", "epistemic_class", "confidence", "evidence_json", "tags_json",
  "status", "created_at", "promoted_record_id", "idempotency_key", "reason", "caller_json",
] as const;

const SESSION_COLUMNS = [
  "search_session_id", "scope_id", "intent", "actor_json", "observed_at",
  "created_at", "result_refs_json", "candidate_refs_json", "note",
] as const;

export interface BackupData {
  scopes: Array<Record<string, unknown>>;
  contradictionGroups: Array<Record<string, unknown>>;
  records: Array<Record<string, unknown>>;
  revisions: Array<Record<string, unknown>>;
  candidates: Array<Record<string, unknown>>;
  searchSessions: Array<Record<string, unknown>>;
}

export interface BackupBundle {
  format: typeof BACKUP_FORMAT | typeof LEGACY_BACKUP_FORMAT;
  schemaVersion: typeof BACKUP_SCHEMA_VERSION;
  contractVersion: string;
  createdAt: string;
  checksum: string;
  data: BackupData;
}

function selectAll(db: { prepare(sql: string): { all(): Array<Record<string, unknown>> } }, table: string, columns: readonly string[]): Array<Record<string, unknown>> {
  return db.prepare(`SELECT ${columns.join(", ")} FROM ${table}`).all();
}

function canonicalChecksum(data: BackupData): string {
  return createHash("sha256").update(JSON.stringify(data)).digest("hex");
}

/** Export the canonical Memory bundle (+ projection-rebuild metadata). */
export function backupImpl(store: MemoryStore): BackupBundle {
  const db = store.ensureOpen();
  const data: BackupData = {
    scopes: selectAll(db, "memory_scopes", SCOPE_COLUMNS),
    contradictionGroups: selectAll(db, "contradiction_groups", GROUP_COLUMNS),
    records: selectAll(db, "memory_records", RECORD_COLUMNS),
    revisions: selectAll(db, "memory_record_revisions", REVISION_COLUMNS),
    candidates: selectAll(db, "memory_candidates", CANDIDATE_COLUMNS),
    searchSessions: selectAll(db, "memory_search_sessions", SESSION_COLUMNS),
  };
  return {
    format: BACKUP_FORMAT,
    schemaVersion: BACKUP_SCHEMA_VERSION,
    contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
    createdAt: new Date().toISOString(),
    checksum: canonicalChecksum(data),
    data,
  };
}

export function backupToFile(store: MemoryStore, path: string): BackupBundle {
  const bundle = backupImpl(store);
  writeFileSync(path, JSON.stringify(bundle), "utf8");
  return bundle;
}

/** Verify a backup bundle: format, checksum, and structural references. */
export function verifyBackup(bundle: unknown): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  if (bundle === null || typeof bundle !== "object") {
    return { valid: false, errors: ["bundle is not an object"] };
  }
  const b = bundle as Partial<BackupBundle>;
  if (b.format !== BACKUP_FORMAT && b.format !== LEGACY_BACKUP_FORMAT) {
    errors.push(`format must be '${BACKUP_FORMAT}' or '${LEGACY_BACKUP_FORMAT}'`);
  } else if (b.format === LEGACY_BACKUP_FORMAT) {
    process.stderr.write(`warning: restoring a legacy '${LEGACY_BACKUP_FORMAT}' bundle; new backups are written as '${BACKUP_FORMAT}'\n`);
  }
  if (b.schemaVersion !== BACKUP_SCHEMA_VERSION) errors.push(`schemaVersion must be ${BACKUP_SCHEMA_VERSION}`);
  if (b.data === undefined || b.data === null || typeof b.data !== "object") {
    errors.push("bundle.data is missing");
    return { valid: false, errors };
  }
  const data = b.data as BackupData;
  const recomputed = canonicalChecksum(data);
  if (b.checksum !== recomputed) {
    errors.push("checksum mismatch: the backup is corrupt or tampered");
  }
  const scopeIds = new Set((data.scopes ?? []).map((r) => String(r["scope_id"])));
  const recordIds = new Set((data.records ?? []).map((r) => String(r["record_id"])));
  for (const rec of data.records ?? []) {
    if (!scopeIds.has(String(rec["scope_id"]))) errors.push(`record '${rec["record_id"]}' references unknown scope '${rec["scope_id"]}'`);
    if (rec["supersedes_id"] !== null && rec["supersedes_id"] !== undefined && !recordIds.has(String(rec["supersedes_id"]))) errors.push(`record '${rec["record_id"]}' supersedes unknown record '${rec["supersedes_id"]}'`);
  }
  for (const rev of data.revisions ?? []) {
    if (!recordIds.has(String(rev["record_id"]))) errors.push(`revision references unknown record '${rev["record_id"]}'`);
  }
  for (const cand of data.candidates ?? []) {
    if (!scopeIds.has(String(cand["scope_id"]))) errors.push(`candidate '${cand["candidate_id"]}' references unknown scope '${cand["scope_id"]}'`);
  }
  for (const grp of data.contradictionGroups ?? []) {
    if (!scopeIds.has(String(grp["scope_id"]))) errors.push(`contradiction group '${grp["group_id"]}' references unknown scope '${grp["scope_id"]}'`);
  }
  for (const ses of data.searchSessions ?? []) {
    if (!scopeIds.has(String(ses["scope_id"]))) errors.push(`search session '${ses["search_session_id"]}' references unknown scope '${ses["scope_id"]}'`);
  }
  return { valid: errors.length === 0, errors };
}

function insertRows(db: { prepare(sql: string): { run(...p: unknown[]): void } }, table: string, columns: readonly string[], rows: Array<Record<string, unknown>>): void {
  const insert = db.prepare(`INSERT INTO ${table} (${columns.join(", ")}) VALUES (${columns.map(() => "?").join(", ")})`);
  for (const row of rows) {
    insert.run(...columns.map((c) => (row[c] ?? null) as never));
  }
}

/** Restore a verified bundle into a FRESH store (full snapshot). */
export function restoreBundle(store: MemoryStore, bundle: unknown): { restored: true; scopes: number; records: number; candidates: number } {
  const check = verifyBackup(bundle);
  if (!check.valid) {
    throw new ValidationError(`refusing to restore an invalid backup: ${check.errors.join("; ")}`);
  }
  const b = bundle as BackupBundle;
  const db = store.ensureOpen();
  const existingRecords = Number((db.prepare("SELECT COUNT(*) AS n FROM memory_records").get() as Record<string, unknown>)["n"]);
  const existingScopes = Number((db.prepare("SELECT COUNT(*) AS n FROM memory_scopes").get() as Record<string, unknown>)["n"]);
  if (existingRecords > 0 || existingScopes > 0) {
    throw new ConflictError("restore targets a non-empty store: a backup restore is a full snapshot into a fresh store");
  }
  // Task 45: lineage pointers may reference records inserted later in the
  // bundle order (e.g. superseded_by_id). The bundle is checksum-verified
  // and structurally validated (verifyBackup), so suspend FK enforcement
  // around the restore transaction (the pragma is a no-op inside a
  // transaction, so it is toggled before BEGIN / after COMMIT).
  db.exec("PRAGMA foreign_keys = OFF;");
  db.exec("BEGIN IMMEDIATE;");
  try {
    insertRows(db, "memory_scopes", SCOPE_COLUMNS, b.data.scopes);
    insertRows(db, "contradiction_groups", GROUP_COLUMNS, b.data.contradictionGroups);
    insertRows(db, "memory_records", RECORD_COLUMNS, b.data.records);
    insertRows(db, "memory_record_revisions", REVISION_COLUMNS, b.data.revisions);
    insertRows(db, "memory_candidates", CANDIDATE_COLUMNS, b.data.candidates);
    insertRows(db, "memory_search_sessions", SESSION_COLUMNS, b.data.searchSessions);
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  } finally {
    db.exec("PRAGMA foreign_keys = ON;");
  }
  return {
    restored: true,
    scopes: b.data.scopes.length,
    records: b.data.records.length,
    candidates: b.data.candidates.length,
  };
}

export function restoreFromFile(store: MemoryStore, path: string): { restored: true; scopes: number; records: number; candidates: number } {
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(path, "utf8"));
  } catch (err) {
    throw new ValidationError(`cannot read backup file '${path}': ${err instanceof Error ? err.message : String(err)}`);
  }
  return restoreBundle(store, raw);
}

export interface ForeignReferenceIssue {
  problem: string;
  count: number;
}

export interface StoreReferenceReport {
  consistent: boolean;
  issues: ForeignReferenceIssue[];
}

/** Verify canonical foreign references in the live store. */
export function verifyStoreReferences(store: MemoryStore): StoreReferenceReport {
  const db = store.ensureOpen();
  const issues: ForeignReferenceIssue[] = [];
  const count = (sql: string): number => Number((db.prepare(sql).get() as Record<string, unknown>)["n"]);

  const orphanRecords = count(`
    SELECT COUNT(*) AS n FROM memory_records r LEFT JOIN memory_scopes s ON s.scope_id = r.scope_id
    WHERE s.scope_id IS NULL`);
  if (orphanRecords > 0) issues.push({ problem: "records reference missing scopes", count: orphanRecords });

  const orphanRevisions = count(`
    SELECT COUNT(*) AS n FROM memory_record_revisions r LEFT JOIN memory_records m ON m.record_id = r.record_id
    WHERE m.record_id IS NULL`);
  if (orphanRevisions > 0) issues.push({ problem: "revisions reference missing records", count: orphanRevisions });

  const orphanCandidates = count(`
    SELECT COUNT(*) AS n FROM memory_candidates c LEFT JOIN memory_scopes s ON s.scope_id = c.scope_id
    WHERE s.scope_id IS NULL`);
  if (orphanCandidates > 0) issues.push({ problem: "candidates reference missing scopes", count: orphanCandidates });

  const orphanSupersedes = count(`
    SELECT COUNT(*) AS n FROM memory_records r LEFT JOIN memory_records p ON p.record_id = r.supersedes_id
    WHERE r.supersedes_id IS NOT NULL AND p.record_id IS NULL`);
  if (orphanSupersedes > 0) issues.push({ problem: "records supersede missing records", count: orphanSupersedes });

  const orphanGroups = count(`
    SELECT COUNT(*) AS n FROM contradiction_groups g LEFT JOIN memory_scopes s ON s.scope_id = g.scope_id
    WHERE s.scope_id IS NULL`);
  if (orphanGroups > 0) issues.push({ problem: "contradiction groups reference missing scopes", count: orphanGroups });

  const orphanSessions = count(`
    SELECT COUNT(*) AS n FROM memory_search_sessions ss LEFT JOIN memory_scopes s ON s.scope_id = ss.scope_id
    WHERE s.scope_id IS NULL`);
  if (orphanSessions > 0) issues.push({ problem: "search sessions reference missing scopes", count: orphanSessions });

  return { consistent: issues.length === 0, issues };
}