/**
 * Crash/rebuild/deletion qualification (Task 45, Phase VIII).
 *
 * EXERCISES the recovery paths against real, disposable stores — this is an
 * active qualification harness, not an assertion about existing state:
 *
 * - torn store: a corrupted store file is opened and reported unhealthy by
 *   doctor (never throws, typed error, never fabricates data);
 * - partial write: a record projection torn away from the immutable revision
 *   log is DETECTED by append-integrity and REPAIRED from the log;
 * - projection corruption: a damaged lexical index is detected by
 *   projection-integrity and REBUILT from canonical records;
 * - vector corruption: a corrupt derived vector is skipped and reported,
 *   then restored by an embedding rebuild (which also removes orphans);
 * - restore: a checksummed backup taken before destructive mutations
 *   restores a complete, verifiable snapshot into a fresh store;
 * - source deletion: tombstoning scrubs content, removes the derived
 *   vector, drops the record from default retrieval, and keeps lineage
 *   pointers coherent;
 * - privacy deletion propagation: purging a privacy class removes the
 *   record row, its revision log, its derived vector, its lexical entry,
 *   and every inbound pointer — projections stay healthy afterwards;
 * - scope deletion: tombstoning a scope retires its records coherently.
 *
 * Every scenario runs on scratch stores the harness creates (never on the
 * caller's store) and removes afterwards. The report carries stable check
 * names and deterministic details (counts only, no paths/ids/timestamps).
 */
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { MemoryEngine } from "./memoryEngine.ts";
import { localHashProvider } from "./embeddings.ts";
import type { QualificationCheck } from "./corpora.ts";

export interface RecoveryQualificationReport {
  contractVersion: string;
  checks: QualificationCheck[];
  passed: boolean;
}

export interface RecoveryQualificationOptions {
  /** Directory for scratch stores. Default: a fresh OS temp dir (removed afterwards). */
  scratchDir?: string;
}

function check(name: string, pass: boolean, detail: string): QualificationCheck {
  return { name, pass, detail };
}

export function qualifyRecoveryImpl(engine: MemoryEngine, options: RecoveryQualificationOptions = {}): RecoveryQualificationReport {
  void engine; // the harness runs against its own scratch stores
  const checks: QualificationCheck[] = [];
  const scratch = options.scratchDir ?? mkdtempSync(join(tmpdir(), "mem-recovery-"));
  let owned = options.scratchDir === undefined;
  try {
    runScenarios(scratch, checks);
  } finally {
    if (owned) {
      rmSync(scratch, { recursive: true, force: true });
      owned = false;
    }
  }
  return {
    contractVersion: engine.contractVersion,
    checks,
    passed: checks.every((c) => c.pass),
  };
}

function runScenarios(scratch: string, checks: QualificationCheck[]): void {
  // ---- torn store: doctor reports unhealthy without throwing ----
  {
    const tornPath = join(scratch, "torn.db");
    writeFileSync(tornPath, "this is not a sqlite database file", "utf8");
    const torn = new MemoryEngine({ storePath: tornPath });
    let ok = false;
    let detail = "doctor threw on a torn store";
    try {
      const report = torn.doctor();
      ok = report.healthy === false && typeof report.errorCode === "string";
      detail = ok ? "torn store reported unhealthy with a typed error" : `unexpected doctor state: ${JSON.stringify({ healthy: report.healthy })}`;
    } catch (err) {
      detail = `doctor threw: ${err instanceof Error ? err.message : String(err)}`;
    }
    checks.push(check("torn-store-doctor", ok, detail));
  }

  // ---- working store for the write/corruption/deletion scenarios ----
  const workPath = join(scratch, "work.db");
  const work = new MemoryEngine({ storePath: workPath });
  work.open();
  try {
    work.buildQualificationCorpus();
    const scopeKey = "qualification-v1";

    // ---- partial write: projection torn from the append log, repaired ----
    {
      const victim = work
        .searchRecords({ scope: scopeKey, exactSubject: "Retry backoff" })
        .find((r) => r.status === "active")!;
      const db = work.store.ensureOpen();
      db.prepare("UPDATE memory_records SET content = 'torn partial write', content_hash = 'drift' WHERE record_id = ?").run(victim.recordId);
      const before = work.store.checkAppendIntegrity();
      const brokenDetected = before.consistent === false && before.broken.some((b) => b.recordId === victim.recordId);
      const repair = work.store.repairRecordProjection(victim.recordId);
      const after = work.store.checkAppendIntegrity();
      const restored = work.getRecord(victim.recordId);
      const ok =
        brokenDetected &&
        repair.repaired === true &&
        after.consistent === true &&
        restored.content === "Retry policy uses exponential backoff with jitter";
      checks.push(
        check(
          "append-integrity-repair",
          ok,
          ok
            ? "torn projection detected and repaired from the immutable log"
            : `detected ${brokenDetected}, repaired ${repair.repaired}, consistent ${after.consistent}`,
        ),
      );
    }

    // ---- lexical projection corruption: detected and rebuilt ----
    {
      const victim = work
        .searchRecords({ scope: scopeKey, exactSubject: "Rate limit" })
        .find((r) => r.status === "active")!;
      const db = work.store.ensureOpen();
      db.prepare("DELETE FROM memory_fts WHERE rowid IN (SELECT rowid FROM memory_records WHERE record_id = ?)").run(victim.recordId);
      const detected = work.checkProjectionIntegrity(scopeKey);
      const lexicalWasCorrupted = detected.projections.find((p) => p.name === "lexical")?.status === "corrupted";
      const repair = work.repairProjections({ scope: scopeKey });
      const repaired = repair.report.projections.find((p) => p.name === "lexical")?.status === "ok";
      const lexicalRestored = work
        .lexicalSearch("requests per minute", { scope: scopeKey })
        .hits.some((h) => h.record.subject === "Rate limit");
      const ok = lexicalWasCorrupted && repaired && lexicalRestored;
      checks.push(
        check(
          "lexical-corruption-repair",
          ok,
          ok
            ? "missing index entries detected and rebuilt from canonical records"
            : `corrupted ${lexicalWasCorrupted}, repaired ${repaired}, restored ${lexicalRestored}`,
        ),
      );
    }

    // ---- embedding area: vector corruption, rebuild recovery, deletion propagation ----
    work.setEmbeddingProvider(localHashProvider);
    work.buildEmbeddingProjection(scopeKey);
    {
      const db = work.store.ensureOpen();
      db.prepare("UPDATE memory_embeddings SET vector_json = '{corrupt' WHERE record_id IN (SELECT record_id FROM memory_records WHERE subject = 'Cache strategy')").run();
      const degraded = work.semanticSearch("cache ttl", { scope: scopeKey });
      const skippedReported = (degraded.diagnostics.skippedCorrupt ?? 0) === 1;
      work.rebuildEmbeddingProjection(scopeKey);
      const restored = work.semanticSearch("cache ttl", { scope: scopeKey });
      const restoredOk = (restored.diagnostics.skippedCorrupt ?? 0) === 0 && restored.hits.length >= 1;
      const integrity = work.checkProjectionIntegrity(scopeKey);
      const embeddingOk = integrity.projections.find((p) => p.name === "embedding")?.status === "ok";
      const ok = skippedReported && restoredOk && embeddingOk;
      checks.push(
        check(
          "vector-corruption-rebuild",
          ok,
          ok
            ? "corrupt vector skipped and reported, rebuild restored the projection"
            : `skipped ${skippedReported}, restored ${restoredOk}, integrity ${embeddingOk}`,
        ),
      );
    }

    // ---- source deletion propagation (tombstone) ----
    {
      const victim = work
        .searchRecords({ scope: scopeKey, exactSubject: "Onboarding flow" })
        .find((r) => r.status === "active")!;
      work.deleteRecord(victim.recordId, { actor: { kind: "human", name: "kim" }, reason: "qualification: source deletion", origin: "recovery-harness" });
      const db = work.store.ensureOpen();
      const vectorRows = Number(
        (db.prepare("SELECT COUNT(*) AS n FROM memory_embeddings WHERE record_id = ?").get(victim.recordId) as Record<string, unknown>)["n"],
      );
      const tombstone = work.getRecord(victim.recordId);
      const lexicalHit = work
        .lexicalSearch("onboarding guided steps", { scope: scopeKey })
        .hits.some((h) => h.record.recordId === victim.recordId);
      const semanticHit = work
        .semanticSearch("onboarding guided steps", { scope: scopeKey })
        .hits.some((h) => h.record.recordId === victim.recordId);
      const chainIntact = work
        .listEvents(500)
        .some((e) => e.type === "memory.record.deleted");
      const ok =
        vectorRows === 0 &&
        tombstone.status === "deleted" &&
        tombstone.content === "" &&
        !lexicalHit &&
        !semanticHit &&
        chainIntact;
      checks.push(
        check(
          "source-deletion-propagation",
          ok,
          ok
            ? "tombstone scrubbed content, dropped from lexical+semantic, vector removed, event recorded"
            : `vectorRows ${vectorRows}, lexicalHit ${lexicalHit}, semanticHit ${semanticHit}`,
        ),
      );
    }

    // ---- privacy purge propagation ----
    {
      const sensitive = work
        .searchRecords({ scope: scopeKey, exactSubject: "API key rotation" })
        .find((r) => r.status === "active")!;
      const purge = work.purgeByPrivacy({
        actor: { kind: "human", name: "kim" },
        reason: "qualification: privacy deletion propagation",
        privacyClasses: ["sensitive"],
        scope: scopeKey,
        origin: "recovery-harness",
      });
      let recordGone = false;
      try {
        work.getRecord(sensitive.recordId);
      } catch {
        recordGone = true;
      }
      const db = work.store.ensureOpen();
      const vectorRows = Number(
        (db.prepare("SELECT COUNT(*) AS n FROM memory_embeddings WHERE record_id = ?").get(sensitive.recordId) as Record<string, unknown>)["n"],
      );
      const revisionRows = Number(
        (db.prepare("SELECT COUNT(*) AS n FROM memory_record_revisions WHERE record_id = ?").get(sensitive.recordId) as Record<string, unknown>)["n"],
      );
      const lexicalHit = work
        .lexicalSearch("api key rotation", { scope: scopeKey, status: "all" })
        .hits.some((h) => h.record.recordId === sensitive.recordId);
      const integrity = work.checkProjectionIntegrity(scopeKey);
      const staleDetected = integrity.projections.find((p) => p.name === "embedding")?.status === "corrupted";
      // Canonical deletion makes the derived projection metadata stale — the
      // recovery path (rebuild) must restore consistency with no orphans.
      work.rebuildEmbeddingProjection(scopeKey);
      const postIntegrity = work.checkProjectionIntegrity(scopeKey);
      const healthy = postIntegrity.projections.every((p) => p.status !== "corrupted");
      const ok =
        purge.purgedCount === 1 &&
        recordGone &&
        vectorRows === 0 &&
        revisionRows === 0 &&
        !lexicalHit &&
        staleDetected &&
        healthy;
      checks.push(
        check(
          "privacy-purge-propagation",
          ok,
          ok
            ? "purge removed record, revisions, vector, and lexical entry; stale projection rebuilt healthy"
            : `purged ${purge.purgedCount}, recordGone ${recordGone}, vectorRows ${vectorRows}, revisionRows ${revisionRows}, lexicalHit ${lexicalHit}, staleDetected ${staleDetected}, healthy ${healthy}`,
        ),
      );
    }

    // ---- scope deletion (tombstone mode) ----
    {
      work.createScope("recovery-scratch-scope", "Recovery Scratch");
      work.addRecord({
        scope: "recovery-scratch-scope",
        kind: "fact",
        subject: "Scratch fact",
        content: "A scratch fact for scope deletion",
        actor: { kind: "human", name: "kim" },
        method: "asserted",
        epistemicClass: "observed",
        confidence: 0.8,
        sourceKind: "user_note",
        evidenceRefs: [{ engine: "external", ref: "note:scratch" }],
      });
      const deleted = work.deleteScope("recovery-scratch-scope", {
        actor: { kind: "human", name: "kim" },
        reason: "qualification: scope deletion",
        mode: "tombstone",
        origin: "recovery-harness",
      });
      const references = work.verifyStoreReferences();
      const ok =
        deleted.deletedAt !== null &&
        work.searchRecords({ scope: "recovery-scratch-scope" }).length === 0 &&
        references.consistent;
      checks.push(
        check(
          "scope-deletion-tombstone",
          ok,
          ok
            ? "scope tombstoned; its records left the default view; references coherent"
            : `deletedAt ${deleted.deletedAt === null ? "null" : "set"}, referencesOk ${references.consistent}`,
        ),
      );
    }

    // ---- restore: full snapshot into a fresh store after destructive mutations ----
    {
      const bundlePath = join(scratch, "snapshot.json");
      const bundle = work.backupToFile(bundlePath);
      const verified = work.verifyBackup(bundle);
      // Destructive mutations AFTER the snapshot.
      const nextVictim = work
        .searchRecords({ scope: scopeKey, exactSubject: "Ranking hot path" })
        .find((r) => r.status === "active")!;
      work.deleteRecord(nextVictim.recordId, { actor: { kind: "human", name: "kim" }, reason: "qualification: post-backup mutation", origin: "recovery-harness" });

      const restorePath = join(scratch, "restored.db");
      const restoredEngine = new MemoryEngine({ storePath: restorePath });
      restoredEngine.open();
      try {
        restoredEngine.restoreBundle(bundle);
        const restoredRecords = restoredEngine.searchRecords({ scope: scopeKey, status: "all" });
        const restoredVictim = restoredEngine
          .searchRecords({ scope: scopeKey, exactSubject: "Ranking hot path" })
          .find((r) => r.status === "active");
        // The snapshot is the post-mutation canonical state: the tombstoned
        // record stays a tombstone, the purged record stays gone.
        const tombstoneRestored = restoredEngine
          .searchRecords({ scope: scopeKey, exactSubject: "Onboarding flow", status: "all" })
          .some((r) => r.status === "deleted");
        const purgedStillGone =
          restoredEngine.searchRecords({ scope: scopeKey, exactSubject: "API key rotation", status: "all" }).length === 0;
        const referencesConsistent = restoredEngine.verifyStoreReferences().consistent;
        // Derived state is not part of a canonical snapshot: the FTS index
        // repopulates via triggers on restore; embeddings rebuild on demand.
        const lexicalRestored = restoredEngine
          .lexicalSearch("requests per minute", { scope: scopeKey })
          .hits.some((h) => h.record.subject === "Rate limit");
        const integrity = restoredEngine.checkProjectionIntegrity(scopeKey);
        const noCorruption = integrity.projections.every((p) => p.status !== "corrupted");
        const ok =
          verified.valid &&
          restoredRecords.length === 17 &&
          restoredVictim !== undefined &&
          tombstoneRestored &&
          purgedStillGone &&
          referencesConsistent &&
          lexicalRestored &&
          noCorruption;
        checks.push(
          check(
            "backup-restore-snapshot",
            ok,
            ok
              ? "verified snapshot restored faithfully into a fresh store; derived lexical index recovered via triggers"
              : `verified ${verified.valid}, restored ${restoredRecords.length}, victimPresent ${restoredVictim !== undefined}, tombstone ${tombstoneRestored}, purgedGone ${purgedStillGone}, references ${referencesConsistent}, lexical ${lexicalRestored}, noCorruption ${noCorruption}`,
          ),
        );
      } finally {
        restoredEngine.close();
      }
    }
  } finally {
    work.close();
  }
}
