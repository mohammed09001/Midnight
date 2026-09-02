/**
 * CHILD LOOP 2 verification — Task 18: deduplication and near-duplicate
 * handling. Proves: exact duplicate detection via normalized content hash,
 * normalized/near-duplicate detection via token Jaccard, preservation of
 * idempotency, and the duplicate-vs-corroborating distinction (same subject,
 * distinct content, distinct evidence ⇒ independent corroboration, NOT a
 * duplicate). Includes negative and boundary cases.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { jaccardSimilarity, NEAR_DUPLICATE_THRESHOLD } from "../src/engine/dedup.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t18-${name}-`));
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

test("T18: exact duplicate — identical normalized content is detected", () => {
  const { engine, dir } = tempEngine("exact");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Rate limit", "Public api allows 120 requests per minute"));
    // Re-proposal with identical normalized text (extra whitespace collapses).
    const analysis = engine.analyzeDuplicates("lib", {
      subject: "Rate limit",
      content: "  Public   api allows 120 requests  per minute  ",
      evidenceRefs: [{ engine: "external", ref: "note:same" }],
    });
    assert.equal(analysis.isDuplicate, true);
    assert.equal(analysis.matches.length, 1);
    assert.equal(analysis.matches[0]!.kind, "exact");
    assert.equal(analysis.matches[0]!.similarity, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T18: normalized near-duplicate — high token overlap on the same subject", () => {
  const { engine, dir } = tempEngine("near");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Deploy window", "The deployment window is every Tuesday morning for the api service"));
    const analysis = engine.analyzeDuplicates("lib", {
      subject: "Deploy window",
      content: "The deployment window is every Tuesday morning for the api service now",
    });
    assert.equal(analysis.isDuplicate, true);
    assert.equal(analysis.matches[0]!.kind, "normalized");
    assert.ok(analysis.matches[0]!.similarity >= NEAR_DUPLICATE_THRESHOLD);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T18: duplicate content is DISTINGUISHED from independently corroborating evidence", () => {
  const { engine, dir } = tempEngine("corroboration");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(
      rec("lib", "Backup time", "Backup runs at 02:00 UTC", {
        evidenceRefs: [{ engine: "repository_sync", ref: "docs/backup.md" }],
      }),
    );
    // Same subject, genuinely different content, different evidence → corroborating.
    const corroborating = engine.analyzeDuplicates("lib", {
      subject: "Backup time",
      content: "The nightly backup job starts at two in the morning coordinated universal time",
      evidenceRefs: [{ engine: "repository_sync", ref: "runbook/ops-4.md" }],
    });
    assert.equal(corroborating.isDuplicate, false, "distinct content is NOT a duplicate");
    assert.equal(corroborating.corroborating.length, 1);
    assert.equal(corroborating.matches[0]!.kind, "corroborating");
    assert.ok(corroborating.matches[0]!.distinctEvidenceRefs.length >= 1);

    // A completely different subject is independent (no duplicate, no corroboration).
    const independent = engine.analyzeDuplicates("lib", {
      subject: "Release cadence",
      content: "We ship every two weeks",
    });
    assert.equal(independent.isDuplicate, false);
    assert.equal(independent.matches.length, 0);
    assert.equal(independent.corroborating.length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T18: idempotency is preserved — the same key returns the same record, no duplicate", () => {
  const { engine, dir } = tempEngine("idempotency");
  try {
    engine.createScope("lib", "Library");
    const first = engine.addRecord(
      rec("lib", "Region", "eu-west-1", { idempotencyKey: "sync:job-7" }),
    );
    const second = engine.addRecord(
      rec("lib", "Region", "eu-west-1", { idempotencyKey: "sync:job-7" }),
    );
    assert.equal(first.recordId, second.recordId, "replay returns the same record");
    // And dedup analysis confirms a single exact match (not two copies).
    const analysis = engine.analyzeDuplicates("lib", {
      subject: "Region",
      content: "eu-west-1",
    });
    assert.equal(analysis.matches.length, 1);
    assert.equal(analysis.matches[0]!.kind, "exact");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T18: candidate stream scan surfaces duplicate proposals before promotion", () => {
  const { engine, dir } = tempEngine("candidates");
  try {
    engine.createScope("lib", "Library");
    engine.addCandidate({
      scope: "lib",
      kind: "fact",
      subject: "Rate limit",
      content: "120 requests per minute",
      actor: { kind: "agent", name: "worker-a" },
      method: "extracted",
      epistemicClass: "observed",
      confidence: 0.8,
      reason: "learned from repo",
      sourceKind: "repository_evidence",
      evidenceRefs: [{ engine: "repository_sync", ref: "doc:rate.md" }],
    });
    // Existing promoted record with identical content.
    engine.addRecord(rec("lib", "Rate limit", "120 requests per minute"));
    const results = engine.findCandidateDuplicates("lib");
    assert.equal(results.length, 1);
    assert.equal(results[0]!.analysis.isDuplicate, true);
    assert.equal(results[0]!.analysis.matches[0]!.kind, "exact");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T18: pure matcher — jaccard bounds and empty handling", () => {
  assert.equal(jaccardSimilarity("", ""), 0);
  assert.equal(jaccardSimilarity("a b", "a b"), 1);
  assert.ok(jaccardSimilarity("a b c d e", "a b c d e f") < 1);
  assert.ok(jaccardSimilarity("completely different words here", "totally unrelated stuff") < 0.2);
});

test("T18: negative — malformed subject/content raise typed errors", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.analyzeDuplicates("lib", { subject: "", content: "x" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.analyzeDuplicates("lib", { subject: "x", content: "   " }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.analyzeDuplicates("nope", { subject: "x", content: "y" }),
      (err: unknown) => err instanceof Error,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});