/**
 * Task 3 (Midnight Memory Execution 01) — non-goals and engine isolation.
 * Proves: the explicit non-goal vocabulary landed in docs/BOUNDARY.md; the
 * package manifest carries no runtime dependency surface; the public
 * dispatcher contract (not just the internal method) exposes projection
 * rebuild without touching canonical records; backups never persist derived
 * projections; and dispatching an unenumerated operation is refused through
 * the same typed envelope as any other validation failure.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";

const REPO_ROOT = join(import.meta.dirname, "..");

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t49-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function rec(scope: string, subject: string, content: string) {
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
  };
}

test("T49: docs/BOUNDARY.md states the full non-goal vocabulary", () => {
  const boundary = readFileSync(join(REPO_ROOT, "docs", "BOUNDARY.md"), "utf8");
  const phrases = [
    "Performance ledger",
    "raw transcript store",
    "context-pack assembler",
    "vector database",
    "graph database",
    "agent orchestrator",
    "generic cache",
    "sibling-database reader",
  ];
  for (const phrase of phrases) {
    assert.ok(boundary.includes(phrase), `docs/BOUNDARY.md must state the non-goal: ${phrase}`);
  }
});

test("T49: package.json carries no runtime dependency surface", () => {
  const pkg = JSON.parse(readFileSync(join(REPO_ROOT, "package.json"), "utf8")) as { dependencies?: Record<string, string> };
  assert.ok(pkg.dependencies === undefined || Object.keys(pkg.dependencies).length === 0, "no runtime dependency could reach a sibling engine's store");
});

test("T49: projection rebuild is reachable through the public dispatcher contract, not just the internal method", () => {
  const { engine, dir } = tempEngine("rebuild-contract");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    engine.addRelation(a.recordId, {
      type: "applies_to", target: "entity:component:gateway",
      actor: { kind: "engine", name: "pp" }, method: "classified",
    });
    const canonicalHash = engine.getRecord(a.recordId).contentHash;

    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.projections",
      request: { scope: "lib", action: "rebuild" },
    });
    assert.equal(envelope.ok, true);
    if (envelope.ok) {
      const result = envelope.result as { rebuilt: string[]; report: { healthy: boolean } };
      assert.ok(result.rebuilt.includes("lexical"));
      assert.ok(result.rebuilt.includes("entity"));
      assert.equal(result.report.healthy, true);
    }
    // Canonical truth is byte-identical through a rebuild driven entirely
    // via the versioned contract surface.
    assert.equal(engine.getRecord(a.recordId).contentHash, canonicalHash);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T49: backup never persists derived projections", () => {
  const { engine, dir } = tempEngine("backup-shape");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    const bundle = engine.backup();
    const forbiddenKeys = ["embeddings", "graph", "entities", "fts", "lexical"];
    for (const key of forbiddenKeys) {
      assert.ok(!(key in bundle.data), `backup data must not carry a derived-projection key: ${key}`);
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T49: an unenumerated operation is refused through the same typed envelope as any other validation failure", () => {
  const { engine, dir } = tempEngine("closed-surface");
  try {
    engine.createScope("lib", "Library");
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.performanceStore.read" as never,
      request: {},
    });
    assert.equal(envelope.ok, false);
    if (!envelope.ok) assert.equal(envelope.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
