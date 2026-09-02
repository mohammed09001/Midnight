/**
 * Task 6 (Midnight Memory Execution 02) — harden external evidence
 * references. Proves the one genuine gap fixed here (duplicate {engine,ref}
 * pairs) and the "retired" reuse path (a new evidence-backed record
 * supersedes the old one; evidence is never silently swapped).
 *
 * The other five cases in the missing/malformed/expired/duplicated/
 * inaccessible/retired matrix are already proven elsewhere and are not
 * re-tested here (docs/EVIDENCE_REFERENCES.md has the full table):
 *   - missing:   test/t27_performance.test.ts
 *   - malformed: test/t3_schema.test.ts
 *   - expired:   test/t13_retention.test.ts, test/t20_explain_traces.test.ts
 *   - inaccessible: Performance/tests/test_memory_bridge.py (sealed-envelope checks)
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";

const KIM = { kind: "human" as const, name: "kim" };

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t51-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

test("T51: addRecord rejects an exact-duplicate {engine, ref} pair", () => {
  const { engine, dir } = tempEngine("record-dup");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () =>
        engine.addRecord({
          scope: "lib", kind: "fact", subject: "S", content: "C",
          actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9,
          sourceKind: "user_note",
          evidenceRefs: [
            { engine: "performance", ref: "perf:1" },
            { engine: "performance", ref: "perf:1" },
          ],
        }),
      (err: unknown) =>
        err instanceof Error &&
        (err as { code?: string }).code === "MEMORY_VALIDATION_FAILED" &&
        /duplicate/.test(err.message),
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T51: addCandidate rejects an exact-duplicate {engine, ref} pair", () => {
  const { engine, dir } = tempEngine("candidate-dup");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () =>
        engine.addCandidate({
          scope: "lib", kind: "fact", subject: "S", content: "C",
          actor: KIM, method: "m", epistemicClass: "derived", confidence: 0.8,
          sourceKind: "performance_evidence", reason: "test",
          evidenceRefs: [
            { engine: "performance", ref: "perf:1" },
            { engine: "performance", ref: "perf:1" },
          ],
        }),
      (err: unknown) => err instanceof Error && (err as { code?: string }).code === "MEMORY_VALIDATION_FAILED",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T51: proposePerformanceLessons rejects a lesson with duplicated evidenceRefs, batch continues", () => {
  const { engine, dir } = tempEngine("lesson-dup");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposePerformanceLessons("lib", [
      { subject: "Dup", content: "x", evidenceRefs: ["perf:1", "perf:1"] },
      { subject: "Good", content: "y", evidenceRefs: ["perf:2"] },
    ]);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.accepted[0]!.subject, "Good");
    assert.equal(result.rejected.length, 1);
    assert.equal(result.rejected[0]!.code, "MEMORY_VALIDATION_FAILED");
    assert.match(result.rejected[0]!.message, /duplicate/);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T51: negative control — the same literal ref from two different engines is NOT a duplicate", () => {
  const { engine, dir } = tempEngine("negative-control");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord({
      scope: "lib", kind: "fact", subject: "S", content: "C",
      actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9,
      sourceKind: "user_note",
      evidenceRefs: [
        { engine: "performance", ref: "1" },
        { engine: "study_document", ref: "1" },
      ],
    });
    assert.equal(record.evidenceRefs.length, 2);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T51: retired evidence is communicated by a new superseding record, never a silent evidence swap", () => {
  const { engine, dir } = tempEngine("retirement");
  try {
    engine.createScope("lib", "Library");
    const proposal = engine.proposePerformanceLessons("lib", [
      { subject: "Backoff lesson", content: "Backoff reduces retry storms", evidenceRefs: ["perf:1"] },
    ]);
    const candidate = proposal.accepted[0]!;
    const record1 = engine.promoteCandidate(candidate.candidateId, {
      actor: KIM,
      policy: "explicit_user_decision",
    });
    assert.equal(record1.status, "active");

    const record2 = engine.supersedeRecord(record1.recordId, {
      content: "Backoff reduces retry storms (perf:1 evidence retired; see perf:2)",
      actor: KIM,
      method: "performance_lesson_retirement",
      reason: "Performance evidence perf:1 retired; see perf:2 for the current lesson",
    });
    assert.equal(record2.supersedesId, record1.recordId);

    const refetched1 = engine.getRecord(record1.recordId);
    assert.equal(refetched1.status, "superseded");
    assert.match(refetched1.supersededReason ?? "", /retired/);

    // The API cannot silently swap evidence: supersedeRecord always carries
    // forward the prior record's evidenceRefs verbatim. Introducing new
    // evidence requires a genuinely new evidence-backed proposal/record.
    assert.deepEqual(record2.evidenceRefs, record1.evidenceRefs);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
