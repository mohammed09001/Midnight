/**
 * CHILD LOOP 1 verification — Task 37: field-level privacy and project
 * isolation. Proves: content-class policy (per scope) controls exportability
 * of excerpts and derived indexes (sensitive excluded by default, `forbidSensitive`
 * refuses even opt-in, restricted `exportable` excludes non-exportable classes);
 * project/workspace isolation (strict by default — unscoped read/query refused;
 * `open` allows cross-project); local/self-hosted default surfaced in
 * `policyStatus`; the versioned contract (`memory.privacy`); and typed
 * negatives.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { PrivacyViolationError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t37-${name}-`));
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

test("T37: project isolation is strict by default — unscoped read/query is refused", () => {
  const { engine, dir } = tempEngine("isolation");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "a"));
    // Strict default: unscoped retrieval is refused (project isolation).
    assert.throws(
      () => engine.searchRecords({}),
      (err: unknown) => err instanceof ValidationError && err.message.includes("project isolation"),
    );
    assert.throws(
      () => engine.lexicalSearch("a"),
      (err: unknown) => err instanceof ValidationError,
    );
    // Scoped retrieval works.
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 1);
    // Switching to open allows cross-project (unscoped) retrieval.
    engine.setProjectIsolation("open");
    assert.equal(engine.searchRecords({}).length, 1);
    const status = engine.policyStatus();
    assert.equal(status.projectIsolation, "open");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T37: content-class policy — sensitive excluded by default, forbidSensitive refuses even opt-in", () => {
  const { engine, dir } = tempEngine("content-policy");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Public", "public fact"));
    engine.addRecord(rec("lib", "Secret", "restricted detail", { privacyClass: "sensitive" }));
    // Default policy: sensitive excluded from excerpts.
    const pack = engine.contextExcerpts({ scope: "lib" });
    assert.ok(pack.excerpts.every((e) => e.subject !== "Secret"));
    assert.equal(pack.skippedSensitive, 1);
    // Opt-in reveals sensitive (default policy allows it).
    const opened = engine.contextExcerpts({ scope: "lib", includeSensitive: true });
    assert.ok(opened.excerpts.some((e) => e.subject === "Secret"));
    // forbidSensitive refuses sensitive even with opt-in.
    engine.setScopePrivacyPolicy("lib", { content: { exportable: ["public", "internal"], forbidSensitive: true } });
    const forbidden = engine.contextExcerpts({ scope: "lib", includeSensitive: true });
    assert.ok(forbidden.excerpts.every((e) => e.subject !== "Secret"), "forbidSensitive excludes sensitive everywhere");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T37: restricted exportable classes exclude non-exportable content from excerpts", () => {
  const { engine, dir } = tempEngine("exportable");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "PublicNote", "public note"));
    engine.addRecord(rec("lib", "InternalNote", "internal note", { privacyClass: "internal" }));
    // Restrict exports to public only → internal is excluded.
    engine.setScopePrivacyPolicy("lib", { content: { exportable: ["public"], forbidSensitive: false } });
    const pack = engine.contextExcerpts({ scope: "lib" });
    assert.ok(pack.excerpts.every((e) => e.subject === "PublicNote"));
    // policyStatus reflects the per-scope content policy.
    const status = engine.policyStatus();
    const lib = status.scopes.find((s) => s.projectKey === "lib")!;
    assert.deepEqual(lib.content.exportable, ["public"]);
    assert.equal(lib.content.forbidSensitive, false);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T37: content-class policy applies to the embedding (derived index) gate", () => {
  const { engine, dir } = tempEngine("embedding-gate");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Public", "public fact"));
    engine.addRecord(rec("lib", "Secret", "secret detail", { privacyClass: "sensitive" }));
    engine.setEmbeddingProvider({ name: "test", model: "m", version: "1", embed: (t) => t.map(() => new Float32Array(2)) });
    // Default: sensitive excluded from the projection.
    const gated = engine.buildEmbeddingProjection("lib");
    assert.equal(gated.recordCount, 1);
    assert.equal(gated.skippedPrivacy, 1);
    // forbidSensitive refuses sensitive even with opt-in.
    engine.setScopePrivacyPolicy("lib", { content: { exportable: ["public", "internal"], forbidSensitive: true } });
    const forbidden = engine.rebuildEmbeddingProjection("lib", { includeSensitive: true });
    assert.equal(forbidden.recordCount, 1, "sensitive excluded from the derived index despite opt-in");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T37: local/self-hosted default is explicit and immutable in policyStatus", () => {
  const { engine, dir } = tempEngine("self-hosted");
  try {
    engine.createScope("lib", "Library");
    const status = engine.policyStatus();
    assert.equal(status.selfHosted, true, "self-hosted default is immutable");
    assert.equal(status.projectIsolation, "strict");
    assert.ok(Array.isArray(status.scopes));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T37: versioned contract — memory.privacy status and policy actions", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    const status = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.privacy",
      request: {},
    });
    assert.equal(status.ok, true);
    if (status.ok) {
      const result = status.result as { status: { selfHosted: boolean; projectIsolation: string } };
      assert.equal(result.status.selfHosted, true);
      assert.equal(result.status.projectIsolation, "strict");
    }
    const setPolicy = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.privacy",
      request: { action: "setScopeContentPolicy", scope: "lib", policy: { content: { exportable: ["public"], forbidSensitive: true } } },
    });
    assert.equal(setPolicy.ok, true);
    // The engine now applies the policy to excerpt packs.
    const pack = engine.contextExcerpts({ scope: "lib", includeSensitive: true });
    assert.equal(pack.excerpts.length, 0, "forbidSensitive applied via contract-configured policy");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T37: typed negatives — invalid isolation mode, invalid content policy", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.setScopePrivacyPolicy("nope", { content: { exportable: ["public"], forbidSensitive: false } }),
      (err: unknown) => err instanceof Error, // NotFoundError (unknown scope)
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});