/**
 * CHILD LOOP 1 verification — Task 36: Context-safe memory excerpts.
 * Proves: bounded excerpt packs (subject, excerpted content, tags, sourceKind,
 * authority tier, validity, confidence, privacyClass) suitable for Context
 * Packs; per-excerpt content truncation; the privacy gate (sensitive excluded
 * by default, `skippedSensitive` reported; single-record sensitive content is
 * REDACTED, never leaked); evidence payloads never appear in excerpts; bounded
 * pack size + diagnostics; filters; typed negatives; and the versioned
 * contract.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { NotFoundError, PrivacyViolationError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t36-${name}-`));
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

test("T36: excerpt pack returns bounded structured facts with provenance metadata, no evidence payload", () => {
  const { engine, dir } = tempEngine("pack");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "Public api allows 120 requests per minute", { sourceKind: "study_finding", tags: ["api"] }));
    const pack = engine.contextExcerpts({ scope: "lib", maxExcerpts: 5 });
    assert.equal(pack.scopeId, engine.getScope("lib").scopeId);
    assert.equal(pack.maxExcerpts, 5);
    assert.ok(pack.excerpts.length >= 1);
    const excerpt = pack.excerpts[0]!;
    assert.equal(excerpt.subject, "Rate limit");
    assert.ok(excerpt.content.includes("120 requests"));
    assert.deepEqual(excerpt.tags, ["api"]);
    assert.equal(excerpt.sourceKind, "study_finding");
    assert.equal(excerpt.authorityTier, "verified_source");
    assert.equal(typeof excerpt.currentlyValid, "boolean");
    assert.equal(excerpt.confidence, 0.9);
    assert.equal(excerpt.privacyClass, "internal");
    assert.equal(excerpt.truncated, false);
    // NO evidence payload leaks into the excerpt (by-reference discipline).
    assert.ok(!("evidenceRefs" in excerpt), "excerpts never carry evidence payloads");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T36: bounded per-excerpt content is ellipsized and flagged", () => {
  const { engine, dir } = tempEngine("truncation");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Long", "x".repeat(500)));
    const pack = engine.contextExcerpts({ scope: "lib", maxContentChars: 40 });
    const excerpt = pack.excerpts[0]!;
    assert.equal(excerpt.content.length, 41, "40 chars + ellipsis");
    assert.ok(excerpt.content.endsWith("…"));
    assert.equal(excerpt.truncated, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T36: privacy gate — sensitive records are excluded by default and reported", () => {
  const { engine, dir } = tempEngine("privacy");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Public", "public fact"));
    engine.addRecord(rec("lib", "Secret", "restricted internal detail", { privacyClass: "sensitive" }));
    const gated = engine.contextExcerpts({ scope: "lib" });
    assert.ok(gated.excerpts.every((e) => e.subject !== "Secret"));
    assert.equal(gated.skippedSensitive, 1);
    const opened = engine.contextExcerpts({ scope: "lib", includeSensitive: true });
    assert.ok(opened.excerpts.some((e) => e.subject === "Secret"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T36: single-record excerpt REDACTS sensitive content rather than leaking it", () => {
  const { engine, dir } = tempEngine("single");
  try {
    engine.createScope("lib", "Library");
    const secret = engine.addRecord(rec("lib", "Credential note", "the api key is ABC123", { privacyClass: "sensitive" }));
    const redacted = engine.memoryExcerpt(secret.recordId);
    assert.equal(redacted.content, "[sensitive content excluded]");
    assert.ok(!redacted.content.includes("ABC123"), "restricted content is never leaked");
    const revealed = engine.memoryExcerpt(secret.recordId, { includeSensitive: true });
    assert.ok(revealed.content.includes("ABC123"));
    // Tombstoned records are refused (content scrubbed).
    const doomed = engine.addRecord(rec("lib", "Doomed", "scrubbed"));
    engine.deleteRecord(doomed.recordId, { actor: { kind: "human", name: "kim" }, reason: "scrub" });
    assert.throws(
      () => engine.memoryExcerpt(doomed.recordId),
      (err: unknown) => err instanceof PrivacyViolationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T36: bounded pack size, filters, and diagnostics", () => {
  const { engine, dir } = tempEngine("bounded-filters");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "alpha", { sourceKind: "study_finding" }));
    engine.addRecord(rec("lib", "B", "beta", { sourceKind: "analysis_evidence", epistemicClass: "derived", confidence: 0.6 }));
    engine.addRecord(rec("lib", "C", "gamma", { sourceKind: "agent_inference", epistemicClass: "inferred", confidence: 0.3, evidenceRefs: [] }));
    // Size cap + diagnostics.
    const capped = engine.contextExcerpts({ scope: "lib", maxExcerpts: 1 });
    assert.equal(capped.excerpts.length, 1);
    assert.equal(capped.diagnostics.truncated, true);
    assert.ok(capped.diagnostics.totalMatches >= 2);
    // minAuthority verified_source → only A.
    const verified = engine.contextExcerpts({ scope: "lib", minAuthority: "verified_source" });
    assert.ok(verified.excerpts.every((e) => e.subject === "A"));
    // minConfidence 0.7 → A and B, not C.
    const confident = engine.contextExcerpts({ scope: "lib", minConfidence: 0.7 });
    assert.ok(!confident.excerpts.some((e) => e.subject === "C"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T36: negative — unknown scope, invalid at, bad minConfidence, unknown record", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.contextExcerpts({ scope: "nope" }),
      (err: unknown) => err instanceof NotFoundError,
    );
    assert.throws(
      () => engine.contextExcerpts({ scope: "lib", at: "garbage" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.contextExcerpts({ scope: "lib", minConfidence: 1.5 }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.memoryExcerpt("mem_nonexistent"),
      (err: unknown) => err instanceof Error,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T36: versioned contract — memory.excerpts pack and record through the dispatcher", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    const pack = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.excerpts",
      request: { scope: "lib", maxExcerpts: 5 },
    });
    assert.equal(pack.ok, true);
    if (pack.ok) {
      const result = pack.result as { pack: { excerpts: Array<{ subject: string; truncated: boolean }> } };
      assert.ok(result.pack.excerpts.length >= 1);
      assert.ok(result.pack.excerpts.every((e) => typeof e.truncated === "boolean"));
    }
    const bad = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.excerpts",
      request: { scope: "lib", at: "garbage" },
    });
    assert.equal(bad.ok, false);
    if (!bad.ok) assert.equal(bad.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});