/**
 * CHILD LOOP 1 verification — Task 28: Integrate Study → Memory proposals.
 * Proves: verified Study findings AND user annotations become Memory
 * CANDIDATES (never direct records) carrying Study/version/source-revision
 * provenance via evidenceRef (engine "study_document"); Study records stay
 * EXTERNAL; promotion eligibility for verified findings
 * (verified_study_fact); bounded batches; partial failure; intake
 * authorization; contract dispatch; and persistence.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { MAX_STUDY_PROPOSALS_PER_BATCH, studyEvidenceRef } from "../src/engine/study.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t28-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function finding(subject: string, content: string, overrides: Record<string, unknown> = {}) {
  return {
    type: "finding" as const,
    subject,
    content,
    studyId: "study-9",
    version: "1.2.0",
    sourceRevision: "rfc-1234#s3",
    ...overrides,
  };
}

function annotation(subject: string, content: string, overrides: Record<string, unknown> = {}) {
  return {
    type: "annotation" as const,
    subject,
    content,
    studyId: "study-9",
    version: "1.2.0",
    sourceRevision: "rfc-1234#s3",
    ...overrides,
  };
}

test("T28: verified Study findings become candidates with Study/version/source-revision provenance", () => {
  const { engine, dir } = tempEngine("findings");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposeStudy("lib", [
      finding("Backoff", "Exponential backoff improves resilience"),
    ]);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.rejected.length, 0);
    const candidate = result.accepted[0]!;
    assert.equal(candidate.status, "open");
    assert.equal(candidate.provenance.sourceKind, "study_finding");
    assert.equal(candidate.epistemicClass, "observed");
    assert.equal(candidate.kind, "fact");
    // Study/version/source-revision provenance, by reference (Study stays external).
    assert.equal(candidate.evidenceRefs.length, 1);
    assert.equal(candidate.evidenceRefs[0]!.engine, "study_document");
    assert.equal(candidate.evidenceRefs[0]!.ref, "study-9#v1.2.0#revrfc-1234#s3");
    assert.deepEqual(studyEvidenceRef("study-9", "1.2.0", "rfc-1234#s3"), candidate.evidenceRefs[0]);
    // Not a durable record yet; visible in the intake stream.
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
    assert.equal(engine.listCandidates({ scope: "lib", status: "open" }).length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T28: verified findings are promotion-eligible via verified_study_fact", () => {
  const { engine, dir } = tempEngine("promotion");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposeStudy("lib", [
      finding("Region", "eu-central-1 is the region"),
    ]);
    const candidate = result.accepted[0]!;
    const assessment = engine.evaluatePromotion(candidate.candidateId);
    assert.ok(assessment.matchedPolicies.includes("verified_study_fact"));
    assert.equal(assessment.eligible, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T28: user annotations become candidates with the same Study provenance", () => {
  const { engine, dir } = tempEngine("annotations");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposeStudy("lib", [
      annotation("Backoff note", "User notes the jitter recommendation applies here", {
        actor: { kind: "human", name: "kim" },
      }),
    ]);
    assert.equal(result.accepted.length, 1);
    const candidate = result.accepted[0]!;
    assert.equal(candidate.provenance.sourceKind, "user_note");
    assert.equal(candidate.kind, "note");
    assert.equal(candidate.provenance.actor.name, "kim");
    assert.equal(candidate.evidenceRefs[0]!.engine, "study_document");
    assert.equal(candidate.evidenceRefs[0]!.ref, "study-9#v1.2.0#revrfc-1234#s3");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T28: bounded batch — excess proposals are explicitly rejected", () => {
  const { engine, dir } = tempEngine("bounded");
  try {
    engine.createScope("lib", "Library");
    const proposals = Array.from({ length: MAX_STUDY_PROPOSALS_PER_BATCH + 3 }, (_, i) =>
      finding(`Finding ${i}`, `content ${i}`, { studyId: `study-${i}` }),
    );
    const result = engine.proposeStudy("lib", proposals);
    assert.equal(result.accepted.length, MAX_STUDY_PROPOSALS_PER_BATCH);
    assert.equal(result.rejected.length, 3);
    assert.match(result.rejected[0]!.message, /batch exceeds/);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T28: partial failure — a malformed proposal is rejected, the valid one accepted", () => {
  const { engine, dir } = tempEngine("partial");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposeStudy("lib", [
      { type: "finding", subject: "Broken", content: "missing study provenance", studyId: "", version: "1", sourceRevision: "r" },
      finding("Valid", "this one is fine"),
    ]);
    assert.equal(result.rejected.length, 1);
    assert.equal(result.rejected[0]!.code, "MEMORY_VALIDATION_FAILED");
    assert.match(result.rejected[0]!.message, /studyId is required/);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.accepted[0]!.subject, "Valid");
    assert.equal(engine.listCandidates({ scope: "lib", status: "open" }).length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T28: intake authorization — allowlist gates the Study caller", () => {
  const { engine, dir } = tempEngine("allowlist");
  try {
    engine.createScope("lib", "Library");
    engine.setScopeIntakePolicy("lib", { mode: "allowlist", allow: ["human:kim"] });
    const denied = engine.proposeStudy("lib", [finding("Denied", "x")]);
    assert.equal(denied.accepted.length, 0);
    assert.equal(denied.rejected[0]!.code, "MEMORY_INTAKE_UNAUTHORIZED");
    engine.setScopeIntakePolicy("lib", { mode: "allowlist", allow: ["human:kim", "engine:study_document"] });
    const allowed = engine.proposeStudy("lib", [finding("Allowed", "y")]);
    assert.equal(allowed.accepted.length, 1);
    assert.equal(allowed.accepted[0]!.caller!.name, "study_document");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T28: versioned contract — memory.study.propose through the dispatcher", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.study.propose",
      request: {
        scope: "lib",
        proposals: [{ type: "finding", subject: "Latency", content: "p99 improved", studyId: "study-1", version: "2.0", sourceRevision: "s1" }],
      },
    });
    assert.equal(envelope.ok, true);
    if (envelope.ok) {
      const result = envelope.result as { accepted: Array<{ subject: string }>; rejected: unknown[] };
      assert.equal(result.accepted.length, 1);
      assert.equal(result.accepted[0]!.subject, "Latency");
      assert.equal(result.rejected.length, 0);
    }
    const malformed = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.study.propose",
      request: { scope: "lib", proposals: "nope" },
    });
    assert.equal(malformed.ok, false);
    if (!malformed.ok) assert.equal(malformed.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T28: proposals survive restart in the intake stream", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t28-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const result = engine.proposeStudy("lib", [finding("Persisted", "survives restart")]);
    assert.equal(result.accepted.length, 1);
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const stream = engine.listCandidates({ scope: "lib", status: "open" });
      assert.equal(stream.length, 1);
      assert.equal(stream[0]!.evidenceRefs[0]!.engine, "study_document");
      assert.equal(stream[0]!.provenance.sourceKind, "study_finding");
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});