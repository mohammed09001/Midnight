/**
 * CHILD LOOP verification — Task 20: memory.explain enrichment (validity,
 * contradiction status, evidence gaps) and retrieval traces (which filters
 * applied, why each record matched) on memory.search / memory.current.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { NotFoundError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t20-${name}-`));
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
    evidenceRefs: [{ engine: "external" as const, ref: "note:1" }],
    ...overrides,
  };
}

test("T20: explainRecord — evidenceGaps for no evidence and expired evidence", () => {
  const { engine, dir } = tempEngine("gaps");
  try {
    engine.createScope("lib", "Library");
    const noEvidence = engine.addRecord(
      fact("lib", "No evidence", "unsourced claim", {
        evidenceRefs: [],
        epistemicClass: "derived",
        sourceKind: "analysis_evidence",
      }),
    );
    const explainedNoEvidence = engine.explainRecord(noEvidence.recordId);
    assert.equal(explainedNoEvidence.evidenceGaps.length, 1);
    assert.match(explainedNoEvidence.evidenceGaps[0]!, /no evidenceRefs/);

    const expired = engine.addRecord(
      fact("lib", "Stale source", "old claim", {
        evidenceRefs: [
          { engine: "external", ref: "note:2", expiresAt: "2020-01-01T00:00:00.000Z" },
        ],
      }),
    );
    const explainedExpired = engine.explainRecord(expired.recordId, "2026-01-01T00:00:00.000Z");
    assert.equal(explainedExpired.evidenceGaps.length, 1);
    assert.match(explainedExpired.evidenceGaps[0]!, /expired at 2020-01-01T00:00:00\.000Z/);

    const fresh = engine.addRecord(fact("lib", "Fresh source", "current claim"));
    assert.deepEqual(engine.explainRecord(fresh.recordId).evidenceGaps, []);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T20: explainRecord — validity window vs currentlyValid", () => {
  const { engine, dir } = tempEngine("validity");
  try {
    engine.createScope("lib", "Library");
    const currentRecord = engine.addRecord(fact("lib", "Now", "true today"));
    const explainedCurrent = engine.explainRecord(currentRecord.recordId);
    assert.equal(explainedCurrent.validity.currentlyValid, true);

    const future = engine.addRecord(
      fact("lib", "Later", "true eventually", { validFrom: "2999-01-01T00:00:00.000Z" }),
    );
    const explainedFuture = engine.explainRecord(future.recordId);
    assert.equal(explainedFuture.validity.currentlyValid, false);
    assert.equal(explainedFuture.validFrom, "2999-01-01T00:00:00.000Z");

    // Explicit `at` in the future makes the not-yet-valid record valid then.
    const explainedAtFuture = engine.explainRecord(future.recordId, "3000-01-01T00:00:00.000Z");
    assert.equal(explainedAtFuture.validity.currentlyValid, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T20: explainRecord — contradiction group status surfaced", () => {
  const { engine, dir } = tempEngine("contradiction");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(fact("lib", "Region", "eu-west-1"));
    const b = engine.addRecord(fact("lib", "Region", "eu-central-1"));
    const withoutGroup = engine.explainRecord(a.recordId);
    assert.deepEqual(withoutGroup.contradiction, { groupId: null, status: null, groupSize: null });

    const group = engine.registerContradiction("lib", "Region", [a.recordId, b.recordId]);
    const explained = engine.explainRecord(a.recordId);
    assert.equal(explained.contradiction.groupId, group.groupId);
    assert.equal(explained.contradiction.status, "open");
    assert.equal(explained.contradiction.groupSize, 2);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T20: searchRecordsTraced — appliedFilters echo, per-record reasons, truncation", () => {
  const { engine, dir } = tempEngine("search");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(fact("lib", "A", "alpha", { tags: ["urgent"], confidence: 0.95 }));
    engine.addRecord(fact("lib", "B", "beta", { tags: ["urgent"], confidence: 0.5 }));
    engine.addRecord(fact("lib", "C", "gamma", { tags: ["low"], confidence: 0.95 }));

    const byTag = engine.searchRecordsTraced({ scope: "lib", tag: "urgent" });
    assert.equal(byTag.records.length, 2);
    assert.deepEqual(byTag.trace.appliedFilters, { scope: "lib", tag: "urgent" });
    for (const record of byTag.records) {
      const reasons = byTag.trace.matches[record.recordId]!;
      assert.ok(reasons.some((r) => r.filter === "tag" && r.reason.includes("urgent")));
      assert.ok(reasons.some((r) => r.filter === "scope"));
    }

    const byConfidence = engine.searchRecordsTraced({ scope: "lib", confidenceMin: 0.9 });
    assert.equal(byConfidence.records.length, 2);
    assert.ok(
      byConfidence.trace.matches[byConfidence.records[0]!.recordId]!.some(
        (r) => r.filter === "confidenceMin" && r.reason.includes("confidenceMin 0.9"),
      ),
    );

    const truncatedResult = engine.searchRecordsTraced({ scope: "lib", limit: 1 });
    assert.equal(truncatedResult.records.length, 1);
    assert.equal(truncatedResult.trace.totalMatches, 3);
    assert.equal(truncatedResult.trace.truncated, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T20: currentRecordsTraced — trace shape and validity reasons", () => {
  const { engine, dir } = tempEngine("current");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(fact("lib", "Cadence", "Tuesday"));
    const result = engine.currentRecordsTraced({ scope: "lib", subject: "Cadence" });
    assert.equal(result.records.length, 1);
    assert.deepEqual(result.trace.appliedFilters, { subject: "Cadence" });
    const reasons = result.trace.matches[result.records[0]!.recordId]!;
    assert.ok(reasons.some((r) => r.filter === "status"));
    assert.ok(reasons.some((r) => r.filter === "validFrom"));
    assert.ok(reasons.some((r) => r.filter === "validUntil"));
    assert.ok(reasons.some((r) => r.filter === "subject"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T20: dispatcher — memory.search/memory.current/memory.explain enriched envelopes", () => {
  const { engine, dir } = tempEngine("dispatch");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(
      fact("lib", "Rate limit", "120 rpm", {
        evidenceRefs: [],
        epistemicClass: "derived",
        sourceKind: "analysis_evidence",
      }),
    );

    const searched = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.search",
      request: { scope: "lib", exactSubject: "Rate limit" },
    });
    assert.equal(searched.ok, true);
    if (searched.ok) {
      const result = searched.result as { records: unknown[]; trace: { appliedFilters: unknown } };
      assert.equal(result.records.length, 1);
      assert.deepEqual(result.trace.appliedFilters, { scope: "lib", exactSubject: "Rate limit" });
    }

    const current = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.current",
      request: { scope: "lib" },
    });
    assert.equal(current.ok, true);
    if (current.ok) {
      const result = current.result as { records: unknown[]; trace: unknown };
      assert.equal(result.records.length, 1);
      assert.ok(result.trace !== undefined);
    }

    const explained = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.explain",
      request: { recordId: record.recordId },
    });
    assert.equal(explained.ok, true);
    if (explained.ok) {
      const result = explained.result as {
        evidenceGaps: string[];
        validity: { currentlyValid: boolean };
        contradiction: { groupId: string | null };
      };
      assert.equal(result.evidenceGaps.length, 1);
      assert.equal(result.validity.currentlyValid, true);
      assert.equal(result.contradiction.groupId, null);
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T20: negative — invalid `at` is a typed error, unknown record is a typed not-found", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(
      fact("lib", "Rate limit", "120 rpm", {
        validFrom: "2026-01-01T00:00:00.000Z",
        validUntil: "2026-12-31T00:00:00.000Z",
      }),
    );
    // A malformed `at` must not silently mis-state validity/evidence gaps.
    assert.throws(
      () => engine.explainRecord(record.recordId, "not-a-timestamp"),
      (err: unknown) => err instanceof ValidationError,
    );
    // Unknown record id is a typed not-found through the enriched API.
    assert.throws(
      () => engine.explainRecord("mem_doesnotexist"),
      (err: unknown) => err instanceof NotFoundError,
    );
    // The dispatcher returns a typed error envelope, never a throw.
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.explain",
      request: { recordId: record.recordId, at: "bad" },
    });
    assert.equal(envelope.ok, false);
    if (!envelope.ok) {
      assert.equal(envelope.error.code, "MEMORY_VALIDATION_FAILED");
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
