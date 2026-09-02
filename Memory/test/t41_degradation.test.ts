/**
 * CHILD LOOP 1 verification — Task 41: graceful degradation.
 *
 * Proves the Task Source Requirement: structured/lexical Memory WORKS when
 * embeddings (absent, failing at runtime, or corrupt), the graph projection,
 * the MCP host, or sibling engines are unavailable. Degradation is explicit
 * (typed MEMORY_EMBEDDINGS_UNAVAILABLE with cause, hybrid path reasons,
 * skippedCorrupt diagnostics) — never silent, never a baseline loss. Recovery
 * (provider healthy again → rebuild) restores the optional projection.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  MemoryEngine,
  localHashProvider,
  dispatch,
  MEMORY_ENGINE_CONTRACT_VERSION,
  type EmbeddingProvider,
} from "../src/index.ts";
import { EmbeddingsUnavailableError } from "../src/contracts/errors.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "src", "cli", "cli.ts");

function tempEngine(name: string): { engine: MemoryEngine; dir: string; storePath: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t41-${name}-`));
  const storePath = join(dir, "memory.db");
  const engine = new MemoryEngine({ storePath });
  engine.open();
  return { engine, dir, storePath };
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

/** A provider that is CONFIGURED but fails at runtime (e.g. network/model). */
function failingProvider(name = "external:flaky"): EmbeddingProvider {
  return {
    name,
    model: "flaky-model",
    version: "1.0.0",
    embed(): Float32Array[] {
      throw new Error("network unreachable");
    },
  };
}

test("T41: structured/lexical Memory works with embeddings absent, graph never built, MCP host absent, and dangling sibling evidence", () => {
  const { engine, dir, storePath } = tempEngine("all-absent");
  try {
    engine.createScope("lib", "Library");
    // Sibling-engine evidence refs that do NOT resolve anywhere: Memory keeps
    // them by reference and retrieval is unaffected when the siblings are down.
    const a = engine.addRecord(rec("lib", "Rate limit", "120 requests per minute", {
      evidenceRefs: [
        { engine: "study_document", ref: "study:does-not-exist" },
        { engine: "analysis", ref: "analysis:also-missing" },
      ],
    }));
    const b = engine.addRecord(rec("lib", "Retry backoff", "exponential backoff with retry", {
      relationHints: [{ type: "applies_to", target: "entity:component:api-gateway" }],
    }));

    // Structured retrieval works.
    const structured = engine.searchRecords({ scope: "lib", exactSubject: "Rate limit" });
    assert.deepEqual(structured.map((r) => r.recordId), [a.recordId]);
    // Lexical retrieval works.
    const lexical = engine.lexicalSearch("backoff", { scope: "lib" });
    assert.equal(lexical.hits.length, 1);
    assert.equal(lexical.hits[0]!.record.recordId, b.recordId);
    // Ranked / fused / hybrid baselines all work without any provider.
    assert.ok(engine.rankedSearch("backoff", { scope: "lib" }).hits.length >= 1);
    assert.ok(engine.fusedSearch("backoff", { scope: "lib" }).hits.length >= 1);
    const hybrid = engine.hybridSearch("backoff", { scope: "lib" });
    assert.equal(hybrid.hits.length, 1);
    assert.equal(hybrid.path.semantic.available, false);
    assert.ok(hybrid.hits[0]!.total > 0);

    // Embeddings report unavailable — a status, not a crash.
    assert.equal(engine.embeddingProjectionStatus("lib").status, "unavailable");

    // Graph projection is on demand: NEVER built, still computable.
    const graph = engine.graphProjection("lib");
    assert.ok(graph.nodeCount >= 2, "records project to graph nodes on demand");

    // The versioned contract surface works without any MCP host.
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.lexical",
      request: { query: "backoff", scope: "lib" },
    });
    assert.equal(envelope.ok, true);

    // The terminal surface works without any MCP host (fresh process, CLI only).
    const stdout = execFileSync(
      process.execPath,
      ["--experimental-strip-types", CLI_PATH, "health", "--store", storePath],
      { encoding: "utf8", env: { ...process.env } },
    );
    const health = JSON.parse(stdout) as { store: { healthy: boolean } };
    assert.equal(health.store.healthy, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T41: failing provider degrades typed — hybrid keeps the deterministic baseline", () => {
  const { engine, dir } = tempEngine("provider-failure");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    // A healthy provider builds the projection once...
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");
    // ...then the provider starts failing at runtime.
    engine.setEmbeddingProvider(failingProvider());

    // Hybrid retrieval DEGRADES — it never loses the lexical baseline.
    const hybrid = engine.hybridSearch("rate", { scope: "lib" });
    assert.equal(hybrid.hits.length, 1);
    const hit = hybrid.hits[0]!;
    assert.equal(hit.signals.semantic.available, false);
    assert.equal(hit.signals.semantic.value, 0);
    assert.ok(hit.signals.semantic.reason!.includes("provider failed"));
    assert.equal(hit.signals.lexical.available, true);
    assert.ok(hit.total > 0);
    assert.equal(hybrid.path.semantic.available, false);
    assert.ok(hybrid.path.semantic.reason!.includes("provider failed"));
    assert.ok(!hybrid.path.signals.includes("semantic"));

    // Build/search fail with the stable typed code, cause preserved.
    try {
      engine.buildEmbeddingProjection("lib");
      assert.fail("buildEmbeddingProjection must throw");
    } catch (err) {
      assert.ok(err instanceof EmbeddingsUnavailableError);
      assert.equal((err as EmbeddingsUnavailableError).code, "MEMORY_EMBEDDINGS_UNAVAILABLE");
      assert.ok((err as Error).message.includes("external:flaky"));
      assert.equal(String((err as { cause?: unknown }).cause), "Error: network unreachable");
    }
    assert.throws(
      () => engine.semanticSearch("rate", { scope: "lib" }),
      (err: unknown) => err instanceof EmbeddingsUnavailableError,
    );

    // Sibling engines see the stable code through the contract envelope, and
    // the degraded hybrid result through the same envelope.
    const semantic = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.semantic",
      request: { query: "rate", scope: "lib" },
    });
    assert.equal(semantic.ok, false);
    if (!semantic.ok) {
      assert.equal(semantic.error.code, "MEMORY_EMBEDDINGS_UNAVAILABLE");
    }
    const hybridEnvelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.hybrid",
      request: { query: "rate", scope: "lib" },
    });
    assert.equal(hybridEnvelope.ok, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T41: failed rebuild leaves the existing projection intact; recovery restores semantic", () => {
  const { engine, dir } = tempEngine("recovery");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));

    // Healthy provider builds the projection.
    engine.setEmbeddingProvider(localHashProvider);
    const built = engine.buildEmbeddingProjection("lib");
    assert.equal(built.status, "built");
    assert.equal(built.recordCount, 1);

    // Provider starts failing: a rebuild attempt fails typed but must NOT
    // corrupt or clear the existing derived projection.
    engine.setEmbeddingProvider(failingProvider());
    assert.throws(
      () => engine.rebuildEmbeddingProjection("lib"),
      (err: unknown) => err instanceof EmbeddingsUnavailableError,
    );
    const status = engine.embeddingProjectionStatus("lib");
    assert.equal(status.status, "built");
    assert.equal(status.provider, "local-hash");
    assert.equal(status.recordCount, 1);
    // Hybrid still answers — degraded semantic, full lexical baseline.
    const degraded = engine.hybridSearch("rate", { scope: "lib" });
    assert.equal(degraded.hits.length, 1);
    assert.equal(degraded.path.semantic.available, false);

    // Recovery: a working provider rebuild restores the semantic signal.
    engine.setEmbeddingProvider(localHashProvider);
    const rebuilt = engine.rebuildEmbeddingProjection("lib");
    assert.equal(rebuilt.status, "built");
    const recovered = engine.semanticSearch("rate", { scope: "lib" });
    assert.equal(recovered.status, "built");
    assert.equal(recovered.hits.length, 1);
    assert.ok(engine.checkProjectionIntegrity("lib").healthy);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T41: provider contract violation (wrong vector count) is typed degradation", () => {
  const { engine, dir } = tempEngine("contract-violation");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    engine.setEmbeddingProvider({
      name: "external:buggy",
      model: "buggy-model",
      version: "1.0.0",
      embed: (texts: string[]) => texts.slice(1).map(() => new Float32Array(4)),
    });
    try {
      engine.buildEmbeddingProjection("lib");
      assert.fail("contract violation must throw");
    } catch (err) {
      assert.ok(err instanceof EmbeddingsUnavailableError);
      assert.ok((err as Error).message.includes("contract"));
    }
    // Lexical Memory is unaffected by the broken optional provider.
    assert.equal(engine.lexicalSearch("rate", { scope: "lib" }).hits.length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T41: corrupt derived vector row is skipped and reported, never fatal; rebuild restores it", () => {
  const { engine, dir } = tempEngine("corrupt-row");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    const b = engine.addRecord(rec("lib", "Retry backoff", "exponential backoff with retry"));
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");

    // Corrupt ONE derived vector row (derived state only — canonical records
    // are untouched, and retrieval truth cannot be corrupted by it).
    engine.store
      .ensureOpen()
      .prepare("UPDATE memory_embeddings SET vector_json = '{not json' WHERE record_id = ?")
      .run(a.recordId);

    // Semantic search skips the corrupt row and reports it.
    const semantic = engine.semanticSearch("rate", { scope: "lib" });
    assert.equal(semantic.status, "built");
    assert.equal(semantic.diagnostics.skippedCorrupt, 1);
    assert.deepEqual(semantic.hits.map((h) => h.record.recordId), [b.recordId]);

    // Hybrid keeps BOTH records reachable: the corrupt row only degrades that
    // record's semantic signal; lexical still carries it.
    const hybridA = engine.hybridSearch("rate", { scope: "lib" });
    assert.equal(hybridA.hits.length, 1);
    const aHit = hybridA.hits[0]!;
    assert.equal(aHit.record.recordId, a.recordId);
    assert.equal(aHit.signals.semantic.available, false);
    assert.ok(aHit.signals.semantic.reason!.includes("corrupt"));
    const hybridB = engine.hybridSearch("backoff", { scope: "lib" });
    assert.equal(hybridB.hits.length, 1);
    assert.equal(hybridB.hits[0]!.signals.semantic.available, true);

    // Recovery: the next rebuild restores the row from canonical records.
    engine.rebuildEmbeddingProjection("lib");
    const restored = engine.semanticSearch("rate", { scope: "lib" });
    assert.notEqual(restored.diagnostics.skippedCorrupt, 1);
    assert.ok(restored.hits.some((h) => h.record.recordId === a.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
