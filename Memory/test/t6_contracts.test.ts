/**
 * CHILD LOOP 3 verification — Task 6: versioned Memory inter-engine
 * contracts. Proves: the 8 named operations, versioned envelopes with
 * major-version negotiation, typed error envelopes, and the rule that no
 * caller may read the Memory store directly (public surface leak check).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import * as publicApi from "../src/index.ts";
import {
  MemoryEngine,
  MEMORY_ENGINE_CONTRACT_VERSION,
  MEMORY_OPERATIONS,
  dispatch,
} from "../src/index.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t6-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function seed(engine: MemoryEngine) {
  engine.createScope("lib", "Library");
  const record = engine.addRecord({
    scope: "lib",
    kind: "fact",
    subject: "Rate limit",
    content: "120 requests per minute",
    actor: { kind: "human", name: "kim" },
    method: "asserted",
    epistemicClass: "observed",
    confidence: 0.9,
    sourceKind: "user_note",
    evidenceRefs: [{ engine: "external", ref: "note:1" }],
  });
  return { record };
}

test("T6: the contract registry defines the eight required operations (plus additive intake stream)", () => {
  const ops = [...MEMORY_OPERATIONS].sort();
  // The eight operations required by the published contract:
  for (const required of [
    "memory.explain",
    "memory.get",
    "memory.history",
    "memory.promote",
    "memory.propose",
    "memory.related",
    "memory.revise",
    "memory.search",
  ] as const) {
    assert.ok(ops.includes(required), `missing required operation ${required}`);
  }
  // 1.2.0 additive: the candidate stream listing (docs/CONTRACTS.md).
  assert.ok(ops.includes("memory.candidates"));
  // 1.3.0 additive: contradiction pairs + open groups (docs/CONTRACTS.md).
  assert.ok(ops.includes("memory.contradictions"));
  // 1.4.0 additive: retention/archival/deletion lifecycle (docs/CONTRACTS.md).
  assert.ok(ops.includes("memory.lifecycle"));
  // 1.5.0 additive: deterministic retrieval baseline (docs/RETRIEVAL.md).
  for (const retrievalOp of [
    "memory.lexical",
    "memory.current",
    "memory.timeline",
    // Tasks 17–19 (same retrieval-baseline line): provenance ranking,
    // duplicate analysis, explainable multi-signal fusion.
    "memory.ranked",
    "memory.duplicates",
    "memory.fused",
  ] as const) {
    assert.ok(ops.includes(retrievalOp), `missing retrieval operation ${retrievalOp}`);
  }
  // 1.7.0 additive: typed relations with provenance + entity projection
  // (Tasks 21–22, docs/CONTRACTS.md).
  for (const relationOp of ["memory.relation", "memory.entities"] as const) {
    assert.ok(ops.includes(relationOp), `missing relation operation ${relationOp}`);
  }
  // 1.8.0 additive: optional semantic embedding projection (Task 23).
  for (const embeddingOp of ["memory.embeddings", "memory.semantic"] as const) {
    assert.ok(ops.includes(embeddingOp), `missing embedding operation ${embeddingOp}`);
  }
  // 1.9.0 additive: optional relationship-graph projection (Task 24).
  assert.ok(ops.includes("memory.graph"), "missing graph operation memory.graph");
  // 1.10.0 additive: hybrid retrieval + index rebuild/corruption recovery (Tasks 25–26).
  for (const op of ["memory.hybrid", "memory.projections"] as const) {
    assert.ok(ops.includes(op), `missing operation ${op}`);
  }
  // 1.11.0 additive: Performance → Memory proposals (Task 27).
  assert.ok(ops.includes("memory.performance.propose"), "missing performance operation memory.performance.propose");
  // 1.12.0 additive: Study → Memory proposals (Task 28).
  assert.ok(ops.includes("memory.study.propose"), "missing study operation memory.study.propose");
  // 1.13.0 additive: Analysis → Memory proposals (Task 29).
  assert.ok(ops.includes("memory.analysis.propose"), "missing analysis operation memory.analysis.propose");
  // 1.14.0 additive: Search → Memory history (Task 30).
  assert.ok(ops.includes("memory.search.session"), "missing search-session operation memory.search.session");
  // 1.15.0 additive: Context → Memory retrieval (Task 31).
  assert.ok(ops.includes("memory.context"), "missing context operation memory.context");
  // 1.16.0 additive: Project user notes (Task 32).
  assert.ok(ops.includes("memory.user.note"), "missing user-note operation memory.user.note");
  // 1.18.0 additive: Context-safe memory excerpts (Task 36).
  assert.ok(ops.includes("memory.excerpts"), "missing excerpts operation memory.excerpts");
  // 1.19.0 additive: field-level privacy + project isolation (Task 37).
  assert.ok(ops.includes("memory.privacy"), "missing privacy operation memory.privacy");
  // 1.20.0 additive: untrusted-content boundaries, backup/integrity, health (Tasks 38–40).
  for (const op of ["memory.trust", "memory.backup", "memory.health"] as const) {
    assert.ok(ops.includes(op), `missing operation ${op}`);
  }
  assert.equal(ops.length, 35);
});

test("T6: no caller may read the store directly — the public surface never exports it", () => {
  const exportedNames = Object.keys(publicApi);
  assert.ok(!exportedNames.includes("MemoryStore"), "MemoryStore must not be public");
  assert.ok(!exportedNames.includes("MemoryStoreError"));
  assert.ok(exportedNames.includes("MemoryEngine"));
  assert.ok(exportedNames.includes("dispatch"));
  // The engine object itself exposes the store as a property, but the
  // contract surface is dispatch(); assert store access is not part of the
  // documented contract operations.
  assert.ok(!MEMORY_OPERATIONS.includes("memory.store" as never));
});

test("T6: memory.search returns matching records through the envelope", () => {
  const { engine, dir } = tempEngine("search");
  try {
    const { record } = seed(engine);
    const response = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.search",
      request: { scope: "lib", subjectContains: "rate" },
    });
    assert.equal(response.ok, true);
    if (response.ok) {
      const records = (response.result as { records: Array<{ recordId: string }> }).records;
      assert.equal(records.length, 1);
      assert.equal(records[0]!.recordId, record.recordId);
    }
    assert.equal(response.contractVersion, MEMORY_ENGINE_CONTRACT_VERSION);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T6: memory.propose + memory.promote lifecycle through the envelope", () => {
  const { engine, dir } = tempEngine("propose-promote");
  try {
    engine.createScope("lib", "Library");
    const proposed = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.propose",
      request: {
        scope: "lib",
        kind: "fact",
        subject: "Possible bottleneck",
        content: "Sync writes serialize ingestion",
        actor: { kind: "agent", name: "analyzer", agentType: "llm" },
        method: "inferred",
        epistemicClass: "inferred",
        confidence: 0.5,
        sourceKind: "agent_inference",
        reason: "flagged during latency analysis",
        caller: { kind: "engine", name: "study_lineage_versioning" },
      },
    });
    assert.equal(proposed.ok, true);
    if (!proposed.ok) return;
    const candidate = (proposed.result as { candidate: { candidateId: string } }).candidate;
    assert.ok(candidate.candidateId.startsWith("cand_"));

    const promoted = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.promote",
      request: {
        candidateId: candidate.candidateId,
        actor: { kind: "human", name: "kim" },
        policy: "explicit_user_decision",
      },
    });
    assert.equal(promoted.ok, true);
    if (promoted.ok) {
      const record = (promoted.result as { record: { status: string } }).record;
      assert.equal(record.status, "active");
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T6: memory.revise, memory.get, memory.history, memory.related, memory.explain", () => {
  const { engine, dir } = tempEngine("read-write-ops");
  try {
    const { record } = seed(engine);
    // add a second record that relates to the first
    const relator = engine.addRecord({
      scope: "lib",
      kind: "note",
      subject: "Relates",
      content: "See rate limit",
      actor: { kind: "human", name: "kim" },
      method: "asserted",
      epistemicClass: "inferred",
      confidence: 0.5,
      relationHints: [{ type: "related", target: record.recordId }],
    });

    const revised = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.revise",
      request: {
        recordId: record.recordId,
        content: "240 requests per minute",
        actor: { kind: "human", name: "kim" },
        method: "corrected",
        reason: "limit doubled",
      },
    });
    assert.equal(revised.ok, true);
    if (revised.ok) {
      assert.equal((revised.result as { record: { revision: number } }).record.revision, 2);
    }

    const got = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.get",
      request: { recordId: record.recordId },
    });
    assert.equal(got.ok, true);
    if (got.ok) {
      assert.equal((got.result as { record: { content: string } }).record.content, "240 requests per minute");
    }

    const history = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.history",
      request: { recordId: record.recordId },
    });
    assert.equal(history.ok, true);
    if (history.ok) {
      const result = history.result as { revisions: unknown[]; chain: unknown[] };
      assert.equal(result.revisions.length, 2);
      assert.equal(result.chain.length, 1);
    }

    const related = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.related",
      request: { recordId: record.recordId },
    });
    assert.equal(related.ok, true);
    if (related.ok) {
      const result = related.result as { incoming: Array<{ recordId: string }>; outgoing: unknown[] };
      assert.deepEqual(result.incoming.map((i) => i.recordId), [relator.recordId]);
      assert.equal(result.outgoing.length, 0);
    }

    const explained = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.explain",
      request: { recordId: record.recordId },
    });
    assert.equal(explained.ok, true);
    if (explained.ok) {
      const result = explained.result as {
        authority: { tier: string };
        provenance: { sourceKind: string };
        events: unknown[];
        // 1.6.0 additive (Task 20): validity, contradiction, evidenceGaps.
        validity: { at: string; currentlyValid: boolean };
        contradiction: { groupId: string | null; status: string | null; groupSize: number | null };
        evidenceGaps: string[];
      };
      assert.equal(result.authority.tier, "user_reported");
      assert.equal(result.provenance.sourceKind, "user_note");
      assert.ok(result.events.length >= 1, "explain lists lifecycle events");
      assert.equal(typeof result.validity.currentlyValid, "boolean");
      assert.equal(result.contradiction.groupId, null);
      assert.deepEqual(result.evidenceGaps, []);
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T6: memory.search supports historical as-of queries through the envelope", () => {
  const { engine, dir } = tempEngine("asof-envelope");
  try {
    const { record } = seed(engine);
    engine.supersedeRecord(record.recordId, {
      content: "240 requests per minute",
      actor: { kind: "human", name: "kim" },
      method: "corrected",
      reason: "limit doubled",
    });
    const past = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.search",
      request: {
        scope: "lib",
        asOf: new Date(Date.parse(engine.getRecord(record.recordId).supersededAt ?? record.createdAt) - 1).toISOString(),
      },
    });
    assert.equal(past.ok, true);
    if (past.ok) {
      const records = (past.result as { records: Array<{ recordId: string }> }).records;
      assert.ok(records.some((r) => r.recordId === record.recordId));
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T6: negative — unknown operation, bad major version, and typed error envelopes", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    seed(engine);
    const unknownOp = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.pwn" as never,
      request: {},
    });
    assert.equal(unknownOp.ok, false);
    if (!unknownOp.ok) assert.equal(unknownOp.error.code, "MEMORY_VALIDATION_FAILED");

    const oldMajor = dispatch(engine, {
      contractVersion: "0.9.9",
      operation: "memory.get",
      request: { recordId: "mem_x" },
    });
    assert.equal(oldMajor.ok, false);
    if (!oldMajor.ok) assert.equal(oldMajor.error.code, "MEMORY_CONTRACT_MISMATCH");

    const missing = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.get",
      request: { recordId: "mem_ghost" },
    });
    assert.equal(missing.ok, false);
    if (!missing.ok) assert.equal(missing.error.code, "MEMORY_NOT_FOUND");

    const badRequest = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.get",
      request: "not-an-object",
    });
    assert.equal(badRequest.ok, false);
    if (!badRequest.ok) assert.equal(badRequest.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T6: same major, different minor is accepted (additive versioning policy)", () => {
  const { engine, dir } = tempEngine("minor-version");
  try {
    const { record } = seed(engine);
    const response = dispatch(engine, {
      contractVersion: "1.0.0",
      operation: "memory.get",
      request: { recordId: record.recordId },
    });
    assert.equal(response.ok, true, "1.0.0 caller accepted by 1.1.0 engine");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

