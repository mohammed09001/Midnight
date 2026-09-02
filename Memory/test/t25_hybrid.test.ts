/**
 * CHILD LOOP 1 verification — Task 25: hybrid lexical + semantic + relation
 * retrieval. Proves: the deterministic baseline always runs and explains
 * itself; the OPTIONAL semantic signal is fused ONLY when an embedding
 * provider is configured AND the projection is built (never required, never
 * silently assumed); the retrieval PATH explains which signals participated;
 * relation signal always participates; typed negatives; determinism.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, localHashProvider } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t25-${name}-`));
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

test("T25: hybrid degrades to the deterministic baseline when no provider is configured", () => {
  const { engine, dir } = tempEngine("no-provider");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Retry backoff", "exponential backoff with retry"));
    // No provider set at all.
    const result = engine.hybridSearch("backoff", { scope: "lib" });
    assert.equal(result.hits.length, 1);
    const hit = result.hits[0]!;
    // Semantic explicitly unavailable with a reason — not silently assumed.
    assert.equal(hit.signals.semantic.available, false);
    assert.ok(hit.signals.semantic.reason !== undefined);
    assert.equal(hit.signals.lexical.available, true);
    assert.equal(hit.signals.relation.available, true);
    // The retrieval path explains the degraded semantic signal.
    assert.equal(result.path.semantic.available, false);
    assert.ok(!result.path.signals.includes("semantic"), "semantic is absent from the active signal path");
    assert.ok(result.path.signals.includes("lexical"));
    assert.ok(result.path.signals.includes("relation"));
    assert.equal(result.path.relation.source, "relation_hints");
    // Deterministic signals still produced a total.
    assert.ok(hit.total > 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T25: hybrid semantic unavailable when the projection is not built; available after build", () => {
  const { engine, dir } = tempEngine("semantic-availability");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Retry backoff", "exponential backoff with retry"));
    engine.setEmbeddingProvider(localHashProvider);
    // Provider configured but projection not built → semantic unavailable.
    const before = engine.hybridSearch("backoff", { scope: "lib" });
    assert.equal(before.path.semantic.available, false);
    assert.ok(before.path.semantic.reason!.includes("not built"));
    assert.equal(before.hits[0]!.signals.semantic.available, false);
    // Build the projection → semantic fuses.
    engine.buildEmbeddingProjection("lib");
    const after = engine.hybridSearch("backoff", { scope: "lib" });
    assert.equal(after.path.semantic.available, true);
    assert.equal(after.path.semantic.provider, "local-hash");
    assert.equal(after.path.semantic.model, "feature-hash-v1");
    assert.equal(after.hits[0]!.signals.semantic.available, true);
    assert.equal(after.hits[0]!.signals.semantic.provider, "local-hash");
    assert.ok(after.hits[0]!.signals.semantic.value > 0, "semantic similarity is positive for a matching record");
    assert.ok(after.path.signals.includes("semantic"));
    // Contribution is value * weight.
    const sem = after.hits[0]!.signals.semantic;
    assert.ok(Math.abs(sem.contribution - sem.value * sem.weight) < 1e-9);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T25: every hit exposes all six signal contributions, never an opaque score", () => {
  const { engine, dir } = tempEngine("explainable");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute", {
      relationHints: [{ type: "applies_to", target: "entity:component:gateway" }],
    }));
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");
    const result = engine.hybridSearch("rate", { scope: "lib" });
    const hit = result.hits[0]!;
    for (const name of ["lexical", "structured", "temporal", "provenance", "relation", "semantic"] as const) {
      const s = hit.signals[name];
      assert.ok(s !== undefined, `signal ${name} present`);
      assert.ok(s.weight > 0, `${name} weight > 0`);
      assert.ok(Math.abs(s.contribution - s.value * s.weight) < 1e-9, `${name} contribution = value*weight`);
    }
    // Total is the sum of contributions.
    const sum = Object.values(hit.signals).reduce((acc, s) => acc + s.contribution, 0);
    assert.ok(Math.abs(sum - hit.total) < 1e-9);
    assert.ok(hit.explanation.length > 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T25: relation signal participates from canonical relation hints", () => {
  const { engine, dir } = tempEngine("relation");
  try {
    engine.createScope("lib", "Library");
    const hub = engine.addRecord(rec("lib", "Rate limit", "api rate limit"));
    const spoke = engine.addRecord(rec("lib", "Rate limit note", "api rate limit (dup)", {
      relationHints: [{ type: "supports", target: hub.recordId }],
    }));
    const result = engine.hybridSearch("rate", { scope: "lib" });
    const hubHit = result.hits.find((h) => h.record.recordId === hub.recordId)!;
    const spokeHit = result.hits.find((h) => h.record.recordId === spoke.recordId)!;
    assert.ok(hubHit.signals.relation.available);
    assert.ok(spokeHit.signals.relation.available);
    // The hub has an incoming link, so its relation signal is non-zero.
    assert.ok(hubHit.signals.relation.value > 0, "incoming relation hint raises the relation signal");
    assert.equal(result.path.relation.available, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T25: negative — empty query, invalid at, and determinism", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Island", "island token"));
    assert.throws(() => engine.hybridSearch("   "), (err: unknown) => err instanceof ValidationError);
    assert.throws(() => engine.hybridSearch("!!!"), (err: unknown) => err instanceof ValidationError);
    assert.throws(
      () => engine.hybridSearch("island", { at: "garbage" }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Determinism without a provider (deterministic baseline only).
    const r1 = engine.hybridSearch("island", { scope: "lib" });
    const r2 = engine.hybridSearch("island", { scope: "lib" });
    assert.deepEqual(
      r1.hits.map((h) => [h.record.recordId, h.total.toFixed(6)]),
      r2.hits.map((h) => [h.record.recordId, h.total.toFixed(6)]),
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});