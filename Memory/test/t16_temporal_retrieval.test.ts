/**
 * CHILD LOOP 3 verification — Task 16: temporal retrieval. Proves the
 * three canonical temporal questions with explicit validity semantics:
 * "what is current" (validity-aware active view), "what was true at date X"
 * (as-of), and "how did the decision change across time" (timeline).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t16-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function decision(scope: string, subject: string, content: string, overrides: Record<string, unknown> = {}) {
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
    ...overrides,
  };
}

test("T16: current — the validity-aware answer to 'what is the current decision'", async () => {
  const { engine, dir } = tempEngine("current");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(decision("lib", "Release cadence", "Tuesday"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Wednesday",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "schedule change",
    });
    // A windowed record that is NOT yet current.
    const future = engine.addRecord(
      decision("lib", "Freeze policy", "Freeze during release", {
        validFrom: "2999-01-01T00:00:00.000Z",
      }),
    );
    const current = engine.currentRecords({ scope: "lib" });
    const ids = current.map((r) => r.recordId);
    assert.ok(ids.includes(v2.recordId), "the successor is current");
    assert.ok(!ids.includes(v1.recordId), "the superseded predecessor is not");
    assert.ok(!ids.includes(future.recordId), "not-yet-valid records are not current");

    // Subject-scoped current answer.
    const scoped = engine.currentRecords({ scope: "lib", subject: "Release cadence" });
    assert.deepEqual(scoped.map((r) => r.recordId), [v2.recordId]);
    assert.equal(scoped[0]!.content, "Wednesday");

    // A retracted decision leaves the current view.
    await new Promise((r) => setTimeout(r, 3));
    engine.retractRecord(v2.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "program paused",
    });
    assert.equal(engine.currentRecords({ scope: "lib", subject: "Release cadence" }).length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T16: what-was-true-at-X — as-of reconstruction with explicit semantics", async () => {
  const { engine, dir } = tempEngine("as-of");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(
      decision("lib", "Backup time", "02:00", { observedAt: "2026-08-01T00:00:00.000Z" }),
    );
    await new Promise((r) => setTimeout(r, 5));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "03:00",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "off-peak move",
    });
    const boundary = new Date(Date.parse(engine.getRecord(v1.recordId).supersededAt ?? v2.createdAt) - 1).toISOString();
    const past = engine.queryRecordsAsOf({ scope: "lib", asOf: boundary, includeRetracted: false });
    const pastBackup = past.find((r) => r.subject === "Backup time");
    assert.ok(pastBackup !== undefined);
    assert.equal(pastBackup!.content, "02:00", "at X the old value was true");
    const now2 = engine.queryRecordsAsOf({ scope: "lib", asOf: new Date().toISOString() });
    assert.equal(now2.find((r) => r.subject === "Backup time")!.content, "03:00");
    assert.throws(
      () => engine.queryRecordsAsOf({ scope: "lib", asOf: "never" }),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T16: timeline — how the decision changed across time, with retirement reasons", async () => {
  const { engine, dir } = tempEngine("timeline");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(
      decision("lib", "Deploy window", "Friday evening"),
    );
    await new Promise((r) => setTimeout(r, 3));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Tuesday morning",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "avoid weekend deploys",
    });
    await new Promise((r) => setTimeout(r, 3));
    // A correction (same identity, new revision) also shows up.
    engine.reviseRecord(v2.recordId, {
      content: "Tuesday 09:00",
      actor: { kind: "engine", name: "project_projection" },
      method: "corrected",
      reason: "exact time confirmed",
    });
    // An unrelated subject does not appear.
    engine.addRecord(decision("lib", "Other", "unrelated"));

    const timeline = engine.decisionTimeline("lib", "Deploy window");
    assert.equal(timeline.length, 2);
    assert.deepEqual(
      timeline.map((t) => t.content),
      ["Friday evening", "Tuesday 09:00"],
    );
    // The change is explicit: successor links, invalidation stamp + reason.
    assert.equal(timeline[0]!.supersededReason, "avoid weekend deploys");
    assert.equal(timeline[0]!.supersededAt !== null, true);
    assert.equal(timeline[1]!.recordId, v2.recordId);
    assert.equal(timeline[1]!.supersedesId, v1.recordId);
    // Timeline excludes tombstones but includes archived history markers.
    engine.archiveRecord(v2.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "program ended",
    });
    assert.equal(engine.decisionTimeline("lib", "Deploy window").length, 2);
    // Subject required.
    assert.throws(
      () => engine.decisionTimeline("lib", "  "),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T16: integration — current, as-of, and timeline agree on one dataset", () => {
  const { engine, dir } = tempEngine("integration");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(decision("lib", "Region", "eu-west-1"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "eu-central-1",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "latency",
    });
    // Current view: only the successor.
    const current = engine.currentRecords({ scope: "lib", subject: "Region" });
    assert.deepEqual(current.map((r) => r.recordId), [v2.recordId]);
    // Timeline: both, oldest first.
    const timeline = engine.decisionTimeline("lib", "Region");
    assert.deepEqual(timeline.map((t) => t.recordId), [v1.recordId, v2.recordId]);
    // As-of just before invalidation: only the predecessor.
    const justBefore = new Date(Date.parse(v1.supersededAt ?? v2.createdAt) - 1).toISOString();
    const past = engine.queryRecordsAsOf({ scope: "lib", asOf: justBefore });
    assert.deepEqual(
      past.filter((r) => r.subject === "Region").map((r) => r.recordId),
      [v1.recordId],
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
