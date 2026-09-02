/**
 * CHILD LOOP 1 verification — Task 4: provenance and evidence authority.
 * Proves: source-kind taxonomy, authority tiers, and the structural rule
 * that agent-generated summaries are NEVER authoritative as observations,
 * regardless of fluency.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";
import { authorityOf } from "../src/engine/authority.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t4-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

const EVIDENCE = [{ engine: "study_document" as const, ref: "doc:study-9#finding-2" }];

test("T4: verified study finding traces to verified_source authority", () => {
  const { engine, dir } = tempEngine("verified");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord({
      scope: "lib",
      kind: "fact",
      subject: "Bundled sqlite",
      content: "Node 22 ships node:sqlite built in",
      actor: { kind: "agent", name: "worker-1" },
      method: "extracted",
      epistemicClass: "observed",
      confidence: 0.97,
      sourceKind: "study_finding",
      evidenceRefs: EVIDENCE,
    });
    const assessment = engine.explainAuthority(record.recordId);
    assert.equal(assessment.tier, "verified_source");
    assert.equal(assessment.capped, false);
    assert.deepEqual(assessment.capReasons, []);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T4: THE CORE RULE — a fluent agent summary can never become 'observed'", () => {
  const { engine, dir } = tempEngine("fluency");
  try {
    engine.createScope("lib", "Library");
    // Perfectly fluent, confident, well-written agent prose — with evidence
    // pointing at the summarized study — STILL rejected as an observation.
    assert.throws(
      () =>
        engine.addRecord({
          scope: "lib",
          kind: "fact",
          subject: "Rate limiting",
          content:
            "After careful analysis of the codebase, the public API demonstrably allows 120 requests per minute per token.",
          actor: { kind: "agent", name: "summarizer", agentType: "llm" },
          method: "summarized",
          epistemicClass: "observed",
          confidence: 0.99,
          sourceKind: "agent_summary",
          derivedFrom: { engine: "study_document", ref: "doc:study-9" },
          evidenceRefs: [{ engine: "study_document", ref: "doc:study-9" }],
        }),
      (err: unknown) =>
        err instanceof ValidationError &&
        err.message.includes("never authoritative as observations"),
      "authority is structural, not textual",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T4: observed claims require evidence references", () => {
  const { engine, dir } = tempEngine("evidence-required");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () =>
        engine.addRecord({
          scope: "lib",
          kind: "fact",
          subject: "Unsupported",
          content: "Claim with no evidence",
          actor: { kind: "human", name: "kim" },
          method: "asserted",
          epistemicClass: "observed",
          confidence: 0.9,
          sourceKind: "user_note",
          // no evidenceRefs
        }),
      (err: unknown) => err instanceof ValidationError && err.message.includes("evidenceRefs"),
    );
    // unknown sourceKind is not good enough for observed either.
    assert.throws(
      () =>
        engine.addRecord({
          scope: "lib",
          kind: "fact",
          subject: "Unknown source",
          content: "Claim with unknown source",
          actor: { kind: "human", name: "kim" },
          method: "asserted",
          epistemicClass: "observed",
          confidence: 0.9,
          sourceKind: "unknown",
          evidenceRefs: EVIDENCE,
        }),
      (err: unknown) => err instanceof ValidationError && err.message.includes("explicit sourceKind"),
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T4: agent_summary without derivedFrom is rejected — summaries must trace", () => {
  const { engine, dir } = tempEngine("summary-lineage");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () =>
        engine.addRecord({
          scope: "lib",
          kind: "note",
          subject: "Summary",
          content: "A summary of something",
          actor: { kind: "agent", name: "summarizer", agentType: "llm" },
          method: "summarized",
          epistemicClass: "derived",
          confidence: 0.6,
          sourceKind: "agent_summary",
          // no derivedFrom
        }),
      (err: unknown) => err instanceof ValidationError && err.message.includes("derivedFrom"),
    );
    // With derivedFrom it is accepted — as derived, capped authority.
    const record = engine.addRecord({
      scope: "lib",
      kind: "note",
      subject: "Summary",
      content: "A summary of the study",
      actor: { kind: "agent", name: "summarizer", agentType: "llm" },
      method: "summarized",
      epistemicClass: "derived",
      confidence: 0.6,
      sourceKind: "agent_summary",
      derivedFrom: { engine: "study_document", ref: "doc:study-9" },
    });
    const assessment = engine.explainAuthority(record.recordId);
    assert.equal(assessment.tier, "agent_derived");
    assert.equal(assessment.capped, true);
    assert.ok(assessment.capReasons.some((r) => r.includes("agent_summary")));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T4: full authority matrix across source kinds and epistemic classes", () => {
  // Tier mapping is structural:
  assert.equal(authorityOf({ sourceKind: "study_finding" }, "observed").tier, "verified_source");
  assert.equal(authorityOf({ sourceKind: "performance_evidence" }, "observed").tier, "verified_source");
  assert.equal(authorityOf({ sourceKind: "repository_evidence" }, "observed").tier, "verified_source");
  assert.equal(authorityOf({ sourceKind: "user_note" }, "observed").tier, "user_reported");
  assert.equal(authorityOf({ sourceKind: "search_session" }, "derived").tier, "analysis");
  assert.equal(authorityOf({ sourceKind: "analysis_evidence" }, "observed").tier, "analysis");
  assert.equal(authorityOf({ sourceKind: "external_document" }, "observed").tier, "analysis");
  assert.equal(authorityOf({ sourceKind: "agent_inference" }, "inferred").tier, "agent_derived");
  assert.equal(authorityOf({ sourceKind: "unknown" }, "unknown").tier, "unattributed");
  // Epistemic honesty caps:
  const inferred = authorityOf({ sourceKind: "study_finding" }, "inferred");
  assert.equal(inferred.capped, true, "even verified sources are capped when the claim is inference");
  const unknownCapped = authorityOf({ sourceKind: "unknown" }, "observed").capped;
  assert.equal(unknownCapped, true);
});

test("T4: user note with evidence is authoritative; explain exposes the full chain", () => {
  const { engine, dir } = tempEngine("explain");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord({
      scope: "lib",
      kind: "decision",
      subject: "Store choice",
      content: "Use SQLite WAL for the canonical store",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      epistemicClass: "observed",
      confidence: 1.0,
      sourceKind: "user_note",
      evidenceRefs: [{ engine: "external", ref: "note:2026-08-30#store" }],
    });
    const explained = engine.getRecordHistory(record.recordId); // history reachable too
    assert.equal(explained.revisions.length, 1);
    const assessment = engine.explainAuthority(record.recordId);
    assert.equal(assessment.tier, "user_reported");
    assert.equal(assessment.capped, false);
    assert.equal(assessment.basis, "traces to 'user_note'");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T4: migration backfill — pre-1.1 records read as unattributed, not fabricated authority", () => {
  const { engine, dir } = tempEngine("backfill");
  try {
    engine.createScope("lib", "Library");
    // Simulate a pre-1.1.0 row: no sourceKind in provenance JSON.
    const record = engine.addRecord({
      scope: "lib",
      kind: "note",
      subject: "Legacy note",
      content: "Written before the authority model",
      actor: { kind: "human", name: "kim" },
      method: "asserted",
      epistemicClass: "inferred",
      confidence: 0.5,
    });
    engine.store
      .ensureOpen()
      .prepare("UPDATE memory_records SET provenance_json = json_remove(provenance_json, '$.sourceKind') WHERE record_id = ?")
      .run(record.recordId);
    // Re-read: defensively normalized to 'unknown' and capped.
    const reread = engine.getRecord(record.recordId);
    assert.equal(reread.provenance.sourceKind, "unknown");
    const assessment = engine.explainAuthority(record.recordId);
    assert.equal(assessment.tier, "unattributed");
    assert.equal(assessment.capped, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T4: revision authority — revising keeps provenance, overrides are explicit", () => {
  const { engine, dir } = tempEngine("revise-authority");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord({
      scope: "lib",
      kind: "fact",
      subject: "S",
      content: "C1",
      actor: { kind: "human", name: "kim" },
      method: "asserted",
      epistemicClass: "observed",
      confidence: 0.9,
      sourceKind: "user_note",
      evidenceRefs: [{ engine: "external", ref: "note:1" }],
    });
    const revised = engine.reviseRecord(record.recordId, {
      content: "C2",
      actor: { kind: "human", name: "editor" },
      method: "copy edit",
      reason: "typo fix without changing meaning",
    });
    assert.equal(revised.provenance.sourceKind, "user_note", "source kind preserved unless explicitly overridden");
    assert.equal(revised.provenance.actor.name, "editor");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

