/**
 * Task 4 (Midnight Memory Execution 02) — align Memory scope identity with
 * Performance project references. Proves: the colon<->dot mapping between
 * Performance's canonical identity string and a Memory projectKey round
 * trips exactly, survives restart, and rejects malformed/wrong-kind input
 * explicitly rather than guessing.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  MemoryEngine,
  projectKeyFromPerformanceIdentity,
  performanceIdentityFromProjectKey,
} from "../src/index.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string; path: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t50-${name}-`));
  const path = join(dir, "memory.db");
  const engine = new MemoryEngine({ storePath: path });
  engine.open();
  return { engine, dir, path };
}

test("T50: a Performance canonical identity round-trips through a Memory scope and back", () => {
  const canonical = `mp:v1:project:${randomUUID()}`;
  const { engine, dir } = tempEngine("round-trip");
  try {
    const projectKey = projectKeyFromPerformanceIdentity(canonical);
    engine.createScope(projectKey, "Perf Project");
    const scope = engine.getScope(projectKey);
    assert.equal(scope.projectKey, projectKey);
    assert.equal(performanceIdentityFromProjectKey(scope.projectKey), canonical);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T50: a malformed canonical identity is rejected explicitly, not guessed", () => {
  assert.throws(
    () => projectKeyFromPerformanceIdentity("mp:v1:project"),
    (err: unknown) => err instanceof Error && (err as { code?: string }).code === "MEMORY_VALIDATION_FAILED",
  );
  assert.throws(
    () => projectKeyFromPerformanceIdentity("xx:v1:project:00000000-0000-4000-8000-000000000000"),
    (err: unknown) => err instanceof Error && (err as { code?: string }).code === "MEMORY_VALIDATION_FAILED",
  );
  assert.throws(
    () => projectKeyFromPerformanceIdentity("mp:v1:project:not-a-uuid"),
    (err: unknown) => err instanceof Error && (err as { code?: string }).code === "MEMORY_VALIDATION_FAILED",
  );
});

test("T50: a Performance identity of an unsupported kind is rejected, naming the kind", () => {
  assert.throws(
    () => projectKeyFromPerformanceIdentity(`mp:v1:tool_observation:${randomUUID()}`),
    (err: unknown) => err instanceof Error && /tool_observation/.test(err.message),
  );
});

test("T50: cross-language agreement fixture — same literal input maps to the same literal projectKey as the Python bridge", () => {
  // Mirrored in Performance/tests/test_memory_bridge.py's
  // test_cross_language_agreement_fixture — proves both independent
  // implementations agree on the exact wire value, not just self-consistency.
  assert.equal(
    projectKeyFromPerformanceIdentity("mp:v1:project:00000000-0000-4000-8000-000000000000"),
    "mp.v1.project.00000000-0000-4000-8000-000000000000",
  );
});

test("T50: the mapping survives a store restart", () => {
  const canonical = `mp:v1:project:${randomUUID()}`;
  const projectKey = projectKeyFromPerformanceIdentity(canonical);
  const dir = mkdtempSync(join(tmpdir(), "mem-t50-restart-"));
  const path = join(dir, "memory.db");
  try {
    {
      const engine = new MemoryEngine({ storePath: path });
      engine.open();
      engine.createScope(projectKey, "Perf Project");
      engine.close();
    }
    {
      const engine = new MemoryEngine({ storePath: path });
      engine.open();
      try {
        const scope = engine.getScope(projectKey);
        assert.equal(scope.projectKey, projectKey);
        assert.equal(performanceIdentityFromProjectKey(scope.projectKey), canonical);
      } finally {
        engine.close();
      }
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
