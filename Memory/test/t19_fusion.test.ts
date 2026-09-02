/**
 * CHILD LOOP 3 verification — Task 19: explainable multi-signal fusion.
 * Proves: lexical, structured, temporal, provenance and relation signals are
 * combined with VISIBLE per-signal contributions (value/weight/contribution),
 * the result is never an opaque score, structured filters bias the fusion,
 * temporal currency and provenance authority shape rankings, relation/
 * corroboration links contribute, and negative cases are typed.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t19-${name}-`));
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

test("T19: fusion exposes every per-signal contribution, never an opaque score", () => {
  const { engine, dir } = tempEngine("explainable");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "Public api allows 120 requests per minute"));
    const result = engine.fusedSearch("rate limit", { scope: "lib" });
    assert.equal(result.hits.length, 1);
    const hit = result.hits[0]!;
    // The full signal set is present and each has value + weight + contribution.
    for (const name of ["lexical", "structured", "temporal", "provenance", "relation"] as const) {
      const s = hit.signals[name];
      assert.ok(s !== undefined, `signal ${name} present`);
      assert.ok(s.value >= 0 && s.value <= 1, `${name}.value in [0,1]`);
      assert.ok(s.weight > 0, `${name}.weight > 0`);
      assert.ok(Math.abs(s.contribution - s.value * s.weight) < 1e-9, `${name}.contribution = value*weight`);
    }
    // Total is the sum of contributions (explainable).
    const sum = Object.values(hit.signals).reduce((acc, s) => acc + s.contribution, 0);
    assert.ok(Math.abs(sum - hit.total) < 1e-9, "total equals the sum of contributions");
    // Deterministic explanation text accompanies the hit.
    assert.ok(hit.explanation.length > 0);
    assert.ok(result.weights.lexical > 0 && result.weights.provenance > 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T19: structured filters bias the fusion — exact subject and tag lifts the match", () => {
  const { engine, dir } = tempEngine("structured");
  try {
    engine.createScope("lib", "Library");
    const tagged = engine.addRecord(
      rec("lib", "Rate limit", "120 requests per minute", { tags: ["api", "limits"] }),
    );
    const plain = engine.addRecord(rec("lib", "Requests note", "mention of requests in passing"));

    // With an explicit tag filter, the tagged record's structured signal jumps.
    const filtered = engine.fusedSearch("requests", { scope: "lib", tag: "api" });
    const taggedHit = filtered.hits.find((h) => h.record.recordId === tagged.recordId)!;
    assert.ok(taggedHit !== undefined);
    assert.ok(taggedHit.signals.structured.value > 0, "tag match raises the structured signal");
    const plainHit = filtered.hits.find((h) => h.record.recordId === plain.recordId)!;
    if (plainHit !== undefined) {
      assert.ok(taggedHit.signals.structured.value > plainHit.signals.structured.value);
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T19: temporal currency and provenance authority shape the ranking", () => {
  const { engine, dir } = tempEngine("temporal-provenance");
  try {
    engine.createScope("lib", "Library");
    const current = engine.addRecord(
      rec("lib", "Deploy window", "deploy on Tuesday morning", { sourceKind: "study_finding" }),
    );
    const retired = engine.addRecord(
      rec("lib", "Deploy window", "deploy on Friday evening", {
        sourceKind: "agent_inference",
        epistemicClass: "inferred",
        confidence: 0.3,
        evidenceRefs: [],
      }),
    );
    // Superseding RETIRES the old record (status superseded) while creating an
    // active successor.
    const successor = engine.supersedeRecord(retired.recordId, {
      content: "deploy on Tuesday morning (updated)",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "schedule change",
    });

    const result = engine.fusedSearch("deploy", { scope: "lib" });
    const currentHit = result.hits.find((h) => h.record.recordId === current.recordId)!;
    const retiredHit = result.hits.find((h) => h.record.recordId === retired.recordId)!;
    const successorHit = result.hits.find((h) => h.record.recordId === successor.recordId)!;
    assert.ok(currentHit !== undefined);
    assert.ok(retiredHit !== undefined);
    assert.ok(successorHit !== undefined);
    // The active, high-authority record outranks the retired predecessor.
    assert.ok(currentHit.total > retiredHit.total);
    assert.ok(successorHit.total > retiredHit.total, "the active successor outranks the retired record");
    assert.equal(currentHit.signals.temporal.value, 1, "active record is current");
    assert.ok(retiredHit.signals.temporal.value < 1, "superseded record has reduced currency");
    assert.ok(successorHit.signals.temporal.value > retiredHit.signals.temporal.value);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T19: relation/corroboration links contribute to the relation signal", () => {
  const { engine, dir } = tempEngine("relation");
  try {
    engine.createScope("lib", "Library");
    const hub = engine.addRecord(
      rec("lib", "Rate limit", "api rate limit policy", {
        relationHints: [{ type: "related", target: "engine:context:pack-1" }],
      }),
    );
    const spoke = engine.addRecord(
      rec("lib", "Rate limit", "api rate limit policy (dup)",
        { relationHints: [{ type: "supports", target: hub.recordId }] }),
    );
    const result = engine.fusedSearch("rate limit", { scope: "lib" });
    const hubHit = result.hits.find((h) => h.record.recordId === hub.recordId)!;
    const spokeHit = result.hits.find((h) => h.record.recordId === spoke.recordId)!;
    assert.ok(hubHit !== undefined);
    // spoke targets hub, so hub has an incoming link → its relation signal > 0.
    assert.ok(hubHit.signals.relation.value > 0, "incoming relation hint raises the relation signal");
    assert.ok(spokeHit.signals.relation.value > 0, "outgoing relation hint raises the relation signal");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T19: negative — empty query, unknown scope, and custom weights are handled", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Island", "island token"));
    assert.throws(() => engine.fusedSearch("   "), (err: unknown) => err instanceof ValidationError);
    assert.throws(() => engine.fusedSearch("!!!"), (err: unknown) => err instanceof ValidationError);
    assert.throws(
      () => engine.fusedSearch("island", { scope: "nope" }),
      (err: unknown) => err instanceof Error,
    );
    // Invalid `at` is a typed validation error, not silent mis-fusion.
    assert.throws(
      () => engine.fusedSearch("island", { at: "garbage" }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Custom weights are honored (provenance dominates; others zeroed).
    const weighted = engine.fusedSearch("island", {
      scope: "lib",
      weights: { lexical: 0, structured: 0, temporal: 0, provenance: 1, relation: 0 },
    });
    assert.equal(weighted.hits.length, 1);
    assert.ok(Math.abs(weighted.hits[0]!.total - weighted.hits[0]!.signals.provenance.contribution) < 1e-9);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});