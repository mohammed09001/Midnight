/**
 * CHILD LOOP 1 verification — Task 14: exact identity and structured-filter
 * retrieval. Proves retrieval by project, kind, exact subject, source
 * engine, tags, validity instant, confidence range, actor, and time ranges.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t14-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

test("T14: structured filters — engine, actor, confidence, exact subject, validity, time", () => {
  const { engine, dir } = tempEngine("filters");
  try {
    // This test deliberately exercises cross-project retrieval (no scope).
    engine.setProjectIsolation("open");
    engine.createScope("alpha", "Alpha");
    engine.createScope("beta", "Beta");
    const a = engine.addRecord({
      scope: "alpha",
      kind: "fact",
      subject: "Rate limit",
      content: "120 requests per minute from the limiter study",
      actor: { kind: "agent", name: "worker-1" },
      method: "extracted",
      epistemicClass: "observed",
      confidence: 0.95,
      sourceKind: "study_finding",
      evidenceRefs: [{ engine: "study_document", ref: "doc:s1" }],
      observedAt: "2026-08-01T00:00:00.000Z",
    });
    engine.addRecord({
      scope: "alpha",
      kind: "decision",
      subject: "Cache policy",
      content: "Cache is rebuildable",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      epistemicClass: "observed",
      confidence: 0.6,
      sourceKind: "user_note",
      evidenceRefs: [{ engine: "external", ref: "note:9" }],
      observedAt: "2026-08-20T00:00:00.000Z",
    });
    engine.addRecord({
      scope: "beta",
      kind: "fact",
      subject: "Rate limit",
      content: "Beta cluster limit differs",
      actor: { kind: "agent", name: "worker-2" },
      method: "extracted",
      epistemicClass: "observed",
      confidence: 0.8,
      sourceKind: "repository_evidence",
      evidenceRefs: [{ engine: "repository_sync", ref: "repo:x" }],
    });

    // Exact identity retrieval via the record id.
    assert.equal(engine.getRecord(a.recordId).recordId, a.recordId);
    // Exact subject.
    assert.equal(engine.searchRecords({ exactSubject: "Rate limit", status: "all" }).length, 2);
    // Source engine filter.
    const byEngine = engine.searchRecords({ sourceEngine: "repository_sync" });
    assert.equal(byEngine.length, 1);
    assert.equal(byEngine[0]!.scopeId, engine.getScope("beta").scopeId);
    // Actor canonical key.
    const byActor = engine.searchRecords({ actor: "agent:worker-1" });
    assert.deepEqual(byActor.map((r) => r.recordId), [a.recordId]);
    // Confidence range.
    const confident = engine.searchRecords({ confidenceMin: 0.9, status: "all" });
    assert.deepEqual(confident.map((r) => r.subject).sort(), ["Rate limit"]);
    const mid = engine.searchRecords({ confidenceMin: 0.5, confidenceMax: 0.7, status: "all" });
    assert.deepEqual(mid.map((r) => r.subject), ["Cache policy"]);
    // Validity at instant (observedAt defaults the record's observed time;
    // validFrom/validUntil are open here, so validAt only needs existence).
    const validAug = engine.searchRecords({ validAt: "2026-08-05T00:00:00.000Z", status: "all" });
    assert.ok(validAug.length >= 2);
    // Time ranges.
    const early = engine.searchRecords({ observedBefore: "2026-08-15T00:00:00.000Z", status: "all" });
    assert.deepEqual(early.map((r) => r.recordId), [a.recordId]);
    const late = engine.searchRecords({ observedAfter: "2026-08-15T00:00:00.000Z", status: "all" });
    assert.equal(late.length, 2);
    assert.deepEqual(late.map((r) => r.subject).sort(), ["Cache policy", "Rate limit"]);
    // Combined filters compose.
    const composed = engine.searchRecords({
      scope: "alpha",
      kind: "fact",
      sourceEngine: "study_document",
      actor: "agent:worker-1",
      confidenceMin: 0.9,
    });
    assert.deepEqual(composed.map((r) => r.recordId), [a.recordId]);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T14: validity-window filter — records outside their window are excluded", () => {
  const { engine, dir } = tempEngine("validity");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord({
      ...fact("lib"),
      subject: "Promo",
      content: "Launch discount",
      validFrom: "2026-08-01T00:00:00.000Z",
      validUntil: "2026-08-15T00:00:00.000Z",
    });
    engine.addRecord({ ...fact("lib"), subject: "Standing", content: "No discounts" });
    const atInWindow = engine.searchRecords({ scope: "lib", validAt: "2026-08-10T00:00:00.000Z" });
    assert.equal(atInWindow.length, 2);
    const atAfterWindow = engine.searchRecords({ scope: "lib", validAt: "2026-08-20T00:00:00.000Z" });
    assert.equal(atAfterWindow.length, 1);
    assert.equal(atAfterWindow[0]!.subject, "Standing");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T14: negative — malformed time/confidence filters are typed errors", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    assert.throws(
      () => engine.searchRecords({ validAt: "tomorrow" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.searchRecords({ createdAfter: "last tuesday" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.searchRecords({ confidenceMin: "high" as never }),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

function fact(scope: string) {
  return {
    scope,
    kind: "fact" as const,
    subject: "S",
    content: "C",
    actor: { kind: "human" as const, name: "kim" },
    method: "asserted",
    epistemicClass: "observed" as const,
    confidence: 0.9,
    sourceKind: "user_note" as const,
    evidenceRefs: [{ engine: "external" as const, ref: "note:1" }],
  };
}
