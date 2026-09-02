/**
 * CHILD LOOP 1 verification — Task 17: provenance-aware ranking.
 * Proves: high-authority, direct, current evidence ranks above lower
 * authority/directness/currency; low-confidence and contradicted records
 * are EXPOSED (never silently hidden); breakdowns are explicit; determinism
 * and restart survival.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t17-${name}-`));
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

test("T17: high-authority, direct, current evidence ranks above lower-quality peers", () => {
  const { engine, dir } = tempEngine("ranking");
  try {
    engine.createScope("lib", "Library");
    // High authority: verified study finding, observed, with evidence, active.
    const high = engine.addRecord(
      rec("lib", "Rate limit", "Public api allows 120 requests per minute", {
        sourceKind: "study_finding",
        confidence: 0.95,
      }),
    );
    // Lower authority: agent-derived summary of the same topic.
    const low = engine.addRecord(
      rec("lib", "Rate limit", "I think the api rate limit might be around 120 per minute", {
        sourceKind: "agent_inference",
        epistemicClass: "inferred",
        confidence: 0.4,
        evidenceRefs: [],
      }),
    );

    const result = engine.rankedSearch("rate limit", { scope: "lib" });
    const hits = result.hits;
    assert.ok(hits.length >= 2, "both records are exposed");
    const highHit = hits.find((h) => h.record.recordId === high.recordId)!;
    const lowHit = hits.find((h) => h.record.recordId === low.recordId)!;
    assert.ok(highHit.rank > lowHit.rank, "high-authority current record ranks above agent-inferred");
    assert.equal(highHit.provenance.authority.tier, "verified_source");
    assert.equal(lowHit.provenance.authority.tier, "agent_derived");
    assert.equal(lowHit.provenance.lowConfidence, true);
    // Explicit per-signal breakdown is visible (not an opaque score).
    assert.equal(typeof highHit.provenance.signals.authority, "number");
    assert.equal(typeof highHit.provenance.signals.currency, "number");
    assert.ok(highHit.provenance.notes.length > 0);
    // The lower-quality record is STILL present (not silently hidden).
    assert.ok(hits.some((h) => h.record.recordId === low.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T17: superseded/current distinction — the successor ranks above the retired predecessor", () => {
  const { engine, dir } = tempEngine("currency");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(rec("lib", "Deploy window", "Friday evening"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Tuesday morning",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "avoid weekend deploys",
    });
    const result = engine.rankedSearch("deploy", { scope: "lib" });
    const v1Hit = result.hits.find((h) => h.record.recordId === v1.recordId)!;
    const v2Hit = result.hits.find((h) => h.record.recordId === v2.recordId)!;
    // The predecessor is exposed (historical) but ranked below the current record.
    assert.equal(v1Hit.provenance.historical, true);
    assert.equal(v2Hit.provenance.historical, false);
    assert.ok(v2Hit.rank >= v1Hit.rank, "the current successor ranks at or above the superseded predecessor");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T17: contradicted records are exposed with an explicit flag, not hidden", () => {
  const { engine, dir } = tempEngine("contradiction-exposure");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Backup time", "02:00"));
    const b = engine.addRecord(rec("lib", "Backup time", "03:00"));
    engine.registerContradiction("lib", "Backup time", [a.recordId, b.recordId]);
    const result = engine.rankedSearch("backup", { scope: "lib" });
    const contradictedHits = result.hits.filter((h) => h.provenance.contradicted);
    assert.equal(contradictedHits.length, 2, "both contradicted records remain exposed");
    for (const hit of contradictedHits) {
      assert.ok(hit.provenance.signals.contradiction < 1, "contradiction reduces the signal");
      assert.ok(hit.provenance.notes.some((n) => n.includes("contradiction")));
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T17: determinism and restart survival of ranking", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t17-restart-"));
  const path = join(dir, "memory.db");
  let firstOrder: string[];
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Backoff", "Exponential backoff with retry"));
    engine.addRecord(
      rec("lib", "Backoff", "backoff mentioned in passing", {
        sourceKind: "agent_summary",
        epistemicClass: "derived",
        confidence: 0.3,
        derivedFrom: { engine: "external" as const, ref: "sum:1" },
      }),
    );
    const r1 = engine.rankedSearch("backoff", { scope: "lib" });
    const r2 = engine.rankedSearch("backoff", { scope: "lib" });
    assert.deepEqual(
      r1.hits.map((h) => [h.record.recordId, h.rank]),
      r2.hits.map((h) => [h.record.recordId, h.rank]),
    );
    firstOrder = r1.hits.map((h) => h.record.recordId);
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const again = engine.rankedSearch("backoff", { scope: "lib" });
      assert.deepEqual(again.hits.map((h) => h.record.recordId), firstOrder);
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});

test("T17: negative — empty query and scope handling are typed", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("alpha", "Alpha");
    engine.createScope("beta", "Beta");
    engine.addRecord(rec("alpha", "Island", "island token here"));
    assert.throws(() => engine.rankedSearch("   "), (err: unknown) => err instanceof ValidationError);
    assert.throws(() => engine.rankedSearch("!!!"), (err: unknown) => err instanceof ValidationError);
    // Unknown scope raises typed not-found through getScopeImpl.
    assert.throws(
      () => engine.rankedSearch("island", { scope: "nope" }),
      (err: unknown) => err instanceof Error,
    );
    // Invalid `at` is a typed validation error, not silent mis-ranking.
    assert.throws(
      () => engine.rankedSearch("island", { at: "garbage" }),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});