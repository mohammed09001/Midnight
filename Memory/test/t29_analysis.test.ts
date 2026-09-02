/**
 * CHILD LOOP 1 verification — Task 29: Integrate Analysis → Memory proposals.
 * Proves: reusable architectural findings are proposed ONLY through
 * EVIDENCE-LINKED candidates (never direct insertion); Analysis records stay
 * EXTERNAL (evidenceRef engine "analysis"); sourceKind analysis_evidence with
 * derived epistemic honesty (never claimed observed); bounded batches;
 * partial failure; intake authorization; promotion eligibility for
 * multi-evidence findings; contract dispatch; and persistence.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import {
  MAX_ANALYSIS_FINDINGS_PER_BATCH,
  MAX_ANALYSIS_EVIDENCE_PER_FINDING,
} from "../src/engine/analysis.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t29-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function finding(subject: string, content: string, refs: string[]) {
  return { subject, content, evidenceRefs: refs };
}

test("T29: evidence-linked architectural findings become candidates, never direct records", () => {
  const { engine, dir } = tempEngine("intake");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposeAnalysis("lib", [
      finding("Modular gateways", "Gateway modules should stay independent", ["analysis:arch-7"]),
    ]);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.rejected.length, 0);
    const candidate = result.accepted[0]!;
    assert.equal(candidate.status, "open");
    assert.equal(candidate.provenance.sourceKind, "analysis_evidence");
    // Epistemic honesty: a finding derived from analysis is never claimed observed.
    assert.equal(candidate.epistemicClass, "derived");
    assert.equal(candidate.kind, "note");
    // Analysis records stay EXTERNAL — evidence-linked, never embedded.
    assert.equal(candidate.evidenceRefs.length, 1);
    assert.equal(candidate.evidenceRefs[0]!.engine, "analysis");
    assert.equal(candidate.evidenceRefs[0]!.ref, "analysis:arch-7");
    // NOT a direct record; visible only in the intake stream.
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
    assert.equal(engine.listCandidates({ scope: "lib", status: "open" }).length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T29: evidence-link enforcement — a finding without evidence is rejected, batch continues", () => {
  const { engine, dir } = tempEngine("evidence-gate");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposeAnalysis("lib", [
      finding("No evidence", "this finding has no backing", []),
      finding("Valid", "this one is evidence-linked", ["analysis:arch-1"]),
    ]);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.rejected.length, 1);
    assert.equal(result.rejected[0]!.code, "MEMORY_VALIDATION_FAILED");
    assert.match(result.rejected[0]!.message, /evidence-linked/);
    assert.equal(result.accepted[0]!.subject, "Valid");
    assert.equal(engine.listCandidates({ scope: "lib", status: "open" }).length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T29: bounded — evidence refs per finding and findings per batch are capped", () => {
  const { engine, dir } = tempEngine("bounded");
  try {
    engine.createScope("lib", "Library");
    const tooManyRefs = Array.from({ length: MAX_ANALYSIS_EVIDENCE_PER_FINDING + 1 }, (_, i) => `analysis:${i}`);
    const one = engine.proposeAnalysis("lib", [finding("Too many refs", "x", tooManyRefs)]);
    assert.equal(one.accepted.length, 0);
    assert.equal(one.rejected.length, 1);
    assert.match(one.rejected[0]!.message, /evidenceRefs exceeds/);

    const findings = Array.from({ length: MAX_ANALYSIS_FINDINGS_PER_BATCH + 4 }, (_, i) =>
      finding(`Finding ${i}`, `content ${i}`, [`analysis:${i}`]),
    );
    const batch = engine.proposeAnalysis("lib", findings);
    assert.equal(batch.accepted.length, MAX_ANALYSIS_FINDINGS_PER_BATCH);
    assert.equal(batch.rejected.length, 4);
    assert.match(batch.rejected[0]!.message, /batch exceeds/);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T29: intake authorization — allowlist gates the Analysis caller", () => {
  const { engine, dir } = tempEngine("allowlist");
  try {
    engine.createScope("lib", "Library");
    engine.setScopeIntakePolicy("lib", { mode: "allowlist", allow: ["human:kim"] });
    const denied = engine.proposeAnalysis("lib", [finding("Denied", "x", ["analysis:1"])]);
    assert.equal(denied.accepted.length, 0);
    assert.equal(denied.rejected[0]!.code, "MEMORY_INTAKE_UNAUTHORIZED");
    engine.setScopeIntakePolicy("lib", { mode: "allowlist", allow: ["human:kim", "engine:analysis"] });
    const allowed = engine.proposeAnalysis("lib", [finding("Allowed", "y", ["analysis:2"])]);
    assert.equal(allowed.accepted.length, 1);
    assert.equal(allowed.accepted[0]!.caller!.name, "analysis");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T29: a multi-evidence finding is promotion-eligible via repeated_evidence_backed_lesson", () => {
  const { engine, dir } = tempEngine("promotion");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposeAnalysis("lib", [
      finding("Independent services", "Services should not share mutable state", ["analysis:arch-1", "analysis:arch-2"]),
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

test("T29: versioned contract — memory.analysis.propose through the dispatcher", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.analysis.propose",
      request: {
        scope: "lib",
        findings: [{ subject: "Cache", content: "cache stamps are rebuildable", evidenceRefs: ["analysis:arch-9"] }],
      },
    });
    assert.equal(envelope.ok, true);
    if (envelope.ok) {
      const result = envelope.result as { accepted: Array<{ subject: string }>; rejected: unknown[] };
      assert.equal(result.accepted.length, 1);
      assert.equal(result.accepted[0]!.subject, "Cache");
      assert.equal(result.rejected.length, 0);
    }
    const malformed = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.analysis.propose",
      request: { scope: "lib", findings: "nope" },
    });
    assert.equal(malformed.ok, false);
    if (!malformed.ok) assert.equal(malformed.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T29: proposals survive restart in the intake stream", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t29-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const result = engine.proposeAnalysis("lib", [finding("Persisted", "survives restart", ["analysis:arch-5"])]);
    assert.equal(result.accepted.length, 1);
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const stream = engine.listCandidates({ scope: "lib", status: "open" });
      assert.equal(stream.length, 1);
      assert.equal(stream[0]!.evidenceRefs[0]!.engine, "analysis");
      assert.equal(stream[0]!.provenance.sourceKind, "analysis_evidence");
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});