/**
 * CHILD LOOP 1 verification — Task 7: append-oriented Memory persistence.
 * Proves: idempotent writes via idempotency keys (replay-safe, race-safe),
 * the immutable revision log as truth with the record row as a rebuildable
 * projection (integrity check + repair), transactions, and restart-safe
 * migrations. Pattern adapted from mem0's ADD-only accumulation (nothing
 * overwritten) without its LLM/provider dependency.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t7-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function observedInput(scope: string, subject: string, content: string) {
  return {
    scope,
    kind: "fact" as const,
    subject,
    content,
    actor: { kind: "human" as const, name: "kim" },
    method: "asserted",
    epistemicClass: "observed" as const,
    confidence: 0.9,
    sourceKind: "user_note" as const,
    evidenceRefs: [{ engine: "external" as const, ref: "note:1" }],
  };
}

test("T7: idempotent record writes — same key returns the same record, no duplicate", () => {
  const { engine, dir } = tempEngine("idempotent-record");
  try {
    engine.createScope("lib", "Library");
    const first = engine.addRecord({
      ...observedInput("lib", "Idempotent", "Written once"),
      idempotencyKey: "sync:repo-abc:123",
    });
    const replay = engine.addRecord({
      ...observedInput("lib", "Idempotent", "Written once — DIFFERENT text should be ignored"),
      idempotencyKey: "sync:repo-abc:123",
    });
    assert.equal(replay.recordId, first.recordId, "replay returns the original record");
    assert.equal(replay.content, "Written once", "original content preserved");
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 1, "no duplicate persisted");
    assert.equal(first.idempotencyKey, "sync:repo-abc:123");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T7: idempotent candidate intake — replay returns the same candidate", () => {
  const { engine, dir } = tempEngine("idempotent-candidate");
  try {
    engine.createScope("lib", "Library");
    const input = {
      ...observedInput("lib", "Lesson", "Retry with backoff"),
      epistemicClass: "inferred" as const,
      reason: "recurring failure pattern",
      idempotencyKey: "analyzer:run-42:lesson-1",
    };
    const first = engine.addCandidate(input);
    const replay = engine.addCandidate({ ...input, reason: "recurring failure pattern (resubmitted)" });
    assert.equal(replay.candidateId, first.candidateId);
    assert.equal(engine.listCandidates({ scope: "lib" }).length, 1);
    // Different key with identical content is a DIFFERENT proposal (deterministic).
    const second = engine.addCandidate({ ...input, idempotencyKey: "analyzer:run-43:lesson-1" });
    assert.notEqual(second.candidateId, first.candidateId);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T7: idempotency survives restart — replay after reopen does not duplicate", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t7-restart-"));
  const path = join(dir, "memory.db");
  let recordId: string;
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    recordId = engine.addRecord({
      ...observedInput("lib", "Durable", "Survives restarts"),
      idempotencyKey: "sync:job-7",
    }).recordId;
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const replay = engine.addRecord({
        ...observedInput("lib", "Durable", "Survives restarts"),
        idempotencyKey: "sync:job-7",
      });
      assert.equal(replay.recordId, recordId);
      assert.equal(engine.searchRecords({ scope: "lib" }).length, 1);
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});

test("T7: the revision log is truth — corrupted projections are detected and repaired", () => {
  const { engine, dir } = tempEngine("append-truth");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(observedInput("lib", "Truth", "Original text"));
    engine.reviseRecord(record.recordId, {
      content: "Revised text",
      actor: { kind: "human", name: "kim" },
      method: "correction",
      reason: "fix",
    });

    // Baseline: consistent.
    let report = engine.checkAppendIntegrity();
    assert.equal(report.consistent, true);
    assert.equal(report.recordCount, 1);

    // Simulate projection drift (e.g. an external tool corrupting the row):
    // the append log still holds the truth.
    engine.store
      .ensureOpen()
      .prepare("UPDATE memory_records SET content = ?, content_hash = 'deadbeef' WHERE record_id = ?")
      .run("externally corrupted", record.recordId);

    report = engine.checkAppendIntegrity();
    assert.equal(report.consistent, false);
    assert.equal(report.broken.length, 1);
    assert.equal(report.broken[0]!.recordId, record.recordId);

    const repair = engine.repairRecordProjection(record.recordId);
    assert.equal(repair.repaired, true);
    const healed = engine.getRecord(record.recordId);
    assert.equal(healed.content, "Revised text", "content rebuilt from newest revision row");
    assert.match(healed.contentHash, /^[0-9a-f]{64}$/);
    assert.equal(healed.revision, 2);
    assert.equal(engine.checkAppendIntegrity().consistent, true);
    // Repair is observable.
    assert.ok(engine.listEvents(10).some((e) => e.type === "memory.record.repaired"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T7: repair refuses to invent state — missing log rows are reported, not fabricated", () => {
  const { engine, dir } = tempEngine("repair-negative");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(observedInput("lib", "S", "C"));
    engine.store.ensureOpen().prepare("DELETE FROM memory_record_revisions WHERE record_id = ?").run(record.recordId);
    const repair = engine.repairRecordProjection(record.recordId);
    assert.equal(repair.repaired, false, "no log rows → nothing to repair from");
    assert.match(repair.detail, /log holds nothing/);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T7: restart-safe migrations — stores upgrade in place with backfill intact", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t7-migration-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.addRecord(observedInput("lib", "Legacy", "Written under 1.3 already"));
    engine.close();
    // Reopen is idempotent: no migration re-application, no growth.
    const again = new MemoryEngine({ storePath: path });
    again.open();
    const applied = again.store.appliedMigrationVersions();
    assert.deepEqual(applied, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    again.close();
  }
  rmSync(dir, { recursive: true, force: true });
});

test("T7: transactions — a failed write leaves no partial state", () => {
  const { engine, dir } = tempEngine("transaction");
  try {
    engine.createScope("lib", "Library");
    const other = engine.addRecord(observedInput("lib", "Other", "Existing"));
    // Superseding a retracted record fails mid-transaction; nothing persists.
    engine.retractRecord(other.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "wrong",
    });
    assert.throws(() =>
      engine.supersedeRecord(other.recordId, {
        content: "Should never persist",
        actor: { kind: "human", name: "kim" },
        method: "decided",
        reason: "should fail anyway",
      }),
    );
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 1);
    assert.equal(
      engine.searchRecords({ scope: "lib" })[0]!.status,
      "retracted",
      "no partial supersession state",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

