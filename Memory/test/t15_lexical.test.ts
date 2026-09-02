/**
 * CHILD LOOP 2 verification — Task 15: lexical/BM25-style memory search.
 * Proves: deterministic ranked keyword search over normalized text
 * (subject/content/tags), exact-term semantics (no stemming), explanations
 * per hit, query diagnostics, index consistency through revise/tombstone/
 * purge (triggers), rebuildability, determinism, and restart survival.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t15-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function fact(scope: string, subject: string, content: string) {
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

test("T15: lexical search ranks by BM25 and explains which fields matched", () => {
  const { engine, dir } = tempEngine("ranking");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(fact("lib", "Rate limiting", "Public api allows 120 requests per minute"));
    engine.addRecord(fact("lib", "Caching", "Cache stamps are rebuildable"));
    engine.addRecord(fact("lib", "Requests note", "Mention of requests in passing"));

    const result = engine.lexicalSearch("requests", { scope: "lib" });
    assert.equal(result.terms.length, 1);
    assert.equal(result.terms[0], "requests");
    assert.ok(result.hits.length >= 1);
    // The subject "Rate limiting" record contains "requests" in content.
    const rateHit = result.hits.find((h) => h.record.subject === "Rate limiting");
    assert.ok(rateHit !== undefined);
    assert.equal(rateHit.explanation.contentMatched, true);
    assert.equal(rateHit.explanation.subjectMatched, false);
    assert.ok(rateHit.score > 0, "score is positive-better");
    // A subject match outweighs a content-only match (weights: subject 5).
    const subjectHit = result.hits.find((h) => h.record.subject === "Requests note");
    if (subjectHit !== undefined) {
      const inSubject = result.hits.find((h) => h.record.subject === "Requests note")!;
      const inContent = rateHit!;
      assert.ok(
        inSubject.score > inContent.score,
        "subject-weighted hit ranks above content-only hit",
      );
    }
    // Diagnostics.
    assert.equal(result.diagnostics.tokenizer, "unicode61");
    assert.equal(result.diagnostics.indexMode, "fts5-external-content");
    assert.ok(result.diagnostics.totalMatches >= result.hits.length);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T15: exact-term semantics — multi-token AND, no stemming", () => {
  const { engine, dir } = tempEngine("exact-terms");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(fact("lib", "A", "Deploy with retry backoff"));
    engine.addRecord(fact("lib", "B", "Deploy without backoff"));
    engine.addRecord(fact("lib", "C", "Retries are configured elsewhere"));

    // Both terms must match (implicit AND).
    const both = engine.lexicalSearch("deploy backoff", { scope: "lib" });
    assert.equal(both.hits.length, 2);
    assert.deepEqual(both.terms, ["deploy", "backoff"]);
    // No stemming: "retries" does not match "retry".
    const retry = engine.lexicalSearch("retries", { scope: "lib" });
    assert.ok(!retry.hits.some((h) => h.record.subject === "A"));
    const retryExact = engine.lexicalSearch("retry", { scope: "lib" });
    assert.ok(retryExact.hits.some((h) => h.record.subject === "A"));
    assert.ok(!retryExact.hits.some((h) => h.record.subject === "C"));
    // FTS5 syntax characters in user input are inert (safely quoted).
    const injection = engine.lexicalSearch("deploy NOT (backoff OR x)", { scope: "lib" });
    assert.deepEqual(injection.terms, ["deploy", "NOT", "backoff", "OR", "x"]);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T15: index follows the lifecycle — revise updates, tombstone/purge remove", () => {
  const { engine, dir } = tempEngine("lifecycle-sync");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord(fact("lib", "Latency", "P99 latency is 250ms"));
    engine.reviseRecord(record.recordId, {
      content: "P99 latency is 400ms after the change",
      actor: { kind: "human", name: "kim" },
      method: "corrected",
      reason: "regression",
    });
    // New term found (update trigger fired), old term gone.
    assert.ok(engine.lexicalSearch("400ms", { scope: "lib" }).hits.some((h) => h.record.recordId === record.recordId));
    assert.ok(!engine.lexicalSearch("250ms", { scope: "lib" }).hits.some((h) => h.record.recordId === record.recordId));

    engine.deleteRecord(record.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "scrub",
    });
    // Tombstoned content is scrubbed → not searchable.
    assert.ok(!engine.lexicalSearch("400ms", { scope: "lib" }).hits.some((h) => h.record.recordId === record.recordId));

    // Purge path: row deleted → delete trigger removes index entries.
    const doomed = engine.addRecord(fact("lib", "Doomed", "zindependence-token"));
    engine.purgeRecord(doomed.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "erasure",
    });
    assert.ok(!engine.lexicalSearch("zindependence-token", { scope: "lib" }).hits.some((h) => h.record.recordId === doomed.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T15: the index is a rebuildable derived artifact", () => {
  const { engine, dir } = tempEngine("rebuild");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(fact("lib", "Drift", "driftmarker term"));
    // Force a rebuild — the recovery path for index/content drift.
    engine.rebuildSearchIndex();
    const after = engine.lexicalSearch("driftmarker", { scope: "lib" });
    assert.equal(after.hits.length, 1);
    assert.equal(
      engine.listEvents(10).some((e) => e.type === "memory.index.rebuilt"),
      true,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T15: determinism and restart survival", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t15-restart-"));
  const path = join(dir, "memory.db");
  let firstOrder: string[];
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.addRecord(fact("lib", "Backoff study", "Exponential backoff for retries"));
    engine.addRecord(fact("lib", "Backoff note", "backoff mentioned"));
    const r1 = engine.lexicalSearch("backoff", { scope: "lib" });
    const r2 = engine.lexicalSearch("backoff", { scope: "lib" });
    assert.deepEqual(r1.hits.map((h) => [h.record.recordId, h.score]), r2.hits.map((h) => [h.record.recordId, h.score]));
    firstOrder = r1.hits.map((h) => h.record.recordId);
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const again = engine.lexicalSearch("backoff", { scope: "lib" });
      assert.deepEqual(again.hits.map((h) => h.record.recordId), firstOrder);
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});

test("T15: negative — empty queries and scope filters are handled", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("alpha", "Alpha");
    engine.createScope("beta", "Beta");
    engine.addRecord(fact("alpha", "Only here", "island token"));
    assert.throws(() => engine.lexicalSearch("   "), (err: unknown) => err instanceof ValidationError);
    assert.throws(() => engine.lexicalSearch("!!!"), (err: unknown) => err instanceof ValidationError);
    // Scope filter applies to lexical results.
    assert.equal(engine.lexicalSearch("island", { scope: "beta" }).hits.length, 0);
    assert.equal(engine.lexicalSearch("island", { scope: "alpha" }).hits.length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
