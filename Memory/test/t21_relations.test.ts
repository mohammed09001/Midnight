/**
 * CHILD LOOP 1 verification — Task 21: typed Memory relationships.
 * Proves: the bounded relation vocabulary (related, depends_on, supports,
 * contradicts, derived_from, applies_to, learned_from), attributed
 * provenance on every relation, attributed add/remove management with typed
 * failures (self/tombstone/cross-scope targets, duplicates, not-found), the
 * supersession chain surfaced through the relations view, and persistence
 * across restart.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { ConflictError, NotFoundError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t21-${name}-`));
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

const HUMAN = { kind: "human" as const, name: "kim" };

test("T21: every bounded relation type is accepted and stamped with provenance", () => {
  const { engine, dir } = tempEngine("types");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Rate limit", "120 rpm"));
    const b = engine.addRecord(rec("lib", "Gateway", "api gateway"));
    const c = engine.addRecord(rec("lib", "Lesson", "learned lesson"));

    const related = engine.addRelation(a.recordId, { type: "related", target: b.recordId, actor: HUMAN, method: "linked" });
    const derived = engine.addRelation(a.recordId, { type: "derived_from", target: c.recordId, actor: HUMAN, method: "derived" });
    const supports = engine.addRelation(a.recordId, { type: "supports", target: c.recordId, actor: HUMAN, method: "cited" });
    const applies = engine.addRelation(a.recordId, { type: "applies_to", target: "entity:component:gateway", actor: HUMAN, method: "classified" });
    const learned = engine.addRelation(a.recordId, { type: "learned_from", target: "engine:study_document:lesson-9", actor: HUMAN, method: "extracted" });
    const contradicts = engine.addRelation(b.recordId, { type: "contradicts", target: c.recordId, actor: HUMAN, method: "detected" });
    const depends = engine.addRelation(b.recordId, { type: "depends_on", target: a.recordId, actor: HUMAN, method: "analyzed" });

    // Each add returns the updated related view containing the attributed hint.
    const outgoingA = related.outgoing.concat(derived.outgoing, supports.outgoing, applies.outgoing, learned.outgoing);
    assert.ok(outgoingA.some((h) => h.type === "related" && h.target === b.recordId));
    assert.ok(outgoingA.some((h) => h.type === "derived_from" && h.target === c.recordId));
    assert.ok(outgoingA.some((h) => h.type === "supports" && h.target === c.recordId));
    assert.ok(outgoingA.some((h) => h.type === "applies_to" && h.target === "entity:component:gateway"));
    assert.ok(outgoingA.some((h) => h.type === "learned_from" && h.target === "engine:study_document:lesson-9"));
    assert.ok(contradicts.outgoing.some((h) => h.type === "contradicts"));
    assert.ok(depends.outgoing.some((h) => h.type === "depends_on"));

    // Every hint carries provenance: actor, method, capturedAt.
    const final = engine.getRecord(a.recordId);
    for (const hint of final.relationHints) {
      assert.ok(hint.provenance !== undefined, `relation ${hint.type} has provenance`);
      assert.equal(hint.provenance!.actor.name, "kim");
      assert.ok(hint.provenance!.method.length > 0);
      assert.ok(!Number.isNaN(Date.parse(hint.provenance!.capturedAt)), "capturedAt is a timestamp");
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T21: attributed add/remove with typed failures — cross-scope, self, tombstone, duplicate, not-found", () => {
  const { engine, dir } = tempEngine("failures");
  try {
    engine.createScope("lib", "Library");
    engine.createScope("other", "Other");
    const a = engine.addRecord(rec("lib", "A", "alpha"));
    const b = engine.addRecord(rec("lib", "B", "beta"));
    const foreign = engine.addRecord(rec("other", "C", "gamma"));

    // Cross-scope record target is refused.
    assert.throws(
      () => engine.addRelation(a.recordId, { type: "related", target: foreign.recordId, actor: HUMAN, method: "x" }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Self-relation is refused.
    assert.throws(
      () => engine.addRelation(a.recordId, { type: "related", target: a.recordId, actor: HUMAN, method: "x" }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Malformed target format is refused.
    assert.throws(
      () => engine.addRelation(a.recordId, { type: "related", target: "not-a-valid-target", actor: HUMAN, method: "x" }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Unknown relation type is refused.
    assert.throws(
      () => engine.addRelation(a.recordId, { type: "bogus" as never, target: b.recordId, actor: HUMAN, method: "x" }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Tombstoned source record refuses relations.
    const doomed = engine.addRecord(rec("lib", "Doomed", "doomed"));
    engine.deleteRecord(doomed.recordId, { actor: HUMAN, reason: "scrub" });
    assert.throws(
      () => engine.addRelation(doomed.recordId, { type: "related", target: a.recordId, actor: HUMAN, method: "x" }),
      (err: unknown) => err instanceof ConflictError,
    );

    // Duplicate (type+target) is a conflict.
    engine.addRelation(a.recordId, { type: "related", target: b.recordId, actor: HUMAN, method: "x" });
    assert.throws(
      () => engine.addRelation(a.recordId, { type: "related", target: b.recordId, actor: HUMAN, method: "y" }),
      (err: unknown) => err instanceof ConflictError,
    );

    // Remove works and is attributed; removing a missing relation is not-found.
    const after = engine.removeRelation(a.recordId, { type: "related", target: b.recordId });
    assert.ok(!after.outgoing.some((h) => h.type === "related" && h.target === b.recordId));
    assert.throws(
      () => engine.removeRelation(a.recordId, { type: "related", target: b.recordId }),
      (err: unknown) => err instanceof NotFoundError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T21: the relations view surfaces the canonical supersession chain", () => {
  const { engine, dir } = tempEngine("supersession");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(rec("lib", "Deploy window", "Friday"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Tuesday",
      actor: HUMAN,
      method: "decided",
      reason: "schedule change",
    });
    // The memory.related contract surfaces the chain (supersedes/supersededBy).
    const relatedV1 = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.related",
      request: { recordId: v1.recordId },
    });
    assert.equal(relatedV1.ok, true);
    if (relatedV1.ok) {
      const result = relatedV1.result as { supersedes: string[]; supersededBy: string[] };
      assert.deepEqual(result.supersedes, []);
      assert.deepEqual(result.supersededBy, [v2.recordId]);
    }
    const relatedV2 = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.related",
      request: { recordId: v2.recordId },
    });
    if (relatedV2.ok) {
      const result = relatedV2.result as { supersedes: string[]; supersededBy: string[] };
      assert.deepEqual(result.supersedes, [v1.recordId]);
      assert.deepEqual(result.supersededBy, []);
    }
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T21: relations set at record creation accept the new types and provenance", () => {
  const { engine, dir } = tempEngine("creation");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "A", "alpha"));
    const b = engine.addRecord(rec("lib", "B", "beta", {
      relationHints: [
        { type: "derived_from", target: a.recordId, provenance: { actor: HUMAN, method: "extracted", capturedAt: "2026-08-01T00:00:00.000Z" } },
        { type: "applies_to", target: "entity:technology:sqlite" },
      ],
    }));
    const hints = engine.getRecord(b.recordId).relationHints;
    assert.ok(hints.some((h) => h.type === "derived_from" && h.provenance !== undefined));
    assert.ok(hints.some((h) => h.type === "applies_to" && h.target === "entity:technology:sqlite"));
    // Inline provenance without a valid capturedAt is refused.
    assert.throws(
      () => engine.addRecord(rec("lib", "C", "gamma", {
        relationHints: [{ type: "related", target: a.recordId, provenance: { actor: HUMAN, method: "x", capturedAt: "not-a-time" } }],
      })),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.addRecord(rec("lib", "D", "delta", {
        relationHints: [{ type: "related", target: a.recordId, provenance: { actor: HUMAN, method: "x" } as never }],
      })),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T21: relations survive restart", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t21-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "A", "alpha"));
    const b = engine.addRecord(rec("lib", "B", "beta"));
    engine.addRelation(a.recordId, { type: "supports", target: b.recordId, actor: HUMAN, method: "cited" });
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const records = engine.searchRecords({ scope: "lib", contentContains: "alpha" });
      assert.equal(records.length, 1);
      const hint = records[0]!.relationHints.find((h) => h.type === "supports");
      assert.ok(hint !== undefined, "relation persisted across restart");
      assert.equal(hint!.provenance!.actor.name, "kim");
      assert.equal(hint!.provenance!.method, "cited");
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});