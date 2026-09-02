/**
 * Memory health and retrieval quality instrumentation (Task 40).
 *
 * Measures intake/promotion/rejection, stale and contradicted records,
 * retrieval latency, index freshness, missing evidence, and rebuild health —
 * a single operational report for terminal/tool surfaces.
 *
 * - intake: candidate counts by status (open/promoted/rejected).
 * - staleRecords: active records whose validity window has lapsed but were
 *   not yet swept.
 * - contradictedRecords: records in OPEN contradiction groups.
 * - missingEvidence: non-deleted records with zero evidence references.
 * - index: lexical (FTS) freshness and embedding projection status from the
 *   projection-integrity report (docs/PROJECTIONS.md).
 * - rebuild: the unified projection integrity report (health of the derived
 *   indexes).
 * - retrieval: a bounded sample lexical query with hit count and latency (ms).
 */
import type { MemoryStore } from "./store.ts";
import { checkProjectionIntegrityImpl, type ProjectionStatus } from "./projections.ts";
import { lexicalSearchImpl } from "./retrieval.ts";

export interface MemoryHealthMetrics {
  store: { healthy: boolean; migrations: number[]; eventCount: number };
  intake: { open: number; promoted: number; rejected: number };
  staleRecords: number;
  contradictedRecords: number;
  missingEvidence: number;
  index: {
    lexical: { status: ProjectionStatus["status"]; detail?: string };
    embedding: { status: ProjectionStatus["status"]; detail?: string };
  };
  rebuild: { healthy: boolean; projections: ProjectionStatus[] };
  retrieval: { sampleQuery: string; sampleHits: number; sampleLatencyMs: number };
}

function count(db: { prepare(sql: string): { get(...p: unknown[]): unknown } }, sql: string, ...params: Array<string | number>): number {
  const row = db.prepare(sql).get(...params) as Record<string, unknown> | undefined;
  return Number((row ?? {})["n"] ?? 0);
}

/** Build the operational health + retrieval-quality report. */
export function memoryHealthImpl(store: MemoryStore): MemoryHealthMetrics {
  const db = store.ensureOpen();
  const doctor = store.doctor();
  const rebuild = checkProjectionIntegrityImpl(store, null, undefined);
  const lexical = rebuild.projections.find((p) => p.name === "lexical");
  const embedding = rebuild.projections.find((p) => p.name === "embedding");

  const intake = {
    open: count(db, "SELECT COUNT(*) AS n FROM memory_candidates WHERE status = 'open'"),
    promoted: count(db, "SELECT COUNT(*) AS n FROM memory_candidates WHERE status = 'promoted'"),
    rejected: count(db, "SELECT COUNT(*) AS n FROM memory_candidates WHERE status = 'rejected'"),
  };

  const now = new Date().toISOString();
  const staleRecords = count(
    db,
    "SELECT COUNT(*) AS n FROM memory_records WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < ?",
    now,
  );
  const contradictedRecords = count(
    db,
    "SELECT COUNT(*) AS n FROM memory_records WHERE status != 'deleted' AND contradiction_group_id IS NOT NULL",
  );
  const missingEvidence = count(
    db,
    "SELECT COUNT(*) AS n FROM memory_records WHERE status != 'deleted' AND evidence_json = '[]'",
  );

  // Bounded retrieval-quality sample: a lexical query measured for latency.
  const sampleQuery = "the";
  const started = process.hrtime.bigint();
  const sample = lexicalSearchImpl(store, sampleQuery, { status: "all", limit: 5 });
  const sampleLatencyMs = Number((process.hrtime.bigint() - started) / 1_000_000n);

  return {
    store: {
      healthy: doctor.healthy,
      migrations: store.appliedMigrationVersions(),
      eventCount: store.countEvents(),
    },
    intake,
    staleRecords,
    contradictedRecords,
    missingEvidence,
    index: {
      lexical: { status: lexical?.status ?? "unavailable", ...(lexical?.detail !== undefined ? { detail: lexical.detail } : {}) },
      embedding: { status: embedding?.status ?? "unavailable", ...(embedding?.detail !== undefined ? { detail: embedding.detail } : {}) },
    },
    rebuild: { healthy: rebuild.healthy, projections: rebuild.projections },
    retrieval: { sampleQuery, sampleHits: sample.hits.length, sampleLatencyMs },
  };
}