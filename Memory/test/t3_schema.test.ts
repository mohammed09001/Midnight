/**
 * CHILD LOOP 3 verification — Task 3: canonical Memory record schema.
 * Proves every required field group (record kind, subject, normalized
 * content, provenance, source engine, evidence links, scope, confidence,
 * temporal validity, privacy class, tags, relation hints, created/revised
 * timestamps, status), by-reference payloads, and the full record
 * lifecycle with negative/boundary cases.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import {
  ConflictError,
  NotFoundError,
  PrivacyViolationError,
  ValidationError,
} from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t3-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function baseInput(scope: string) {
  return {
    scope,
    kind: "fact" as const,
    subject: "Rate limiting",
    content: "Public API allows 120 requests per minute per token",
    actor: { kind: "agent" as const, name: "worker-1", agentType: "research" },
    method: "extracted",
    epistemicClass: "observed" as const,
    confidence: 0.95,
    sourceKind: "study_finding" as const,
    evidenceRefs: [{ engine: "study_document" as const, ref: "doc:rfc-1234#s2" }],
  };
}

test("T3: canonical schema round-trips every required field group", () => {
  const { engine, dir } = tempEngine("schema");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord({
      ...baseInput("lib"),
      subject: "  Rate   limiting ",
      content: "Public  API allows\n\t120 requests  per minute per token ",
      evidenceRefs: [
        { engine: "repository_sync", ref: "repo:acme/api@main:src/limiter.ts", note: "limiter config" },
        { engine: "study_document", ref: "doc:rfc-7777#section-3" },
      ],
      relationHints: [
        { type: "depends_on", target: "mem_somewhere", note: "token auth" },
        { type: "related", target: "engine:study_document:doc:rfc-7777" },
      ],
      tags: ["api", "limits"],
      privacyClass: "internal",
      validFrom: "2026-08-01T00:00:00.000Z",
      validUntil: "2027-08-01T00:00:00.000Z",
    });

    // kind, subject (normalized), normalized content, provenance, evidence
    // links, scope, confidence, temporal validity, privacy, tags, relation
    // hints, timestamps, status.
    assert.equal(record.kind, "fact");
    assert.equal(record.subject, "Rate limiting");
    assert.equal(record.content, "Public API allows 120 requests per minute per token");
    assert.match(record.contentHash, /^[0-9a-f]{64}$/);
    assert.equal(record.provenance.actor.kind, "agent");
    assert.equal(record.provenance.actor.agentType, "research");
    assert.equal(record.provenance.method, "extracted");
    assert.ok(record.provenance.capturedAt.length > 0);
    assert.equal(record.evidenceRefs.length, 2);
    assert.equal(record.evidenceRefs[0]!.engine, "repository_sync");
    assert.equal(record.scopeId, engine.getScope("lib").scopeId);
    assert.equal(record.confidence, 0.95);
    assert.equal(record.epistemicClass, "observed");
    assert.equal(record.validFrom, "2026-08-01T00:00:00.000Z");
    assert.equal(record.validUntil, "2027-08-01T00:00:00.000Z");
    assert.equal(record.privacyClass, "internal");
    assert.deepEqual(record.tags, ["api", "limits"]);
    assert.equal(record.relationHints.length, 2);
    assert.equal(record.status, "active");
    assert.equal(record.revision, 1);
    assert.equal(record.contractVersion, MEMORY_ENGINE_CONTRACT_VERSION);
    assert.equal(record.provenance.sourceKind, "study_finding");
    assert.ok(record.createdAt.length > 0);
    assert.ok(record.revisedAt.length > 0);
    assert.ok(record.observedAt.length > 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: source payloads stay BY REFERENCE — embedding attempts are rejected", () => {
  const { engine, dir } = tempEngine("byref");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () =>
        engine.addRecord({
          ...baseInput("lib"),
          evidenceRefs: [
            // Payload-smuggling attempt: unknown field carrying file content.
            { engine: "repository_sync", ref: "repo:x", payload: "entire file contents here" } as never,
          ],
        }),
      (err: unknown) => err instanceof ValidationError,
      "unknown evidence fields are rejected — by-reference only",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: privacy — secret-class records are refused BEFORE any persistence", () => {
  const { engine, dir } = tempEngine("privacy");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.addRecord({ ...baseInput("lib"), privacyClass: "secret" as never }),
      (err: unknown) => err instanceof PrivacyViolationError,
    );
    // And nothing was persisted.
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: validation matrix — malformed records rejected with typed errors", () => {
  const { engine, dir } = tempEngine("validation");
  try {
    engine.createScope("lib", "Library");
    const cases: Array<{ input: Record<string, unknown>; why: string }> = [
      { input: { ...baseInput("lib"), kind: "poem" }, why: "unknown kind" },
      { input: { ...baseInput("lib"), epistemicClass: "vibes" }, why: "unknown epistemic class" },
      { input: { ...baseInput("lib"), confidence: 1.5 }, why: "confidence out of range" },
      { input: { ...baseInput("lib"), confidence: "high" }, why: "non-numeric confidence" },
      { input: { ...baseInput("lib"), content: "   " }, why: "empty content" },
      { input: { ...baseInput("lib"), subject: "" }, why: "empty subject" },
      { input: { ...baseInput("lib"), privacyClass: "top-secret" }, why: "unknown privacy class" },
      { input: { ...baseInput("lib"), validUntil: "not-a-date" }, why: "malformed timestamp" },
      {
        input: {
          ...baseInput("lib"),
          evidenceRefs: [{ engine: "warp_drive", ref: "x" }],
        },
        why: "unknown evidence engine",
      },
      {
        input: {
          ...baseInput("lib"),
          relationHints: [{ type: "hates", target: "mem_x" }],
        },
        why: "unknown relation type",
      },
      { input: { ...baseInput("lib"), tags: ["ok", ""] }, why: "empty tag" },
    ];
    for (const { input, why } of cases) {
      assert.throws(
        () => engine.addRecord(input as never),
        (err: unknown) => err instanceof ValidationError,
        `expected rejection: ${why}`,
      );
    }
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0, "nothing persisted");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: revise keeps immutable revision history and updates revisedAt", async () => {
  const { engine, dir } = tempEngine("revise");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(baseInput("lib"));
    await new Promise((resolve) => setTimeout(resolve, 5));
    const v2 = engine.reviseRecord(v1.recordId, {
      content: "Public API allows 240 requests per minute per token",
      actor: { kind: "human", name: "kim" },
      method: "correction",
      reason: "limit doubled",
    });
    assert.equal(v2.revision, 2);
    assert.equal(v2.content, "Public API allows 240 requests per minute per token");
    assert.equal(v2.createdAt, v1.createdAt, "createdAt is immutable");
    assert.ok(v2.revisedAt > v1.revisedAt);
    // Immutable revision rows are queryable via the store.
    const revisions = engine.store
      .ensureOpen()
      .prepare("SELECT revision, content, reason FROM memory_record_revisions WHERE record_id = ? ORDER BY revision")
      .all(v1.recordId) as Array<{ revision: number; content: string; reason: string | null }>;
    assert.equal(revisions.length, 2);
    assert.equal(revisions[0]!.content, v1.content);
    assert.equal(revisions[0]!.reason, "initial");
    assert.equal(revisions[1]!.reason, "limit doubled");
    // Events capture the lifecycle.
    const types = engine.listEvents(20).map((e) => e.type);
    assert.ok(types.includes("memory.record.revised"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: supersede builds the chain; revise/supersede of non-active fails", () => {
  const { engine, dir } = tempEngine("supersede");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(baseInput("lib"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Updated limit: 200 rpm",
      actor: { kind: "human", name: "kim" },
      method: "policy change",
      reason: "limit raised",
    });
    assert.equal(v2.supersedesId, v1.recordId);
    assert.equal(engine.getRecord(v1.recordId).status, "superseded");
    assert.equal(engine.getRecord(v1.recordId).supersededById, v2.recordId);

    assert.throws(
      () =>
        engine.reviseRecord(v1.recordId, {
          content: "zombie edit",
          actor: { kind: "human", name: "kim" },
          method: "edit",
          reason: "should fail anyway",
        }),
      (err: unknown) => err instanceof ConflictError,
      "superseded records cannot be revised",
    );
    assert.throws(
      () =>
        engine.supersedeRecord(v1.recordId, {
          content: "double supersede",
          actor: { kind: "human", name: "kim" },
          method: "policy change",
          reason: "should fail anyway",
        }),
      (err: unknown) => err instanceof ConflictError,
      "already-superseded records cannot be superseded again",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: retract requires a reason and marks status", () => {
  const { engine, dir } = tempEngine("retract");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(baseInput("lib"));
    assert.throws(
      () => engine.retractRecord(record.recordId, { actor: { kind: "human", name: "kim" }, reason: "  " }),
      (err: unknown) => err instanceof ValidationError,
    );
    const retracted = engine.retractRecord(record.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "fact was wrong",
    });
    assert.equal(retracted.status, "retracted");
    assert.throws(
      () =>
        engine.retractRecord(record.recordId, {
          actor: { kind: "human", name: "kim" },
          reason: "again",
        }),
      (err: unknown) => err instanceof ConflictError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: temporal validity — stale records expire explicitly", () => {
  const { engine, dir } = tempEngine("expiry");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord({
      ...baseInput("lib"),
      subject: "Old promo",
      content: "Launch discount active",
      validUntil: "2026-08-15T00:00:00.000Z",
    });
    engine.addRecord({ ...baseInput("lib"), subject: "Standing rule", content: "No discounts" });
    const expired = engine.expireStaleRecords("2026-08-30T00:00:00.000Z");
    assert.equal(expired, 1);
    const active = engine.searchRecords({ scope: "lib", status: "active" });
    assert.equal(active.length, 1);
    assert.equal(active[0]!.subject, "Standing rule");
    const all = engine.searchRecords({ scope: "lib" });
    assert.ok(all.some((r) => r.status === "expired"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: search filters by scope, kind, status, subject, content, and tag", () => {
  const { engine, dir } = tempEngine("search");
  try {
    // This test deliberately exercises cross-project retrieval (no scope).
    engine.setProjectIsolation("open");
    engine.createScope("alpha", "Alpha");
    engine.createScope("beta", "Beta");
    engine.addRecord({
      ...baseInput("alpha"),
      subject: "Limiter",
      content: "Fixed window limiter at 120 rpm",
      tags: ["api", "limits"],
    });
    engine.addRecord({
      ...baseInput("alpha"),
      subject: "Cache",
      content: "Cache is rebuildable, never truth",
      kind: "decision",
      tags: ["storage"],
    });
    engine.addRecord({
      ...baseInput("beta"),
      subject: "Limiter beta",
      content: "Token bucket for beta cluster",
    });

    assert.equal(engine.searchRecords({ scope: "alpha" }).length, 2);
    assert.equal(engine.searchRecords({ scope: "beta" }).length, 1);
    assert.equal(engine.searchRecords({ scope: "alpha", kind: "decision" }).length, 1);
    assert.equal(engine.searchRecords({ subjectContains: "limiter" }).length, 2);
    assert.equal(engine.searchRecords({ contentContains: "rebuildable" }).length, 1);
    assert.equal(engine.searchRecords({ tag: "limits" }).length, 1);
    assert.equal(engine.searchRecords({ scope: "alpha", status: "active" }).length, 2);
    assert.equal(engine.searchRecords({ limit: 1 }).length, 1);
    // LIKE wildcards in user input are inert.
    assert.equal(engine.searchRecords({ contentContains: "%100%" }).length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: candidates capture pre-promotion knowledge and promote cleanly", () => {
  const { engine, dir } = tempEngine("candidates");
  try {
    engine.createScope("lib", "Library");
    const candidate = engine.addCandidate({
      ...baseInput("lib"),
      subject: "Possible bottleneck",
      content: "Synchronous writes may serialize ingestion",
      epistemicClass: "inferred",
      confidence: 0.4,
      reason: "performance hypothesis worth tracking",
    });
    assert.equal(candidate.status, "open");
    assert.ok(candidate.candidateId.startsWith("cand_"));
    const record = engine.promoteCandidate(candidate.candidateId, {
      actor: { kind: "human", name: "kim" },
      policy: "explicit_user_decision",
    });
    assert.equal(record.status, "active");
    assert.equal(record.subject, candidate.subject);
    const after = engine.listEvents(50).find((e) => e.type === "memory.candidate.promoted");
    assert.ok(after !== undefined);
    assert.equal(
      (after!.payload as { recordId: string }).recordId,
      record.recordId,
    );
    assert.equal(
      (after!.payload as { policy: string }).policy,
      "explicit_user_decision",
    );
    assert.throws(
      () =>
        engine.promoteCandidate(candidate.candidateId, {
          actor: { kind: "human", name: "kim" },
        }),
      (err: unknown) => err instanceof ConflictError,
      "double promotion is a conflict",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: records are queryable across restart with identical content hash", () => {
  const { engine, dir } = tempEngine("hash");
  const path = join(dir, "memory.db");
  let recordId: string;
  let hash: string;
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(baseInput("lib"));
    recordId = record.recordId;
    hash = record.contentHash;
  } finally {
    engine.close();
  }
  const reopened = new MemoryEngine({ storePath: path });
  reopened.open();
  try {
    const again = reopened.getRecord(recordId!);
    assert.equal(again.contentHash, hash);
    assert.equal(again.content, "Public API allows 120 requests per minute per token");
  } finally {
    reopened.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T3: negative — unknown record id fails typed, unknown group id fails typed", () => {
  const { engine, dir } = tempEngine("notfound");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.getRecord("mem_missing"),
      (err: unknown) => err instanceof NotFoundError,
    );
    assert.throws(
      () => engine.addRecord({ ...baseInput("lib"), contradictionGroupId: "ctg_missing" }),
      (err: unknown) => err instanceof NotFoundError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

