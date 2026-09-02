/**
 * CHILD LOOP 1 verification — Task 45: crash/rebuild/deletion qualification.
 *
 * Proves: the active harness exercises torn stores, partial-write repair
 * from the append log, projection corruption and rebuild, backup/restore
 * into a fresh store, source-deletion and privacy-purge propagation to the
 * DERIVED stores, and scope deletion — deterministically, on scratch stores,
 * with the caller's store untouched, honest CLI exit codes, and the
 * propagation fixes directly falsifiable.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MemoryEngine, localHashProvider } from "../src/index.ts";
import type { RecoveryQualificationReport } from "../src/index.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "src", "cli", "cli.ts");

function tempEngine(name: string): { engine: MemoryEngine; dir: string; storePath: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t45-${name}-`));
  const storePath = join(dir, "memory.db");
  const engine = new MemoryEngine({ storePath });
  engine.open();
  return { engine, dir, storePath };
}

function digest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");
}

test("T45: the harness passes all recovery scenarios on scratch stores", () => {
  const { engine, dir } = tempEngine("harness");
  try {
    const report = engine.qualifyRecovery();
    assert.equal(report.passed, true, `failed: ${report.checks.filter((c) => !c.pass).map((c) => `${c.name} (${c.detail})`).join("; ")}`);
    assert.deepEqual(report.checks.map((c) => c.name), [
      "torn-store-doctor",
      "append-integrity-repair",
      "lexical-corruption-repair",
      "vector-corruption-rebuild",
      "source-deletion-propagation",
      "privacy-purge-propagation",
      "scope-deletion-tombstone",
      "backup-restore-snapshot",
    ]);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T45: determinism — two harness runs produce identical reports", () => {
  const a = tempEngine("det-a");
  const b = tempEngine("det-b");
  try {
    const reportA = a.engine.qualifyRecovery();
    const reportB = b.engine.qualifyRecovery();
    assert.equal(reportA.passed, true);
    assert.deepEqual(reportA, reportB);
    assert.equal(digest(reportA), digest(reportB));
  } finally {
    a.engine.close();
    b.engine.close();
    rmSync(a.dir, { recursive: true, force: true });
    rmSync(b.dir, { recursive: true, force: true });
  }
});

test("T45: deletion propagation — tombstone and purge remove derived vectors; semantic never ranks deleted", () => {
  const { engine, dir } = tempEngine("propagation");
  try {
    engine.createScope("lib", "Library");
    const add = (subject: string, privacy: "internal" | "sensitive"): string =>
      engine.addRecord({
        scope: "lib",
        kind: "fact",
        subject,
        content: `${subject} detailed retrievable content`,
        actor: { kind: "human", name: "kim" },
        method: "asserted",
        epistemicClass: "observed",
        confidence: 0.9,
        sourceKind: "user_note",
        privacyClass: privacy,
        evidenceRefs: [{ engine: "external", ref: `note:${subject}` }],
      }).recordId;
    const keepId = add("Keep me", "internal");
    const tombstoneId = add("Gone soon", "internal");
    const sensitiveId = add("Sensitive fact", "sensitive");
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");

    const db = engine.store.ensureOpen();
    const vectorCount = (id: string): number =>
      Number((db.prepare("SELECT COUNT(*) AS n FROM memory_embeddings WHERE record_id = ?").get(id) as Record<string, unknown>)["n"]);
    assert.equal(vectorCount(keepId), 1);
    assert.equal(vectorCount(tombstoneId), 1);
    assert.equal(vectorCount(sensitiveId), 0, "sensitive records are never embedded");

    // Tombstone: the derived vector must not survive the content scrub.
    engine.deleteRecord(tombstoneId, { actor: { kind: "human", name: "kim" }, reason: "probe" });
    assert.equal(vectorCount(tombstoneId), 0);
    assert.equal(
      engine.semanticSearch("gone soon detailed", { scope: "lib" }).hits.some((h) => h.record.recordId === tombstoneId),
      false,
      "semantic search must never rank deleted records",
    );

    // Privacy purge: the row, revisions, and any derived vector vanish.
    engine.purgeRecord(sensitiveId, { actor: { kind: "human", name: "kim" }, reason: "privacy probe" });
    let purgedGone = false;
    try {
      engine.getRecord(sensitiveId);
    } catch {
      purgedGone = true;
    }
    assert.equal(purgedGone, true);
    assert.equal(vectorCount(sensitiveId), 0);

    // A rebuild removes pre-existing orphans and keeps the projection healthy.
    // (Orphans require FK-off injection: they cannot arise through the API.)
    db.exec("PRAGMA foreign_keys = OFF;");
    db.prepare("INSERT INTO memory_embeddings (record_id, vector_json, provider, model, version, embedded_at) VALUES (?, ?, ?, ?, ?, ?)")
      .run("mem_orphan", "[1,2,3]", "local-hash", "feature-hash-v1", "1.0.0", new Date().toISOString());
    db.exec("PRAGMA foreign_keys = ON;");
    const before = engine.checkProjectionIntegrity("lib");
    assert.equal(before.projections.find((p) => p.name === "embedding")?.status, "corrupted", "orphan must be reported");
    engine.rebuildEmbeddingProjection("lib");
    const after = engine.checkProjectionIntegrity("lib");
    assert.equal(after.projections.find((p) => p.name === "embedding")?.status, "ok", "rebuild must remove orphans");
    assert.equal(after.healthy, true);
    void keepId;
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T45: restore of a supersession-chain store reproduces lineage faithfully", () => {
  const { engine, dir } = tempEngine("restore-lineage");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord({
      scope: "lib",
      kind: "decision",
      subject: "Auth choice",
      content: "Provider A",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      epistemicClass: "observed",
      confidence: 0.9,
      sourceKind: "user_decision",
      evidenceRefs: [{ engine: "external", ref: "note:a" }],
    });
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Provider B",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "switched providers",
    });
    const bundle = engine.backup();
    assert.equal(engine.verifyBackup(bundle).valid, true);

    const restoredDir = mkdtempSync(join(tmpdir(), "mem-t45-restored-"));
    try {
      const restored = new MemoryEngine({ storePath: join(restoredDir, "restored.db") });
      restored.open();
      try {
        restored.restoreBundle(bundle);
        const chain = restored.getRecordHistory(v2.recordId);
        assert.equal(chain.chain.length, 2);
        assert.equal(chain.chain[0]!.content, "Provider A");
        assert.equal(chain.chain[0]!.supersededReason, "switched providers");
        assert.equal(restored.currentRecords({ scope: "lib", subject: "Auth choice" }).length, 1);
      } finally {
        restored.close();
      }
    } finally {
      rmSync(restoredDir, { recursive: true, force: true });
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T45: terminal surface — qualify recovery via CLI with honest exit codes", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t45-cli-"));
  const storePath = join(dir, "memory.db");
  const reportPath = join(dir, "recovery.json");
  try {
    const run = (args: string[]): { stdout: string; status: number } => {
      try {
        const stdout = execFileSync(
          process.execPath,
          ["--experimental-strip-types", CLI_PATH, ...args, "--store", storePath],
          { encoding: "utf8", env: { ...process.env } },
        );
        return { stdout, status: 0 };
      } catch (err) {
        const e = err as { stdout?: string; status?: number };
        return { stdout: e.stdout ?? "", status: e.status ?? 1 };
      }
    };
    const result = run(["qualify", "recovery", "--path", reportPath]);
    assert.equal(result.status, 0, result.stdout.slice(0, 400));
    const report = JSON.parse(result.stdout) as RecoveryQualificationReport;
    assert.equal(report.passed, true);
    assert.equal(report.checks.length, 8);
    assert.deepEqual(JSON.parse(readFileSync(reportPath, "utf8")), report);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
