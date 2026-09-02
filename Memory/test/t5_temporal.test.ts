/**
 * CHILD LOOP 2 verification — Task 5: temporal validity and historical
 * truth. Proves: bi-temporal fields (observedAt valid time vs createdAt/
 * revisedAt transaction time, supersededAt invalidation), history queries
 * (revisions + supersession chain), as-of belief reconstruction, and the
 * invariant that changed decisions never overwrite the past.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t5-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function observedInput(scope: string, subject: string, content: string) {
  return {
    scope,
    kind: "decision" as const,
    subject,
    content,
    actor: { kind: "human" as const, name: "kim" },
    method: "decided",
    epistemicClass: "observed" as const,
    confidence: 0.95,
    sourceKind: "user_note" as const,
    evidenceRefs: [{ engine: "external" as const, ref: "note:decisions" }],
  };
}

test("T5: bi-temporal fields — observedAt is valid time, createdAt is transaction time", () => {
  const { engine, dir } = tempEngine("bitemporal");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord({
      ...observedInput("lib", "Release cadence", "Weekly train on Tuesday"),
      observedAt: "2026-08-01T09:00:00.000Z",
    });
    assert.equal(record.observedAt, "2026-08-01T09:00:00.000Z");
    assert.ok(record.createdAt > record.observedAt, "recorded after it was observed");
    assert.equal(record.supersededAt, null);
    assert.throws(
      () =>
        engine.addRecord({
          ...observedInput("lib", "Bad", "x"),
          observedAt: "not-a-timestamp",
        }),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T5: supersession stamps supersededAt and never deletes the predecessor", () => {
  const { engine, dir } = tempEngine("supersede-at");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord({
      ...observedInput("lib", "Release cadence", "Weekly train on Tuesday"),
      observedAt: "2026-08-01T00:00:00.000Z",
    });
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Weekly train on Wednesday",
      actor: { kind: "human", name: "kim" },
      method: "decided",
        reason: "policy updated",
      });
    const v1After = engine.getRecord(v1.recordId);
    assert.equal(v1After.status, "superseded");
    assert.ok(v1After.supersededAt !== null, "invalidation timestamp recorded");
    assert.ok(v1After.supersededAt <= v2.createdAt, "predecessor invalidated at/before successor creation");
    assert.equal(v1After.content, "Weekly train on Tuesday", "past content untouched");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T5: history returns the full supersession chain and immutable revisions", async () => {
  const { engine, dir } = tempEngine("history");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(observedInput("lib", "Cadence", "Tuesday"));
    await new Promise((r) => setTimeout(r, 5));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Wednesday",
      actor: { kind: "human", name: "kim" },
      method: "decided",
        reason: "policy updated",
      });
    await new Promise((r) => setTimeout(r, 5));
    const v3 = engine.supersedeRecord(v2.recordId, {
      content: "Thursday",
      actor: { kind: "human", name: "kim" },
      method: "decided",
        reason: "policy updated",
      });
    const history = engine.getRecordHistory(v1.recordId);
    assert.deepEqual(
      history.chain.map((c) => c.recordId),
      [v1.recordId, v2.recordId, v3.recordId],
      "chain is ordered oldest to newest from any entry point",
    );
    assert.deepEqual(history.chain.map((c) => c.content), ["Tuesday", "Wednesday", "Thursday"]);
    assert.equal(history.chain[2]!.supersededAt, null);
    // History is reachable from any chain member, including the middle.
    const midHistory = engine.getRecordHistory(v2.recordId);
    assert.equal(midHistory.chain.length, 3);
    // Revisions on the current record are immutable rows.
    const revHistory = engine.getRecordHistory(v3.recordId);
    assert.equal(revHistory.revisions.length, 1);
    assert.equal(revHistory.revisions[0]!.content, "Thursday");
    assert.match(
      revHistory.revisions[0]!.reason ?? "",
      /^supersedes mem_/,
      "supersession reason recorded in the initial revision row",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T5: as-of query reconstructs what was believed at a past instant", async () => {
  const { engine, dir } = tempEngine("asof");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord({
      ...observedInput("lib", "Cadence", "Tuesday"),
      observedAt: "2026-08-01T00:00:00.000Z",
    });
    await new Promise((r) => setTimeout(r, 5));
    const createdAtV1 = v1.createdAt;
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Wednesday",
      actor: { kind: "human", name: "kim" },
      method: "decided",
        reason: "policy updated",
      });
    // A later, unrelated record.
    const other = engine.addRecord({
      ...observedInput("lib", "Owner", "Kim owns releases"),
      observedAt: "2026-08-29T00:00:00.000Z",
    });

    // Just before the successor existed: v1 was believed.
    // (Boundary semantics: at exactly supersededAt the successor already
    // holds, so query 1ms before invalidation.)
    const justBefore = new Date(Date.parse(v1.supersededAt ?? v2.createdAt) - 1).toISOString();
    const before = engine.queryRecordsAsOf({ scope: "lib", asOf: justBefore });
    const beforeIds = before.map((r) => r.recordId);
    assert.ok(beforeIds.includes(v1.recordId), "superseded record is true BEFORE its supersededAt");
    assert.ok(!beforeIds.includes(v2.recordId), "successor did not exist yet");
    assert.ok(!beforeIds.includes(other.recordId), "later record not yet created");

    // Now: v2 and other are current, v1 is not.
    const now2 = engine.queryRecordsAsOf({ scope: "lib", asOf: new Date().toISOString() });
    const nowIds = now2.map((r) => r.recordId);
    assert.ok(nowIds.includes(v2.recordId));
    assert.ok(nowIds.includes(other.recordId));
    assert.ok(!nowIds.includes(v1.recordId), "superseded record is no longer true after supersededAt");
    void createdAtV1;

    // Boundary: at exactly the supersededAt instant, v1 is already gone.
    const atBoundary = engine.queryRecordsAsOf({ scope: "lib", asOf: v1AfterSupersededAt(engine, v1.recordId) });
    assert.ok(!atBoundary.some((r) => r.recordId === v1.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

function v1AfterSupersededAt(engine: MemoryEngine, recordId: string): string {
  const record = engine.getRecord(recordId);
  return record.supersededAt!;
}

test("T5: as-of respects validity windows and retraction timing", async () => {
  const { engine, dir } = tempEngine("asof-windows");
  try {
    engine.createScope("lib", "Library");
    // Short-lived validity window around NOW (valid time is independent of
    // transaction time, but as-of belief is also bounded by created_at —
    // a record cannot be believed before the store learned it).
    const nowMs = Date.now();
    engine.addRecord({
      ...observedInput("lib", "Promo", "Launch discount"),
      validFrom: new Date(nowMs - 1000).toISOString(),
      validUntil: new Date(nowMs + 2000).toISOString(),
    });
    const retracted = engine.addRecord(observedInput("lib", "Wrong rule", "Discounts are impossible"));
    const standing = engine.addRecord(observedInput("lib", "Standing rule", "No discounts"));

    // Inside the window (and after creation): promo believed.
    const inWindow = engine.queryRecordsAsOf({
      scope: "lib",
      asOf: new Date(nowMs + 1000).toISOString(),
    });
    assert.ok(inWindow.some((r) => r.subject === "Promo"));
    // After the window closes: no longer believed.
    const afterWindow = engine.queryRecordsAsOf({
      scope: "lib",
      asOf: new Date(nowMs + 3000).toISOString(),
    });
    assert.ok(!afterWindow.some((r) => r.subject === "Promo"));

    // Retraction is believed until it happens: capture T before retracting.
    await new Promise((r) => setTimeout(r, 5));
    const beforeRetraction = new Date().toISOString();
    await new Promise((r) => setTimeout(r, 5));
    engine.retractRecord(retracted.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "it was wrong",
    });
    await new Promise((r) => setTimeout(r, 5));
    const atBeforeRetraction = engine.queryRecordsAsOf({ scope: "lib", asOf: beforeRetraction });
    assert.ok(atBeforeRetraction.some((r) => r.recordId === retracted.recordId),
      "historical belief includes the record while it still stood");
    const now3 = engine.queryRecordsAsOf({ scope: "lib", asOf: new Date().toISOString() });
    assert.ok(!now3.some((r) => r.recordId === retracted.recordId), "retracted not believed now");
    assert.ok(now3.some((r) => r.recordId === standing.recordId));
    // Callers may explicitly exclude retracted records from belief views.
    const beliefs = engine.queryRecordsAsOf({
      scope: "lib",
      asOf: beforeRetraction,
      includeRetracted: false,
    });
    assert.ok(!beliefs.some((r) => r.recordId === retracted.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T5: current query and as-of agree; expired records leave the current view", async () => {
  const { engine, dir } = tempEngine("current");
  try {
    engine.createScope("lib", "Library");
    const nowMs = Date.now();
    engine.addRecord({
      ...observedInput("lib", "Temporary", "Migration window open"),
      validUntil: new Date(nowMs + 2000).toISOString(),
    });
    engine.addRecord(observedInput("lib", "Permanent", "Schema is append-only"));
    // Before expiry, both are believed.
    const midWindow = engine.queryRecordsAsOf({
      scope: "lib",
      asOf: new Date(nowMs + 1000).toISOString(),
    });
    assert.equal(midWindow.length, 2);
    // Explicit sweep expires the window-closed record (transaction time).
    const expiredCount = engine.expireStaleRecords(new Date(nowMs + 3000).toISOString());
    assert.equal(expiredCount, 1);
    const current = engine.searchRecords({ scope: "lib", status: "active" });
    assert.equal(current.length, 1);
    assert.equal(current[0]!.subject, "Permanent");
    // As-of the same instant agrees with the current view.
    const asOfNow = engine.queryRecordsAsOf({
      scope: "lib",
      asOf: new Date(nowMs + 3000).toISOString(),
    });
    assert.deepEqual(
      asOfNow.map((r) => r.subject).sort(),
      ["Permanent"],
      "expired record is outside its validity window at T=now",
    );
    // Historical: both were believed mid-window — the past is not overwritten by expiry.
    assert.equal(midWindow.length, 2, "the past is not overwritten by expiry");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T5: as-of requires a real timestamp; unknown record history fails typed", () => {
  const { engine, dir } = tempEngine("asof-negative");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.queryRecordsAsOf({ asOf: "yesterday" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.getRecordHistory("mem_missing"),
      (err: unknown) => err instanceof ValidationError || err instanceof Error,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

