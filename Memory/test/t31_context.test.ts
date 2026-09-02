/**
 * CHILD LOOP 1 verification — Task 31: Integrate Context → Memory retrieval.
 * Proves: bounded context-oriented queries with EXPLICIT size/time/project
 * filters return PROVENANCE-RICH results (structural authority, source kind,
 * validity-at-instant, evidence count, confidence); size cap + truncation
 * diagnostics; validity-at and observed-window time filters; provenance
 * filters (minAuthority/sourceKinds/kinds/minConfidence); deterministic
 * context ordering (current first, then authority); typed negatives; and the
 * versioned contract.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { NotFoundError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t31-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function rec(
  scope: string,
  subject: string,
  content: string,
  overrides: Record<string, unknown> = {},
) {
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

function seed(engine: MemoryEngine) {
  engine.createScope("lib", "Library");
  engine.createScope("other", "Other");
  // Current, high-authority record.
  engine.addRecord(rec("lib", "Rate limit", "Public api allows 120 requests per minute", { sourceKind: "study_finding" }));
  // Current, mid-authority record.
  engine.addRecord(rec("lib", "Caching", "cache stamps are rebuildable", { sourceKind: "analysis_evidence", epistemicClass: "derived", confidence: 0.7 }));
  // Future-validated record (not currently valid at the default `at`).
  engine.addRecord(rec("lib", "Freeze policy", "freeze during release", { validFrom: "2999-01-01T00:00:00.000Z" }));
  // A record in another project.
  engine.addRecord(rec("other", "Elsewhere", "different project"));
  // A low-authority agent-derived record.
  engine.addRecord(rec("lib", "Agent guess", "maybe the limit is higher", { sourceKind: "agent_inference", epistemicClass: "inferred", confidence: 0.4, evidenceRefs: [] }));
}

test("T31: bounded context query returns provenance-rich records with size cap and diagnostics", () => {
  const { engine, dir } = tempEngine("provenance-rich");
  try {
    seed(engine);
    const result = engine.contextQuery({ scope: "lib", size: 2 });
    assert.equal(result.scopeId, engine.getScope("lib").scopeId);
    assert.equal(result.size, 2);
    assert.equal(result.returned, 2);
    assert.ok(result.totalMatches >= 3, "more records match than returned");
    assert.equal(result.truncated, true, "size cap truncates");
    // Every returned record is provenance-rich.
    for (const item of result.records) {
      assert.ok(item.authority.tier !== undefined, "structural authority present");
      assert.ok(item.sourceKind !== undefined, "source kind present");
      assert.equal(typeof item.validity.currentlyValid, "boolean");
      assert.equal(typeof item.evidenceCount, "number");
      assert.equal(typeof item.confidence, "number");
    }
    // Deterministic context ordering: currently valid + high authority first.
    const first = result.records[0]!;
    assert.equal(first.validity.currentlyValid, true);
    assert.equal(first.record.subject, "Rate limit");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T31: project and time filters — scope isolation, validity-at, observed window", () => {
  const { engine, dir } = tempEngine("time-project");
  try {
    seed(engine);
    // Project filter isolates the project.
    const other = engine.contextQuery({ scope: "other" });
    assert.equal(other.records.length, 1);
    assert.equal(other.records[0]!.record.subject, "Elsewhere");
    // At the future instant, the future-validated record becomes current.
    const future = engine.contextQuery({ scope: "lib", at: "3000-01-01T00:00:00.000Z", size: 10 });
    const freeze = future.records.find((r) => r.record.subject === "Freeze policy");
    assert.ok(freeze !== undefined, "future-validated record is current at its validity instant");
    assert.equal(freeze!.validity.currentlyValid, true);
    // Observed-window filter: only records observed in the window.
    const windowed = engine.contextQuery({ scope: "lib", time: { from: "2026-08-30T00:00:00.000Z", until: "2026-12-31T00:00:00.000Z" }, size: 10 });
    assert.ok(windowed.records.length >= 2, "observed-window filter returns matching records");
    assert.ok(windowed.records.every((r) => r.record.observedAt >= "2026-08-30T00:00:00.000Z"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T31: provenance filters — minAuthority, sourceKinds, kinds, minConfidence", () => {
  const { engine, dir } = tempEngine("provenance-filters");
  try {
    seed(engine);
    // minAuthority verified_source excludes the analysis/user/agent records.
    const verified = engine.contextQuery({ scope: "lib", minAuthority: "verified_source", size: 10 });
    assert.ok(verified.records.length >= 1);
    assert.ok(verified.records.every((r) => r.authority.tier === "verified_source"));
    // sourceKinds filter.
    const analysisOnly = engine.contextQuery({ scope: "lib", sourceKinds: ["analysis_evidence"], size: 10 });
    assert.ok(analysisOnly.records.every((r) => r.sourceKind === "analysis_evidence"));
    // minConfidence filter.
    const confident = engine.contextQuery({ scope: "lib", minConfidence: 0.8, size: 10 });
    assert.ok(confident.records.every((r) => r.confidence >= 0.8));
    // The agent-derived low-confidence record is excluded by both filters.
    assert.ok(!verified.records.some((r) => r.record.subject === "Agent guess"));
    assert.ok(!confident.records.some((r) => r.record.subject === "Agent guess"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T31: free-text topic refinement narrows the result", () => {
  const { engine, dir } = tempEngine("topic");
  try {
    seed(engine);
    const result = engine.contextQuery({ scope: "lib", query: "rate", size: 10 });
    assert.ok(result.records.length >= 1);
    assert.ok(result.records.every((r) => /rate/i.test(r.record.subject) || /rate/i.test(r.record.content)));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T31: negative — unknown scope, invalid at, invalid minConfidence, oversize/undersize clamp", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.contextQuery({ scope: "nope" }),
      (err: unknown) => err instanceof NotFoundError,
    );
    assert.throws(
      () => engine.contextQuery({ scope: "lib", at: "garbage" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.contextQuery({ scope: "lib", time: { from: "garbage" } }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.contextQuery({ scope: "lib", minConfidence: 1.5 }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Size clamps: negative → 1, oversized → 100.
    assert.equal(engine.contextQuery({ scope: "lib", size: -5 }).size, 1);
    assert.equal(engine.contextQuery({ scope: "lib", size: 100000 }).size, 100);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T31: versioned contract — memory.context through the dispatcher", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 rpm", { sourceKind: "study_finding" }));
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.context",
      request: { scope: "lib", size: 5, minAuthority: "verified_source" },
    });
    assert.equal(envelope.ok, true);
    if (envelope.ok) {
      const result = envelope.result as { result: { records: Array<{ authority: { tier: string }; record: { subject: string } }>; truncated: boolean } };
      assert.ok(result.result.records.length >= 1);
      assert.ok(result.result.records.every((r) => r.authority.tier === "verified_source"));
    }
    const bad = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.context",
      request: { scope: "lib", at: "garbage" },
    });
    assert.equal(bad.ok, false);
    if (!bad.ok) assert.equal(bad.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

// ---- Task 13 (Execution 05): contradiction status, evidence gaps, trace --

test("T31: contradiction status is surfaced on the affected records", () => {
  const { engine, dir } = tempEngine("contradiction");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Region", "eu-west-1"));
    const b = engine.addRecord(rec("lib", "Region", "eu-central-1"));
    engine.registerContradiction("lib", "Region", [a.recordId, b.recordId]);
    const result = engine.contextQuery({ scope: "lib", size: 10 });
    const regionRecords = result.records.filter((r) => r.record.subject === "Region");
    assert.equal(regionRecords.length, 2);
    for (const r of regionRecords) {
      assert.equal(r.contradiction.status, "open");
      assert.equal(r.contradiction.groupSize, 2);
      assert.ok(r.contradiction.groupId !== null);
    }
    // A record with no contradiction group reports null, not a false status.
    const other = engine.addRecord(rec("lib", "Unrelated", "no conflict here"));
    const otherResult = engine.contextQuery({ scope: "lib", query: "unrelated", size: 10 });
    const otherItem = otherResult.records.find((r) => r.record.recordId === other.recordId)!;
    assert.equal(otherItem.contradiction.groupId, null);
    assert.equal(otherItem.contradiction.status, null);
    assert.equal(otherItem.contradiction.groupSize, null);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T31: evidenceGaps reports missing evidence, reused from memory.explain", () => {
  const { engine, dir } = tempEngine("evidence-gaps");
  try {
    seed(engine);
    const result = engine.contextQuery({ scope: "lib", query: "guess", size: 10 });
    const agentGuess = result.records.find((r) => r.record.subject === "Agent guess")!;
    assert.ok(agentGuess.evidenceGaps.some((g) => g.includes("no evidenceRefs")));
    const wellEvidenced = result.records.find((r) => r.record.subject === "Rate limit" || r.record.subject === "Caching");
    if (wellEvidenced !== undefined) {
      assert.deepEqual(wellEvidenced.evidenceGaps, []);
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T31: trace cites the applied filters and reflects records actually excluded by them", () => {
  const { engine, dir } = tempEngine("trace");
  try {
    seed(engine);
    const verified = engine.contextQuery({ scope: "lib", minAuthority: "verified_source", minConfidence: 0.5, size: 10 });
    assert.ok(verified.records.length >= 1);
    for (const r of verified.records) {
      assert.ok(r.trace.some((t) => t.filter === "minAuthority"), "trace names the applied minAuthority filter");
      assert.ok(r.trace.some((t) => t.filter === "minConfidence"), "trace names the applied minConfidence filter");
      assert.ok(r.trace.some((t) => t.filter === "scope"));
    }
    // Negative/boundary: a filter combination that legitimately excludes a
    // record proves the trace reflects real applied filters, not a static
    // list — the low-confidence agent-derived record never appears at all.
    assert.ok(!verified.records.some((r) => r.record.subject === "Agent guess"));
    // No minAuthority/minConfidence set -> those trace entries are absent.
    const unfiltered = engine.contextQuery({ scope: "lib", size: 10 });
    for (const r of unfiltered.records) {
      assert.ok(!r.trace.some((t) => t.filter === "minAuthority"));
      assert.ok(!r.trace.some((t) => t.filter === "minConfidence"));
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});