/**
 * CHILD LOOP 2 verification — Task 26: index rebuild and corruption recovery.
 * Proves: every derived projection (lexical/embedding/graph/entity) is
 * rebuildable from canonical records; CORRUPTION in a stored projection is
 * detected by the integrity check; `repairProjections` rebuilds only the
 * corrupted ones; and a corrupted projection NEVER corrupts Memory truth
 * (canonical records stay byte-identical through corruption + repair).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, localHashProvider } from "../src/index.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t26-${name}-`));
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

test("T26: integrity check reports healthy projections on a consistent store", () => {
  const { engine, dir } = tempEngine("healthy");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");

    const report = engine.checkProjectionIntegrity("lib");
    assert.equal(report.healthy, true);
    assert.equal(report.scopeId, engine.getScope("lib").scopeId);
    const byName = new Map(report.projections.map((p) => [p.name, p.status]));
    assert.equal(byName.get("lexical"), "ok");
    assert.equal(byName.get("embedding"), "ok");
    // On-demand projections have no stored state to corrupt.
    assert.equal(byName.get("graph"), "ok");
    assert.equal(byName.get("entity"), "ok");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T26: corrupted embedding projection is detected and repaired WITHOUT touching canonical truth", () => {
  const { engine, dir } = tempEngine("embedding-corruption");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    const canonicalHash = engine.getRecord(a.recordId).contentHash;
    engine.setEmbeddingProvider(localHashProvider);
    engine.buildEmbeddingProjection("lib");
    assert.equal(engine.checkProjectionIntegrity("lib").healthy, true);

    // Corrupt the derived embedding table: drop the record's embedding row.
    engine.store.ensureOpen().prepare("DELETE FROM memory_embeddings WHERE record_id = ?").run(a.recordId);

    // Detection: integrity reports corrupted; canonical record is untouched.
    const corrupt = engine.checkProjectionIntegrity("lib");
    assert.equal(corrupt.healthy, false);
    const embedding = corrupt.projections.find((p) => p.name === "embedding")!;
    assert.equal(embedding.status, "corrupted");
    assert.equal(engine.getRecord(a.recordId).contentHash, canonicalHash, "canonical truth is NEVER corrupted");

    // Repair rebuilds only the embedding projection.
    const repair = engine.repairProjections({ scope: "lib" });
    assert.deepEqual(repair.repaired, ["embedding"]);
    assert.equal(repair.report.healthy, true);
    assert.equal(engine.getRecord(a.recordId).contentHash, canonicalHash);
    // Semantic search works again over the repaired projection.
    const hits = engine.semanticSearch("rate", { scope: "lib" });
    assert.ok(hits.hits.some((h) => h.record.recordId === a.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T26: corrupted lexical index is detected, repaired, and search recovers", () => {
  const { engine, dir } = tempEngine("lexical-corruption");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Doomed", "corruption-token unique"));
    assert.equal(engine.lexicalSearch("corruption-token", { scope: "lib" }).hits.length, 1);

    // Corrupt the derived FTS index: remove the record's entry.
    engine.store.ensureOpen()
      .prepare("DELETE FROM memory_fts WHERE rowid IN (SELECT rowid FROM memory_records WHERE record_id = ?)")
      .run(a.recordId);

    // Detection: lexical corrupted; the canonical record is still intact and searchable via structured search.
    const corrupt = engine.checkProjectionIntegrity();
    const lexical = corrupt.projections.find((p) => p.name === "lexical")!;
    assert.equal(lexical.status, "corrupted");
    assert.ok(!corrupt.healthy);
    assert.equal(engine.lexicalSearch("corruption-token", { scope: "lib" }).hits.length, 0, "derived index is broken");
    assert.equal(engine.getRecord(a.recordId).content, "corruption-token unique", "canonical content intact");

    // Repair rebuilds the FTS index; lexical search recovers.
    const repair = engine.repairProjections();
    assert.ok(repair.repaired.includes("lexical"));
    assert.equal(repair.report.healthy, true);
    assert.equal(engine.lexicalSearch("corruption-token", { scope: "lib" }).hits.length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T26: rebuildAllProjections rebuilds every projection from canonical records and emits events", () => {
  const { engine, dir } = tempEngine("rebuild-all");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    engine.addRelation(a.recordId, {
      type: "applies_to", target: "entity:component:gateway",
      actor: { kind: "engine", name: "pp" }, method: "classified",
    });
    engine.setEmbeddingProvider(localHashProvider);

    const result = engine.rebuildAllProjections({ scope: "lib" });
    assert.ok(result.rebuilt.includes("lexical"));
    assert.ok(result.rebuilt.includes("entity"));
    assert.ok(result.rebuilt.includes("graph"));
    assert.ok(result.rebuilt.includes("embedding"));
    assert.equal(result.report.healthy, true);
    // Observability events emitted.
    const types = engine.listEvents(30).map((e) => e.type);
    assert.ok(types.includes("memory.index.rebuilt"));
    assert.ok(types.includes("memory.entities.projection.rebuilt"));
    assert.ok(types.includes("memory.graph.projection.rebuilt"));
    assert.ok(types.includes("memory.embeddings.projection.rebuilt"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T26: without a provider the embedding projection is reported unavailable, not corrupted", () => {
  const { engine, dir } = tempEngine("no-provider");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "a"));
    const report = engine.checkProjectionIntegrity("lib");
    const embedding = report.projections.find((p) => p.name === "embedding")!;
    assert.equal(embedding.status, "unavailable");
    // Health only considers ok; unavailable is not corruption.
    assert.equal(report.healthy, true);
    // rebuildAll without a provider skips embedding but rebuilds the rest.
    const rebuilt = engine.rebuildAllProjections({ scope: "lib" });
    assert.ok(!rebuilt.rebuilt.includes("embedding"));
    assert.ok(rebuilt.rebuilt.includes("lexical"));
    assert.equal(rebuilt.report.healthy, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});