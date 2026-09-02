/**
 * CHILD LOOP 1 verification — Task 23: optional semantic embedding projection.
 * Proves: Memory functions WITHOUT a provider (unavailable status, typed
 * errors); provider-neutral interface behind which any provider plugs in;
 * the privacy gate (sensitive records excluded unless explicitly included,
 * tombstoned never embedded); model/version recorded with rebuild detection;
 * complete rebuild with the observability event; cosine semantic search;
 * determinism; and persistence across restart.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, localHashProvider } from "../src/index.ts";
import { EmbeddingsNotBuiltError, EmbeddingsUnavailableError, ValidationError } from "../src/contracts/errors.ts";
import { cosineSimilarity } from "../src/engine/embeddings.ts";
import type { EmbeddingProvider } from "../src/index.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t23-${name}-`));
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

test("T23: Memory functions WITHOUT a provider — unavailable status and typed errors", () => {
  const { engine, dir } = tempEngine("no-provider");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    // Status is available (not an error) and reports unavailable.
    const status = engine.embeddingProjectionStatus("lib");
    assert.equal(status.status, "unavailable");
    assert.equal(status.scopeId, engine.getScope("lib").scopeId);
    // Semantic operations are typed errors, never silent fallbacks.
    assert.throws(
      () => engine.buildEmbeddingProjection("lib"),
      (err: unknown) => err instanceof EmbeddingsUnavailableError,
    );
    assert.throws(
      () => engine.semanticSearch("rate limit", { scope: "lib" }),
      (err: unknown) => err instanceof EmbeddingsUnavailableError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T23: provider-neutral interface — the built-in deterministic provider satisfies it", () => {
  const { engine, dir } = tempEngine("provider");
  try {
    engine.createScope("lib", "Library");
    engine.setEmbeddingProvider(localHashProvider);
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    const projection = engine.buildEmbeddingProjection("lib");
    assert.equal(projection.status, "built");
    assert.equal(projection.provider, "local-hash");
    assert.equal(projection.model, "feature-hash-v1");
    assert.ok(projection.vectorDim !== undefined && projection.vectorDim > 0);
    assert.equal(projection.recordCount, 1);
    // Vectors are finite, normalized, fixed-dimension.
    const vector = projection.embeddings[0]!.vector;
    assert.equal(vector.length, projection.vectorDim);
    const norm = Math.sqrt(Array.from(vector).reduce((s, x) => s + x * x, 0));
    assert.ok(Math.abs(norm - 1) < 1e-6, "vectors are L2-normalized");
    // A custom provider (different model) is recorded separately.
    const custom: EmbeddingProvider = {
      name: "test-provider",
      model: "my-model",
      version: "9.9.9",
      embed: (texts) => texts.map(() => new Float32Array([1, 0, 0])),
    };
    engine.setEmbeddingProvider(custom);
    const rebuilt = engine.rebuildEmbeddingProjection("lib");
    assert.equal(rebuilt.provider, "test-provider");
    assert.equal(rebuilt.model, "my-model");
    assert.equal(rebuilt.version, "9.9.9");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T23: privacy gate — sensitive records are excluded unless explicitly included", () => {
  const { engine, dir } = tempEngine("privacy");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Public fact", "rate limit is 120"));
    engine.addRecord(rec("lib", "Sensitive note", "sensitive internal detail", { privacyClass: "sensitive" }));
    engine.setEmbeddingProvider(localHashProvider);
    // Default gate: sensitive excluded.
    const gated = engine.buildEmbeddingProjection("lib");
    assert.equal(gated.recordCount, 1);
    assert.equal(gated.skippedPrivacy, 1);
    assert.ok(!gated.embeddings.some((e) => e.privacyClass === "sensitive"));
    // Explicit opt-in: sensitive included (privacy gate opened).
    const opened = engine.rebuildEmbeddingProjection("lib", { includeSensitive: true });
    assert.equal(opened.recordCount, 2);
    assert.equal(opened.skippedPrivacy, 0);
    // Tombstoned content is never embedded regardless of gate.
    const doomed = engine.addRecord(rec("lib", "Doomed", "scrubbed content"));
    engine.deleteRecord(doomed.recordId, { actor: { kind: "human", name: "kim" }, reason: "scrub" });
    const afterTombstone = engine.rebuildEmbeddingProjection("lib", { includeSensitive: true });
    assert.ok(!afterTombstone.embeddings.some((e) => e.recordId === doomed.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T23: model/version recorded — status surfaces rebuildRecommended after a model change", () => {
  const { engine, dir } = tempEngine("model-version");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "alpha content"));
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");
    const built = engine.embeddingProjectionStatus("lib");
    assert.equal(built.status, "built");
    assert.equal(built.model, "feature-hash-v1");
    assert.equal(built.rebuildRecommended, false);
    // Change the model → status flags a rebuild.
    const next: EmbeddingProvider = {
      name: "local-hash",
      model: "feature-hash-v2",
      version: "2.0.0",
      embed: localHashProvider.embed,
    };
    engine.setEmbeddingProvider(next);
    const stale = engine.embeddingProjectionStatus("lib");
    assert.equal(stale.rebuildRecommended, true);
    // Rebuild resolves it.
    engine.rebuildEmbeddingProjection("lib");
    assert.equal(engine.embeddingProjectionStatus("lib").rebuildRecommended, false);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T23: semantic search ranks by cosine; not-built and bad query are typed errors", () => {
  const { engine, dir } = tempEngine("semantic");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Retry backoff", "exponential backoff with retry"));
    engine.addRecord(rec("lib", "Caching", "cache stamps are rebuildable"));
    engine.setEmbeddingProvider(localHashProvider);
    // Not built yet → typed error.
    assert.throws(
      () => engine.semanticSearch("backoff", { scope: "lib" }),
      (err: unknown) => err instanceof EmbeddingsNotBuiltError,
    );
    engine.buildEmbeddingProjection("lib");
    const result = engine.semanticSearch("backoff retry", { scope: "lib" });
    assert.equal(result.status, "built");
    assert.ok(result.hits.length >= 1);
    const top = result.hits[0]!;
    assert.equal(top.record.subject, "Retry backoff");
    assert.ok(top.score >= 0, "cosine score reported");
    // Deterministic: same query → same ranking.
    const again = engine.semanticSearch("backoff retry", { scope: "lib" });
    assert.deepEqual(
      again.hits.map((h) => [h.record.recordId, h.score.toFixed(6)]),
      result.hits.map((h) => [h.record.recordId, h.score.toFixed(6)]),
    );
    // Empty query is a validation error.
    assert.throws(
      () => engine.semanticSearch("   ", { scope: "lib" }),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T23: pure matcher — cosine similarity bounds and identity", () => {
  const a = new Float32Array([1, 0, 0]);
  const b = new Float32Array([0, 1, 0]);
  const c = new Float32Array([1, 1, 0]);
  assert.ok(Math.abs(cosineSimilarity(a, a) - 1) < 1e-9);
  assert.ok(Math.abs(cosineSimilarity(a, b) - 0) < 1e-9);
  assert.ok(Math.abs(cosineSimilarity(a, c) - 1 / Math.sqrt(2)) < 1e-9);
  assert.ok(Math.abs(cosineSimilarity(new Float32Array(0), new Float32Array(0))) < 1e-9);
});

test("T23: projection survives restart and is fully rebuildable", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t23-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");
    assert.ok(engine.listEvents(20).some((e) => e.type === "memory.embeddings.projection.built"));
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      engine.setEmbeddingProvider(localHashProvider);
      const status = engine.embeddingProjectionStatus("lib");
      assert.equal(status.status, "built");
      assert.equal(status.model, "feature-hash-v1");
      const hits = engine.semanticSearch("rate limit", { scope: "lib" });
      assert.equal(hits.hits.length, 1);
      // Rebuild path emits the explicit observability event.
      engine.rebuildEmbeddingProjection("lib");
      assert.ok(engine.listEvents(20).some((e) => e.type === "memory.embeddings.projection.rebuilt"));
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});