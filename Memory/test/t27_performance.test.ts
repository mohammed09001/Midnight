/**
 * CHILD LOOP 1 verification — Task 27: Integrate Performance → Memory
 * proposals. Proves: bounded evidence-backed Performance lessons enter the
 * candidate intake stream (NEVER direct records) via the versioned contract;
 * Performance records stay EXTERNAL (referenced by evidenceRef engine
 * "performance"); evidence-backed enforcement; bounded evidence per lesson and
 * bounded batch; intake authorization; promotion eligibility for
 * multi-evidence lessons; partial-failure behavior; contract dispatch; and
 * persistence.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import {
  MAX_PERFORMANCE_LESSONS_PER_BATCH,
  MAX_PERFORMANCE_EVIDENCE_PER_LESSON,
} from "../src/engine/performance.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t27-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function lesson(subject: string, content: string, refs: string[]) {
  return { subject, content, evidenceRefs: refs };
}

test("T27: evidence-backed Performance lessons enter the candidate stream, never direct records", () => {
  const { engine, dir } = tempEngine("intake");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposePerformanceLessons("lib", [
      lesson("Retry storms", "Backoff caps retry storms", ["perf:run-42"]),
    ]);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.rejected.length, 0);
    const candidate = result.accepted[0]!;
    assert.equal(candidate.status, "open", "enters the intake stream as a candidate");
    assert.equal(candidate.provenance.sourceKind, "performance_evidence");
    assert.equal(candidate.epistemicClass, "derived");
    assert.equal(candidate.kind, "observation");
    // Performance records stay EXTERNAL — referenced, never embedded.
    assert.equal(candidate.evidenceRefs.length, 1);
    assert.equal(candidate.evidenceRefs[0]!.engine, "performance");
    assert.equal(candidate.evidenceRefs[0]!.ref, "perf:run-42");
    // Not a durable record yet.
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
    // The candidate is visible in the intake stream.
    const stream = engine.listCandidates({ scope: "lib", status: "open" });
    assert.equal(stream.length, 1);
    assert.equal(stream[0]!.candidateId, candidate.candidateId);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T27: evidence-backed enforcement — a lesson without evidence is rejected, and the batch continues", () => {
  const { engine, dir } = tempEngine("evidence-gate");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposePerformanceLessons("lib", [
      lesson("No evidence", "this lesson has no backing", []),
      lesson("Good lesson", "this one is evidence-backed", ["perf:run-1"]),
    ]);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.rejected.length, 1);
    assert.equal(result.rejected[0]!.code, "MEMORY_VALIDATION_FAILED");
    assert.match(result.rejected[0]!.message, /evidence-backed/);
    assert.equal(result.accepted[0]!.subject, "Good lesson");
    // The bad lesson produced NO candidate.
    assert.equal(engine.listCandidates({ scope: "lib", status: "open" }).length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T27: bounded — evidence refs per lesson and lessons per batch are capped, excess rejected", () => {
  const { engine, dir } = tempEngine("bounded");
  try {
    engine.createScope("lib", "Library");
    // Too many evidence refs on one lesson → rejected.
    const tooManyRefs = Array.from({ length: MAX_PERFORMANCE_EVIDENCE_PER_LESSON + 1 }, (_, i) => `perf:${i}`);
    const one = engine.proposePerformanceLessons("lib", [lesson("Too many refs", "x", tooManyRefs)]);
    assert.equal(one.accepted.length, 0);
    assert.equal(one.rejected.length, 1);
    assert.match(one.rejected[0]!.message, /evidenceRefs exceeds/);

    // Too many lessons in a batch → excess explicitly rejected.
    const lessons = Array.from({ length: MAX_PERFORMANCE_LESSONS_PER_BATCH + 5 }, (_, i) =>
      lesson(`Lesson ${i}`, `content ${i}`, [`perf:${i}`]),
    );
    const batch = engine.proposePerformanceLessons("lib", lessons);
    assert.equal(batch.accepted.length, MAX_PERFORMANCE_LESSONS_PER_BATCH);
    assert.equal(batch.rejected.length, 5);
    assert.match(batch.rejected[0]!.message, /batch exceeds/);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T27: intake authorization — allowlist scopes gate the Performance caller", () => {
  const { engine, dir } = tempEngine("allowlist");
  try {
    engine.createScope("lib", "Library");
    // Allowlist WITHOUT the Performance caller → rejected.
    engine.setScopeIntakePolicy("lib", { mode: "allowlist", allow: ["human:kim"] });
    const denied = engine.proposePerformanceLessons("lib", [lesson("Denied", "x", ["perf:1"])]);
    assert.equal(denied.accepted.length, 0);
    assert.equal(denied.rejected.length, 1);
    assert.equal(denied.rejected[0]!.code, "MEMORY_INTAKE_UNAUTHORIZED");
    // Allowlist WITH the Performance caller → accepted.
    engine.setScopeIntakePolicy("lib", { mode: "allowlist", allow: ["human:kim", "engine:performance"] });
    const allowed = engine.proposePerformanceLessons("lib", [lesson("Allowed", "y", ["perf:2"])]);
    assert.equal(allowed.accepted.length, 1);
    assert.equal(allowed.accepted[0]!.caller!.name, "performance");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T27: a multi-evidence lesson is promotion-eligible via repeated_evidence_backed_lesson", () => {
  const { engine, dir } = tempEngine("promotion");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposePerformanceLessons("lib", [
      lesson("Backoff lesson", "Backoff with jitter reduces retry storms", ["perf:run-1", "perf:run-2"]),
    ]);
    const candidate = result.accepted[0]!;
    const assessment = engine.evaluatePromotion(candidate.candidateId);
    assert.ok(assessment.matchedPolicies.includes("repeated_evidence_backed_lesson"));
    assert.equal(assessment.eligible, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T27: versioned contract — memory.performance.propose through the dispatcher", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.performance.propose",
      request: {
        scope: "lib",
        lessons: [{ subject: "Latency", content: "p99 latency regressed", evidenceRefs: ["perf:run-7"] }],
      },
    });
    assert.equal(envelope.ok, true);
    if (envelope.ok) {
      const result = envelope.result as { accepted: Array<{ subject: string }>; rejected: unknown[] };
      assert.equal(result.accepted.length, 1);
      assert.equal(result.accepted[0]!.subject, "Latency");
      assert.equal(result.rejected.length, 0);
    }
    // Malformed request → typed error envelope.
    const bad = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.performance.propose",
      request: { scope: "lib", lessons: "not-an-array" },
    });
    assert.equal(bad.ok, false);
    if (!bad.ok) assert.equal(bad.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T27: proposals survive restart in the intake stream", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t27-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const result = engine.proposePerformanceLessons("lib", [lesson("Lesson", "persisted", ["perf:run-9"])]);
    assert.equal(result.accepted.length, 1);
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const stream = engine.listCandidates({ scope: "lib", status: "open" });
      assert.equal(stream.length, 1);
      const candidate = stream[0]!;
      assert.equal(candidate.evidenceRefs[0]!.engine, "performance");
      assert.equal(candidate.provenance.sourceKind, "performance_evidence");
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});