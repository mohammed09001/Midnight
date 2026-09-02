/**
 * CHILD LOOP 2 verification — Task 11: supersession without destructive
 * overwrite. Proves: a newer record supersedes an older one while retaining
 * lineage (chain + immutable revisions), provenance, historical
 * queryability (as-of), and an EXPLICIT reason recorded on the link, the
 * revision log, and the event.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t11-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function fact(scope: string, subject: string, content: string) {
  return {
    scope,
    kind: "decision" as const,
    subject,
    content,
    actor: { kind: "human" as const, name: "kim" },
    method: "decided",
    epistemicClass: "observed" as const,
    confidence: 0.95,
    sourceKind: "user_note" as const,
    evidenceRefs: [{ engine: "external" as const, ref: "note:decisions" }],
  };
}

test("T11: supersession requires an explicit reason and records it everywhere", () => {
  const { engine, dir } = tempEngine("reason");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Auth provider", "Auth0 with RS256"));
    // Missing reason → refused before any write.
    assert.throws(
      () =>
        engine.supersedeRecord(v1.recordId, {
          content: "Clerk with RS256",
          actor: { kind: "human", name: "kim" },
          method: "decided",
          reason: "",
        }),
      (err: unknown) => err instanceof ValidationError && err.message.includes("reason is required"),
    );
    assert.equal(engine.getRecord(v1.recordId).status, "active", "nothing written without reason");

    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Clerk with RS256",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "migrated auth providers",
    });
    // Reason on the superseded record row…
    assert.equal(engine.getRecord(v1.recordId).supersededReason, "migrated auth providers");
    // …in the successor's initial revision row…
    const history = engine.getRecordHistory(v2.recordId);
    assert.match(history.revisions[0]!.reason ?? "", /^supersedes mem_.*: migrated auth providers$/);
    // …in the superseded predecessor's chain entry…
    const v1Chain = engine.getRecordHistory(v1.recordId).chain.find((c) => c.recordId === v1.recordId);
    assert.equal(v1Chain!.supersededReason, "migrated auth providers");
    // …and in the event stream.
    const event = engine.listEvents(10).find((e) => e.type === "memory.record.superseded");
    assert.equal((event!.payload as { reason: string }).reason, "migrated auth providers");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T11: non-destructive — predecessor content, provenance, and timestamps untouched", () => {
  const { engine, dir } = tempEngine("non-destructive");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(
      fact("lib", "Auth provider", "Auth0 with RS256"),
    );
    const v1Before = engine.getRecord(v1.recordId);
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Clerk with RS256",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "migrated auth providers",
    });
    const v1After = engine.getRecord(v1.recordId);
    // Only status/lineage fields changed; the historical truth did not.
    assert.equal(v1After.content, "Auth0 with RS256");
    assert.equal(v1After.contentHash, v1Before.contentHash);
    assert.equal(v1After.provenance.actor.name, v1Before.provenance.actor.name);
    assert.equal(v1After.provenance.sourceKind, "user_note", "provenance retained across supersession");
    assert.equal(v1After.createdAt, v1Before.createdAt);
    assert.equal(v1After.observedAt, v1Before.observedAt);
    assert.equal(v1After.revision, v1Before.revision, "revision count untouched by supersession");
    // The successor carries its own identity and inherited provenance shape.
    assert.equal(v2.supersedesId, v1.recordId);
    assert.equal(v2.provenance.sourceKind, "user_note", "provenance retained across supersession");
    assert.notEqual(v2.recordId, v1.recordId);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T11: historical queryability — as-of still shows the predecessor before invalidation", async () => {
  const { engine, dir } = tempEngine("historical");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Backup schedule", "Daily at 02:00"));
    await new Promise((r) => setTimeout(r, 5));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Daily at 03:00",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "shifted to off-peak",
    });
    // Belief 1ms before invalidation: v1.
    const justBefore = new Date(Date.parse(v1.supersededAt ?? v2.createdAt) - 1).toISOString();
    const before = engine.queryRecordsAsOf({ scope: "lib", asOf: justBefore });
    assert.ok(before.some((r) => r.recordId === v1.recordId));
    assert.equal(before.find((r) => r.recordId === v1.recordId)!.content, "Daily at 02:00");
    // Now: v2.
    const now2 = engine.queryRecordsAsOf({ scope: "lib", asOf: new Date().toISOString() });
    assert.ok(now2.some((r) => r.recordId === v2.recordId));
    assert.ok(!now2.some((r) => r.recordId === v1.recordId));
    // The full chain remains reachable from the newest entry.
    assert.deepEqual(
      engine.getRecordHistory(v2.recordId).chain.map((c) => c.recordId),
      [v1.recordId, v2.recordId],
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T11: agents cannot supersede directly — they propose via intake instead", () => {
  const { engine, dir } = tempEngine("agent-refused");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Cache TTL", "TTL 60s"));
    assert.throws(
      () =>
        engine.supersedeRecord(v1.recordId, {
          content: "TTL 120s",
          actor: { kind: "agent", name: "auto-tuner", agentType: "llm" },
          method: "tuned",
          reason: "hit rate improved",
        }),
      (err: unknown) => err instanceof Error,
    );
    assert.equal(engine.getRecord(v1.recordId).status, "active");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
