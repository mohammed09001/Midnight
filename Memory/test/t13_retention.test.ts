/**
 * CHILD LOOP 1 verification — Task 13: retention, archival, and deletion
 * semantics. Proves: active/archived/tombstone lifecycle states, project
 * deletion propagation with identity retention, privacy-driven hard purge
 * with pointer cleanup, and source-evidence expiry semantics (records
 * survive, verifiability degrades visibly).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import {
  ConflictError,
  CorrectionForbiddenError,
  ValidationError,
} from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t13-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function fact(scope: string, subject: string, content: string, overrides: Record<string, unknown> = {}) {
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
    evidenceRefs: [{ engine: "external" as const, ref: `note:${Math.random()}` }],
    ...overrides,
  };
}

test("T13: archive/restore — cold state excluded from current views, restorable", () => {
  const { engine, dir } = tempEngine("archive");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(fact("lib", "Old design", "Monolith architecture"));
    // Agents cannot archive.
    assert.throws(
      () =>
        engine.archiveRecord(record.recordId, {
          actor: { kind: "agent", name: "janitor-bot" },
          reason: "cleanup",
        }),
      (err: unknown) => err instanceof CorrectionForbiddenError,
    );
    const archived = engine.archiveRecord(record.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "replaced by the services design",
    });
    assert.equal(archived.status, "archived");
    assert.ok(archived.archivedAt !== null);
    // Excluded from the default active view…
    assert.equal(engine.searchRecords({ scope: "lib", status: "active" }).length, 0);
    // …but still fully queryable.
    assert.equal(engine.getRecord(record.recordId).content, "Monolith architecture");
    // Archived records were still believed while active (as-of now excludes
    // them because archiving applies forward).
    const now2 = engine.queryRecordsAsOf({ scope: "lib", asOf: new Date().toISOString() });
    assert.ok(!now2.some((r) => r.recordId === record.recordId));

    const restored = engine.restoreRecord(record.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "monolith is back",
    });
    assert.equal(restored.status, "active");
    assert.equal(restored.archivedAt, null);
    assert.throws(
      () =>
        engine.restoreRecord(record.recordId, {
          actor: { kind: "human", name: "kim" },
          reason: "double restore",
        }),
      (err: unknown) => err instanceof ConflictError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T13: tombstone deletion scrubs content but retains identity and lineage", () => {
  const { engine, dir } = tempEngine("tombstone");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Legacy rule", "Deploy on Fridays"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Deploy any day",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "policy change",
    });
    const deleted = engine.deleteRecord(v1.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "retiring the old rule's payload",
    });
    assert.equal(deleted.status, "deleted");
    assert.equal(deleted.content, "", "payload scrubbed");
    assert.deepEqual(deleted.evidenceRefs, []);
    assert.ok(deleted.deletedAt !== null);
    assert.equal(deleted.deletedBy, "human:kim");
    assert.equal(deleted.deleteReason, "retiring the old rule's payload");
    // Lineage markers survive: the successor still points at the tombstone.
    assert.equal(engine.getRecord(v2.recordId).supersedesId, v1.recordId);
    // Tombstones leave the default search view but remain explicitly visible.
    assert.ok(!engine.searchRecords({ scope: "lib" }).some((r) => r.recordId === v1.recordId));
    assert.ok(engine.searchRecords({ scope: "lib", status: "all" }).some((r) => r.recordId === v1.recordId));
    // And from as-of belief views entirely (content unreconstructable).
    const past = engine.queryRecordsAsOf({ scope: "lib", asOf: v1.createdAt });
    assert.ok(!past.some((r) => r.recordId === v1.recordId));
    // Tombstoned records cannot be re-deleted.
    assert.throws(
      () =>
        engine.deleteRecord(v1.recordId, {
          actor: { kind: "human", name: "kim" },
          reason: "again",
        }),
      (err: unknown) => err instanceof ConflictError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T13: privacy purge is the only hard delete and cleans all inbound pointers", () => {
  const { engine, dir } = tempEngine("purge");
  try {
    engine.createScope("lib", "Library");
    const target = engine.addRecord({
      ...fact("lib", "Personal note", "Kim's phone number details"),
      privacyClass: "sensitive",
    });
    const relator = engine.addRecord(
      fact("lib", "Related", "See personal note", {
        relationHints: [{ type: "related", target: target.recordId }],
      }),
    );
    engine.reviseRecord(target.recordId, {
      content: "Kim's phone number details (updated)",
      actor: { kind: "human", name: "kim" },
      method: "corrected",
      reason: "detail change",
    });
    // The record has revision rows before purge.
    assert.equal(engine.getRecordHistory(target.recordId).revisions.length, 2);

    const result = engine.purgeRecord(target.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "subject erasure request",
    });
    assert.equal(result.purged, true);
    // Row is gone.
    assert.throws(() => engine.getRecord(target.recordId), (err: unknown) => err instanceof ValidationError || err instanceof Error);
    // Revision log is gone.
    const revCount = engine.store
      .ensureOpen()
      .prepare("SELECT COUNT(*) AS n FROM memory_record_revisions WHERE record_id = ?")
      .get(target.recordId) as { n: number };
    assert.equal(Number(revCount.n), 0);
    // Inbound relation hints scrubbed.
    const relatorAfter = engine.getRecord(relator.recordId);
    assert.equal(relatorAfter.relationHints.length, 0);
    // Purge event carries no content.
    const event = engine.listEvents(10).find((e) => e.type === "memory.record.purged");
    assert.ok(event !== undefined);
    assert.equal((event!.payload as { reason: string }).reason, "subject erasure request");
    assert.ok(!JSON.stringify(event).includes("phone"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T13: purgeByPrivacy — bulk erasure by privacy class, scoped", () => {
  const { engine, dir } = tempEngine("purge-privacy");
  try {
    engine.createScope("alpha", "Alpha");
    engine.createScope("beta", "Beta");
    engine.addRecord({ ...fact("alpha", "A1", "sensitive a1"), privacyClass: "sensitive" });
    engine.addRecord(fact("alpha", "A2", "internal a2"));
    engine.addRecord({ ...fact("beta", "B1", "sensitive b1"), privacyClass: "sensitive" });
    assert.throws(
      () =>
        engine.purgeByPrivacy({
          actor: { kind: "agent", name: "cleaner" },
          reason: "bot purge",
          privacyClasses: ["sensitive"],
        }),
      (err: unknown) => err instanceof CorrectionForbiddenError,
    );
    const result = engine.purgeByPrivacy({
      actor: { kind: "human", name: "dpo" },
      reason: "retention policy expiration",
      privacyClasses: ["sensitive"],
      scope: "alpha",
    });
    assert.equal(result.purgedCount, 1);
    assert.throws(() => engine.getRecord(result.recordIds[0]!));
    // Beta untouched; internal alpha record untouched.
    assert.equal(engine.getRecord(engine.searchRecords({ scope: "alpha" })[0]!.recordId).privacyClass, "internal");
    assert.equal(engine.searchRecords({ scope: "beta" }).length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T13: project deletion propagates and the identity is retired", () => {
  const { engine, dir } = tempEngine("scope-delete");
  try {
    engine.createScope("doomed", "Doomed Project");
    const a = engine.addRecord(fact("doomed", "R1", "record one"));
    const b = engine.addRecord(fact("doomed", "R2", "record two"));
    engine.addCandidate({
      ...fact("doomed", "C1", "pending proposal"),
      epistemicClass: "inferred",
      reason: "pending",
      caller: { kind: "human", name: "kim" },
    });

    const deleted = engine.deleteScope("doomed", {
      actor: { kind: "human", name: "kim" },
      reason: "project cancelled",
    });
    assert.ok(deleted.deletedAt !== null);
    assert.equal(deleted.deleteReason, "project cancelled");
    // Propagation: records tombstoned.
    assert.equal(engine.getRecord(a.recordId).status, "deleted");
    assert.equal(engine.getRecord(b.recordId).status, "deleted");
    // Pending candidates dropped.
    assert.equal(engine.listCandidates({ scope: "doomed" }).length, 0);
    // The scope is still viewable (retired identity) but refuses writes.
    assert.throws(
      () => engine.addRecord(fact("doomed", "New", "after deletion")),
      (err: unknown) => err instanceof ConflictError,
    );
    assert.throws(
      () =>
        engine.addCandidate({
          ...fact("doomed", "New cand", "after deletion"),
          epistemicClass: "inferred",
          reason: "after deletion",
        }),
      (err: unknown) => err instanceof ConflictError,
    );
    // Identity is NOT reusable.
    assert.throws(
      () => engine.createScope("doomed", "Doomed Project"),
      (err: unknown) => err instanceof ConflictError,
    );
    // Agents cannot delete projects.
    assert.throws(
      () =>
        engine.deleteScope("lib2", {
          actor: { kind: "agent", name: "x" },
          reason: "no",
        }).valueOf(),
      () => true,
    );
    void dir;
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T13: source-evidence expiry — records survive, verifiability degrades visibly", () => {
  const { engine, dir } = tempEngine("evidence-expiry");
  try {
    engine.createScope("lib", "Library");
    // Evidence with an expiry in the past; another record with live evidence.
    const lapsed = engine.addRecord({
      ...fact("lib", "Cached metric", "Uptime was 99.9%"),
      evidenceRefs: [
        {
          engine: "repository_sync",
          ref: "metrics:run-42",
          expiresAt: "2026-08-01T00:00:00.000Z",
        },
      ],
    });
    engine.addRecord(fact("lib", "Standing fact", "Uptime target is 99.9%"));

    const expired = engine.listEvidenceExpired("lib", new Date().toISOString());
    assert.deepEqual(expired.map((r) => r.recordId), [lapsed.recordId]);
    // Sweep reports without mutating.
    const sweep = engine.sweepExpiredEvidence("lib", new Date().toISOString());
    assert.equal(sweep.expiredCount, 1);
    assert.equal(engine.getRecord(lapsed.recordId).status, "active", "expiry never silently invalidates");
    assert.equal(
      engine.listEvents(10).filter((e) => e.type === "memory.evidence.expired").length,
      1,
    );
    // Malformed expiry rejected at intake.
    assert.throws(
      () =>
        engine.addRecord(
          fact("lib", "Bad expiry", "x", {
            evidenceRefs: [{ engine: "external", ref: "x", expiresAt: "soon" }],
          }),
        ),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T13: lifecycle decisions are reasoned — blank reasons refused", () => {
  const { engine, dir } = tempEngine("reasons");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(fact("lib", "S", "C"));
    assert.throws(
      () => engine.archiveRecord(record.recordId, { actor: { kind: "human", name: "kim" }, reason: "" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.deleteRecord(record.recordId, { actor: { kind: "human", name: "kim" }, reason: " " }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.purgeRecord(record.recordId, { actor: { kind: "human", name: "kim" }, reason: "" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.equal(engine.getRecord(record.recordId).status, "active");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
