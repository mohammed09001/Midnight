/**
 * Canonical durable store for the Midnight Memory Engine.
 *
 * SQLite (node:sqlite built into Node.js) in WAL mode. Ownership rules:
 * - This store is the ONLY canonical state of the Memory Engine.
 * - Derived artifacts (embeddings, graphs, caches, context packs,
 *   projections) are NOT stored here and never silently become truth.
 * - Source/evidence payloads owned by sibling engines are referenced,
 *   never embedded.
 *
 * Failure behavior: open/migration failures surface as typed errors. There
 * is no silent in-memory fallback.
 */
import { mkdirSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import {
  MemoryEngineError,
  MigrationError,
  StoreUnavailableError,
} from "../contracts/errors.ts";
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import type { EngineEvent } from "../contracts/types.ts";
import { newId } from "./ids.ts";

export interface Migration {
  version: number;
  name: string;
  sql: string;
}

/**
 * Migration 1: foundation — schema bookkeeping and the engine event log
 * (cross-engine observability surface).
 */
const MIGRATION_001_FOUNDATION: Migration = {
  version: 1,
  name: "foundation_events",
  sql: `
    CREATE TABLE engine_events (
      event_id        TEXT PRIMARY KEY,
      contract_version TEXT NOT NULL,
      type            TEXT NOT NULL,
      payload_json    TEXT NOT NULL,
      created_at      TEXT NOT NULL
    );
    CREATE INDEX idx_engine_events_created ON engine_events(created_at);
    CREATE INDEX idx_engine_events_type ON engine_events(type);
  `,
};

/** Migration 2: scope identities and contradiction groups (Task 2). */
const MIGRATION_002_IDENTITIES: Migration = {
  version: 2,
  name: "identities_scopes_contradictions",
  sql: `
    CREATE TABLE memory_scopes (
      scope_id     TEXT PRIMARY KEY,
      project_key  TEXT NOT NULL UNIQUE,
      display_name TEXT NOT NULL,
      created_at   TEXT NOT NULL
    );

    CREATE TABLE contradiction_groups (
      group_id    TEXT PRIMARY KEY,
      scope_id    TEXT NOT NULL REFERENCES memory_scopes(scope_id),
      subject     TEXT NOT NULL,
      record_ids  TEXT NOT NULL DEFAULT '[]',
      created_at  TEXT NOT NULL
    );
  `,
};

/** Migration 3: canonical memory records, immutable revisions, candidates (Task 3). */
const MIGRATION_003_RECORDS: Migration = {
  version: 3,
  name: "canonical_records_revisions_candidates",
  sql: `
    CREATE TABLE memory_records (
      record_id            TEXT PRIMARY KEY,
      contract_version     TEXT NOT NULL,
      kind                 TEXT NOT NULL,
      subject              TEXT NOT NULL,
      content              TEXT NOT NULL,
      content_hash         TEXT NOT NULL,
      scope_id             TEXT NOT NULL REFERENCES memory_scopes(scope_id),
      provenance_json      TEXT NOT NULL,
      epistemic_class      TEXT NOT NULL,
      confidence           REAL NOT NULL,
      evidence_json        TEXT NOT NULL,
      relation_hints_json  TEXT NOT NULL,
      tags_json            TEXT NOT NULL,
      privacy_class        TEXT NOT NULL,
      valid_from           TEXT,
      valid_until          TEXT,
      status               TEXT NOT NULL,
      revision             INTEGER NOT NULL,
      created_at           TEXT NOT NULL,
      revised_at           TEXT NOT NULL,
      supersedes_id        TEXT REFERENCES memory_records(record_id),
      superseded_by_id     TEXT REFERENCES memory_records(record_id),
      contradiction_group_id TEXT REFERENCES contradiction_groups(group_id)
    );
    CREATE INDEX idx_records_scope ON memory_records(scope_id);
    CREATE INDEX idx_records_scope_status ON memory_records(scope_id, status);
    CREATE INDEX idx_records_subject ON memory_records(subject);
    CREATE INDEX idx_records_kind ON memory_records(kind);
    CREATE INDEX idx_records_supersedes ON memory_records(supersedes_id);
    CREATE INDEX idx_records_contradiction ON memory_records(contradiction_group_id);

    CREATE TABLE memory_record_revisions (
      record_id   TEXT NOT NULL REFERENCES memory_records(record_id),
      revision    INTEGER NOT NULL,
      content     TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      provenance_json TEXT NOT NULL,
      revised_at  TEXT NOT NULL,
      reason      TEXT,
      PRIMARY KEY (record_id, revision)
    );

    CREATE TABLE memory_candidates (
      candidate_id TEXT PRIMARY KEY,
      scope_id     TEXT NOT NULL REFERENCES memory_scopes(scope_id),
      kind         TEXT NOT NULL,
      subject      TEXT NOT NULL,
      content      TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      provenance_json TEXT NOT NULL,
      epistemic_class TEXT NOT NULL,
      confidence   REAL NOT NULL,
      evidence_json TEXT NOT NULL,
      tags_json    TEXT NOT NULL,
      status       TEXT NOT NULL,
      created_at   TEXT NOT NULL,
      promoted_record_id TEXT REFERENCES memory_records(record_id)
    );
    CREATE INDEX idx_candidates_scope_status ON memory_candidates(scope_id, status);
  `,
};

/**
 * Migration 4: bi-temporal fields and authority backfill (Tasks 4+5).
 * observed_at = valid time (when true in reality), defaulting to record
 * time for pre-existing rows; superseded_at stamps supersession;
 * provenance gains sourceKind (unknown) for pre-existing rows.
 */
const MIGRATION_004_TEMPORAL_AUTHORITY: Migration = {
  version: 4,
  name: "temporal_authority",
  sql: `
    ALTER TABLE memory_records ADD COLUMN observed_at TEXT;
    ALTER TABLE memory_records ADD COLUMN superseded_at TEXT;
    UPDATE memory_records SET observed_at = created_at WHERE observed_at IS NULL;
    UPDATE memory_records SET superseded_at = revised_at WHERE status = 'superseded' AND superseded_at IS NULL;
    UPDATE memory_records SET provenance_json = json_set(provenance_json, '$.sourceKind', 'unknown')
      WHERE json_extract(provenance_json, '$.sourceKind') IS NULL;
    UPDATE memory_candidates SET provenance_json = json_set(provenance_json, '$.sourceKind', 'unknown')
      WHERE json_extract(provenance_json, '$.sourceKind') IS NULL;
  `,
};

/**
 * Migration 5: append-oriented persistence + intake pipeline plumbing
 * (Tasks 7+8). Idempotency keys give replay-safe writes (unique indexes;
 * NULL keys stay distinct so legacy rows are untouched); candidates gain
 * reason/caller; scopes gain an intake policy.
 */
const MIGRATION_005_APPEND_INTAKE: Migration = {
  version: 5,
  name: "append_idempotency_intake",
  sql: `
    ALTER TABLE memory_records ADD COLUMN idempotency_key TEXT;
    CREATE UNIQUE INDEX idx_records_idempotency ON memory_records(idempotency_key);
    ALTER TABLE memory_candidates ADD COLUMN idempotency_key TEXT;
    CREATE UNIQUE INDEX idx_candidates_idempotency ON memory_candidates(idempotency_key);
    ALTER TABLE memory_candidates ADD COLUMN reason TEXT NOT NULL DEFAULT '';
    ALTER TABLE memory_candidates ADD COLUMN caller_json TEXT;
    ALTER TABLE memory_scopes ADD COLUMN intake_policy_json TEXT NOT NULL DEFAULT '{"mode":"open","allow":[]}';
  `,
};

/**
 * Migration 6: contradiction resolution + supersession reasons (Tasks 10+11).
 * Groups gain status/resolution (open groups await policy or user
 * resolution); records gain the explicit supersession reason.
 */
const MIGRATION_006_CONTRADICTION_SUPERSEDE: Migration = {
  version: 6,
  name: "contradiction_resolution_supersede_reason",
  sql: `
    ALTER TABLE contradiction_groups ADD COLUMN status TEXT NOT NULL DEFAULT 'open';
    ALTER TABLE contradiction_groups ADD COLUMN resolution_json TEXT;
    ALTER TABLE memory_records ADD COLUMN supersede_reason TEXT;
  `,
};

/**
 * Migration 7: retention, archival, and deletion semantics (Task 13).
 * Records gain archive/tombstone metadata; scopes gain deletion metadata
 * (project deletion propagates, identity is retained).
 */
const MIGRATION_007_RETENTION: Migration = {
  version: 7,
  name: "retention_archival_deletion",
  sql: `
    ALTER TABLE memory_records ADD COLUMN archived_at TEXT;
    ALTER TABLE memory_records ADD COLUMN deleted_at TEXT;
    ALTER TABLE memory_records ADD COLUMN deleted_by TEXT;
    ALTER TABLE memory_records ADD COLUMN delete_reason TEXT;
    ALTER TABLE memory_scopes ADD COLUMN deleted_at TEXT;
    ALTER TABLE memory_scopes ADD COLUMN deleted_by TEXT;
    ALTER TABLE memory_scopes ADD COLUMN delete_reason TEXT;
  `,
};

/**
 * Migration 8: deterministic lexical search index (Task 15).
 *
 * FTS5 external-content index over memory_records (subject, content,
 * tags) — a REBUILDABLE DERIVED INDEX: canonical truth stays in
 * memory_records; the index is discardable and rebuildable at any time
 * ('rebuild' command). Kept consistent via the trigger pattern from the
 * official FTS5 docs (sqlite.org/fts5.html §4.4.3, accessed 2026-08-30).
 * unicode61 tokenizer: case-insensitive, no stemming (exact-term search).
 */
const MIGRATION_008_LEXICAL_INDEX: Migration = {
  version: 8,
  name: "lexical_fts_index",
  sql: `
    CREATE VIRTUAL TABLE memory_fts USING fts5(
      subject, content, tags_json,
      content='memory_records', content_rowid='rowid',
      tokenize='unicode61'
    );
    CREATE TRIGGER memory_fts_ai AFTER INSERT ON memory_records BEGIN
      INSERT INTO memory_fts(rowid, subject, content, tags_json)
      VALUES (new.rowid, new.subject, new.content, new.tags_json);
    END;
    CREATE TRIGGER memory_fts_ad AFTER DELETE ON memory_records BEGIN
      INSERT INTO memory_fts(memory_fts, rowid, subject, content, tags_json)
      VALUES ('delete', old.rowid, old.subject, old.content, old.tags_json);
    END;
    CREATE TRIGGER memory_fts_au AFTER UPDATE OF subject, content, tags_json ON memory_records BEGIN
      INSERT INTO memory_fts(memory_fts, rowid, subject, content, tags_json)
      VALUES ('delete', old.rowid, old.subject, old.content, old.tags_json);
      INSERT INTO memory_fts(rowid, subject, content, tags_json)
      VALUES (new.rowid, new.subject, new.content, new.tags_json);
    END;
    INSERT INTO memory_fts(memory_fts) VALUES ('rebuild');
  `,
};

/**
 * Migration 9: optional semantic embedding projection (Task 23).
 *
 * DERIVED tables only — never canonical truth. `memory_embeddings` holds the
 * per-record embedding vector with its producing provider/model/version;
 * `memory_embedding_projections` holds the per-scope build metadata (record
 * model/version, dimensions, privacy-gate skips). Both are completely
 * rebuildable (`rebuildEmbeddingProjection`) and can be dropped and rebuilt
 * from canonical records at any time. Privacy gate: only records that passed
 * the gate at build time are stored here; tombstoned content is never embedded.
 */
const MIGRATION_009_EMBEDDING_PROJECTION: Migration = {
  version: 9,
  name: "embedding_projection",
  sql: `
    CREATE TABLE memory_embeddings (
      record_id    TEXT PRIMARY KEY REFERENCES memory_records(record_id),
      vector_json  TEXT NOT NULL,
      provider     TEXT NOT NULL,
      model        TEXT NOT NULL,
      version      TEXT NOT NULL,
      embedded_at  TEXT NOT NULL
    );
    CREATE TABLE memory_embedding_projections (
      scope_id       TEXT PRIMARY KEY REFERENCES memory_scopes(scope_id),
      provider       TEXT NOT NULL,
      model          TEXT NOT NULL,
      version        TEXT NOT NULL,
      vector_dim     INTEGER NOT NULL,
      record_count   INTEGER NOT NULL,
      skipped_privacy INTEGER NOT NULL,
      built_at       TEXT NOT NULL
    );
  `,
};

const MIGRATION_010_SEARCH_SESSIONS: Migration = {
  version: 10,
  name: "search_sessions",
  sql: `
    CREATE TABLE memory_search_sessions (
      search_session_id   TEXT PRIMARY KEY,
      scope_id            TEXT NOT NULL REFERENCES memory_scopes(scope_id),
      intent              TEXT NOT NULL,
      actor_json          TEXT,
      observed_at         TEXT NOT NULL,
      created_at          TEXT NOT NULL,
      result_refs_json    TEXT NOT NULL DEFAULT '[]',
      candidate_refs_json TEXT NOT NULL DEFAULT '[]',
      note                TEXT
    );
    CREATE INDEX idx_search_sessions_scope_created ON memory_search_sessions(scope_id, created_at);
  `,
};

const MIGRATION_011_MUTATION_POLICY: Migration = {
  version: 11,
  name: "mutation_policy",
  sql: `
    ALTER TABLE memory_scopes ADD COLUMN mutation_policy_json TEXT NOT NULL DEFAULT '{"mode":"open","allow":[]}';
  `,
};

const MIGRATION_012_PRIVACY_POLICY: Migration = {
  version: 12,
  name: "privacy_policy",
  sql: `
    ALTER TABLE memory_scopes ADD COLUMN privacy_policy_json TEXT NOT NULL DEFAULT '{"content":{"exportable":["public","internal"],"forbidSensitive":false}}';
  `,
};

export const MIGRATIONS: readonly Migration[] = [
  MIGRATION_001_FOUNDATION,
  MIGRATION_002_IDENTITIES,
  MIGRATION_003_RECORDS,
  MIGRATION_004_TEMPORAL_AUTHORITY,
  MIGRATION_005_APPEND_INTAKE,
  MIGRATION_006_CONTRADICTION_SUPERSEDE,
  MIGRATION_007_RETENTION,
  MIGRATION_008_LEXICAL_INDEX,
  MIGRATION_009_EMBEDDING_PROJECTION,
  MIGRATION_010_SEARCH_SESSIONS,
  MIGRATION_011_MUTATION_POLICY,
  MIGRATION_012_PRIVACY_POLICY,
];

export class MemoryStore {
  readonly storePath: string;
  /** True when this open created the store file for the first time. */
  readonly created: boolean;

  private db: DatabaseSync | null = null;
  private appliedVersions: number[] = [];

  constructor(storePath: string) {
    this.storePath = resolve(storePath);
    this.created = !existsSync(this.storePath);
  }

  /** Open (creating/migrating as needed). Idempotent across restarts. */
  open(): this {
    if (this.db !== null) return this;
    let opened: DatabaseSync | null = null;
    try {
      mkdirSync(dirname(this.storePath), { recursive: true });
      const db = new DatabaseSync(this.storePath);
      opened = db;
      db.exec("PRAGMA journal_mode = WAL;");
      db.exec("PRAGMA foreign_keys = ON;");
      db.exec("PRAGMA busy_timeout = 5000;");
      this.migrate(db);
      this.db = db;
      return this;
    } catch (err) {
      // Release the partial handle so the file is not locked on Windows.
      try {
        opened?.close();
      } catch {
        // Closing a failed open may itself fail; nothing more to do.
      }
      this.db = null;
      if (err instanceof MemoryEngineError) throw err;
      throw new StoreUnavailableError(
        `Failed to open memory store at ${this.storePath}: ${describe(err)}`,
        { cause: err },
      );
    }
  }

  private migrate(db: DatabaseSync): void {
    try {
      db.exec(`
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    INTEGER PRIMARY KEY,
          name       TEXT NOT NULL,
          applied_at TEXT NOT NULL
        );
      `);
      const applied = new Set(
        db
          .prepare("SELECT version FROM schema_migrations")
          .all()
          .map((r) => Number((r as Record<string, unknown>)["version"])),
      );
      for (const migration of MIGRATIONS) {
        if (applied.has(migration.version)) continue;
        db.exec("BEGIN IMMEDIATE;");
        try {
          db.exec(migration.sql);
          db.prepare(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
          ).run(migration.version, migration.name, new Date().toISOString());
          db.exec("COMMIT;");
        } catch (txErr) {
          db.exec("ROLLBACK;");
          throw txErr;
        }
      }
      this.appliedVersions = db
        .prepare("SELECT version FROM schema_migrations ORDER BY version")
        .all()
        .map((r) => Number((r as Record<string, unknown>)["version"]));
    } catch (err) {
      if (err instanceof MemoryEngineError) throw err;
      throw new MigrationError(
        `Migration failed for ${this.storePath}: ${describe(err)}`,
        { cause: err },
      );
    }
  }

  appliedMigrationVersions(): number[] {
    this.ensureOpen();
    return [...this.appliedVersions];
  }

  ensureOpen(): DatabaseSync {
    if (this.db === null) {
      this.open();
    }
    return this.db!;
  }

  close(): void {
    if (this.db !== null) {
      this.db.close();
      this.db = null;
    }
  }

  /**
   * Health check for observability/degraded-state reporting. Never throws:
   * reports unhealthy with a typed error code instead.
   */
  doctor(): {
    healthy: boolean;
    integrity: string | null;
    journalMode: string | null;
    errorCode?: string;
    errorMessage?: string;
  } {
    try {
      const db = this.ensureOpen();
      const integrity = String(
        (db.prepare("PRAGMA integrity_check").get() as Record<string, unknown>)[
          "integrity_check"
        ],
      );
      const journalMode = String(
        (db.prepare("PRAGMA journal_mode").get() as Record<string, unknown>)[
          "journal_mode"
        ],
      );
      const healthy = integrity === "ok";
      return {
        healthy,
        integrity,
        journalMode,
        ...(healthy ? {} : { errorCode: "MEMORY_STORE_UNAVAILABLE", errorMessage: `integrity_check=${integrity}` }),
      };
    } catch (err) {
      const code = err instanceof MemoryEngineError ? err.code : "MEMORY_STORE_UNAVAILABLE";
      return {
        healthy: false,
        integrity: null,
        journalMode: null,
        errorCode: code,
        errorMessage: describe(err),
      };
    }
  }

  /**
   * Append an engine event (cross-engine observability). Events are the
   * versioned notification surface for sibling engines; they never carry
   * another engine's payload bodies, only record-level references.
   */
  appendEvent(type: string, payload: unknown): EngineEvent {
    const db = this.ensureOpen();
    const event: EngineEvent = {
      eventId: newId("evt"),
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      type,
      payload,
      createdAt: new Date().toISOString(),
    };
    db.prepare(
      `INSERT INTO engine_events (event_id, contract_version, type, payload_json, created_at)
       VALUES (?, ?, ?, ?, ?)`,
    ).run(
      event.eventId,
      event.contractVersion,
      event.type,
      JSON.stringify(event.payload),
      event.createdAt,
    );
    return event;
  }

  listEvents(limit: number): EngineEvent[] {
    const db = this.ensureOpen();
    const rows = db
      .prepare(
        `SELECT event_id, contract_version, type, payload_json, created_at
         FROM engine_events ORDER BY created_at DESC, event_id DESC LIMIT ?`,
      )
      .all(limit) as Array<Record<string, unknown>>;
    return rows.map((r) => ({
      eventId: String(r["event_id"]),
      contractVersion: String(r["contract_version"]),
      type: String(r["type"]),
      payload: JSON.parse(String(r["payload_json"])),
      createdAt: String(r["created_at"]),
    }));
  }

  countEvents(): number {
    const db = this.ensureOpen();
    const row = db.prepare("SELECT COUNT(*) AS n FROM engine_events").get() as Record<
      string,
      unknown
    >;
    return Number(row["n"]);
  }

  /**
   * Append-integrity check (Task 7): the immutable revision log is the
   * truth of record content; the memory_records row is a projection.
   * Verifies every record has an unbroken revision chain 1..revision and
   * that its projected content hash matches the newest revision row.
   */
  checkAppendIntegrity(): {
    consistent: boolean;
    recordCount: number;
    broken: Array<{ recordId: string; problem: string }>;
  } {
    const db = this.ensureOpen();
    const records = db
      .prepare("SELECT record_id, revision, content_hash FROM memory_records")
      .all() as Array<Record<string, unknown>>;
    const broken: Array<{ recordId: string; problem: string }> = [];
    for (const row of records) {
      const recordId = String(row["record_id"]);
      const revision = Number(row["revision"]);
      const projectedHash = String(row["content_hash"]);
      const revisions = db
        .prepare(
          "SELECT revision, content_hash FROM memory_record_revisions WHERE record_id = ? ORDER BY revision",
        )
        .all(recordId) as Array<Record<string, unknown>>;
      const numbers = revisions.map((r) => Number(r["revision"]));
      const unbroken =
        numbers.length === revision &&
        numbers.every((n, i) => n === i + 1) &&
        numbers[0] === 1;
      if (!unbroken) {
        broken.push({ recordId, problem: `revision chain broken: expected 1..${revision}, got [${numbers.join(",")}]` });
        continue;
      }
      const newestHash = String(revisions[revisions.length - 1]!["content_hash"]);
      if (newestHash !== projectedHash) {
        broken.push({ recordId, problem: "projected content hash differs from newest revision (log is truth)" });
      }
    }
    return { consistent: broken.length === 0, recordCount: records.length, broken };
  }

  /**
   * Repair the record projection from the append-only revision log
   * (Task 7 recovery). Rebuilds content, content hash, and revision
   * counter from the newest immutable revision row. Status/provenance are
   * NOT derived from the log (they are row-level state), only the
   * append-log-owned fields are repaired.
   */
  repairRecordProjection(recordId: string): { repaired: boolean; detail: string } {
    const db = this.ensureOpen();
    const newest = db
      .prepare(
        "SELECT revision, content, content_hash, revised_at FROM memory_record_revisions WHERE record_id = ? ORDER BY revision DESC LIMIT 1",
      )
      .get(recordId) as Record<string, unknown> | undefined;
    if (newest === undefined) {
      return { repaired: false, detail: `no revision rows for '${recordId}' — log holds nothing to repair from` };
    }
    const revision = Number(newest["revision"]);
    const content = String(newest["content"]);
    const contentHash = String(newest["content_hash"]);
    const current = db
      .prepare("SELECT content_hash, revision FROM memory_records WHERE record_id = ?")
      .get(recordId) as Record<string, unknown> | undefined;
    if (current === undefined) {
      return { repaired: false, detail: `record '${recordId}' does not exist` };
    }
    const needsRepair =
      String(current["content_hash"]) !== contentHash || Number(current["revision"]) !== revision;
    if (!needsRepair) {
      return { repaired: false, detail: "projection already consistent with the log" };
    }
    db.prepare(
      "UPDATE memory_records SET content = ?, content_hash = ?, revision = ?, revised_at = ? WHERE record_id = ?",
    ).run(content, contentHash, revision, String(newest["revised_at"]), recordId);
    this.appendEvent("memory.record.repaired", { recordId, revision });
    return { repaired: true, detail: `projection rebuilt from revision ${revision} of the append log` };
  }
}

function describe(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
