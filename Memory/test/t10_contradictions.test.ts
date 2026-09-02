/**
 * CHILD LOOP 1 verification — Task 10: contradiction detection and
 * grouping. Proves: deterministic detection of explicit incompatible
 * claims (same subject, different content, overlapping scope/time),
 * preservation of BOTH claims as a contradiction set pending resolution,
 * attributed resolution (winner-supersedes or retract), agent refusal,
 * and restart survival.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import {
  ConflictError,
  PromotionForbiddenError,
  ValidationError,
} from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t10-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function fact(scope: string, subject: string, content: string, overrides: Record<string, unknown> = {}) {
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

test("T10: detection finds incompatible claims on the same subject with overlapping time", () => {
  const { engine, dir } = tempEngine("detect");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(fact("lib", "Release cadence", "Weekly on Tuesday"));
    const b = engine.addRecord(fact("lib", "Release cadence", "Weekly on Wednesday"));
    // Unrelated subject — no contradiction.
    const c = engine.addRecord(fact("lib", "Owner", "Kim owns releases"));

    const pairs = engine.detectContradictions("lib");
    assert.equal(pairs.length, 1);
    const pair = pairs[0]!;
    assert.deepEqual(
      [pair.recordIdA, pair.recordIdB].sort(),
      [a.recordId, b.recordId].sort(),
    );
    assert.equal(pair.subject, "Release cadence");
    assert.ok(pair.overlapStart.length > 0);
    void c;
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T10: detection exclusions — identical content, supersession links, non-overlap", async () => {
  const { engine, dir } = tempEngine("exclusions");
  try {
    engine.createScope("lib", "Library");
    // Identical content on the same subject: duplicate, not contradiction.
    engine.addRecord(fact("lib", "Same", "Identical claim"));
    engine.addRecord(fact("lib", "Same", "Identical claim"));
    // Disjoint validity windows: no time overlap.
    engine.addRecord(
      fact("lib", "Windowed", "Old rule", {
        validFrom: "2026-08-01T00:00:00.000Z",
        validUntil: "2026-08-10T00:00:00.000Z",
      }),
    );
    engine.addRecord(
      fact("lib", "Windowed", "New rule", {
        validFrom: "2026-08-20T00:00:00.000Z",
        validUntil: "2026-09-01T00:00:00.000Z",
      }),
    );
    assert.equal(engine.detectContradictions("lib").length, 0);

    // Supersession-linked pair (same subject, different content): lineage,
    // not contradiction.
    const old = engine.addRecord(
      fact("lib", "Superseded claim", "First version", {
        observedAt: "2026-08-25T00:00:00.000Z",
      }),
    );
    engine.supersedeRecord(old.recordId, {
      content: "Second version",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "correction",
    });
    assert.equal(engine.detectContradictions("lib").length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T10: grouping preserves BOTH claims and awaits resolution", () => {
  const { engine, dir } = tempEngine("grouping");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(fact("lib", "Port", "API runs on 8080"));
    const b = engine.addRecord(fact("lib", "Port", "API runs on 9090"));
    const group = engine.registerContradiction("lib", "Port", [a.recordId, b.recordId]);
    assert.equal(group.status, "open");
    assert.equal(group.resolution, null);

    // Both claims remain intact and queryable — nothing was destroyed.
    assert.equal(engine.getRecord(a.recordId).status, "active");
    assert.equal(engine.getRecord(b.recordId).status, "active");
    assert.equal(engine.getRecord(a.recordId).content, "API runs on 8080");

    // Grouped pairs are excluded from re-detection but listed as open.
    assert.equal(engine.detectContradictions("lib").length, 0);
    const open = engine.listOpenContradictions("lib");
    assert.equal(open.length, 1);
    assert.equal(open[0]!.groupId, group.groupId);
    // The pair detection would still see them after resolution-time
    // exclusion via group membership — verified implicitly above.
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T10: resolution by winner-supersedes retains lineage and closes the group", () => {
  const { engine, dir } = tempEngine("resolve-supersede");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(fact("lib", "Port", "API runs on 8080"));
    const b = engine.addRecord(fact("lib", "Port", "API runs on 9090"));
    const group = engine.registerContradiction("lib", "Port", [a.recordId, b.recordId]);

    const resolved = engine.resolveContradiction(group.groupId, {
      action: "supersede",
      winnerRecordId: b.recordId,
      actor: { kind: "human", name: "kim" },
      reason: "port migrated in the infra change",
    });
    assert.equal(resolved.status, "resolved");
    assert.equal(resolved.resolution?.action, "supersede");
    assert.equal(resolved.resolution?.winnerRecordId, b.recordId);

    // Loser was superseded BY the winner (lineage, not deletion).
    const loser = engine.getRecord(a.recordId);
    assert.equal(loser.status, "superseded");
    assert.equal(loser.supersededById, b.recordId);
    assert.equal(loser.supersededReason, "port migrated in the infra change");
    // Winner still active.
    assert.equal(engine.getRecord(b.recordId).status, "active");
    // Event with attribution.
    const event = engine.listEvents(10).find((e) => e.type === "memory.contradiction.resolved");
    assert.ok(event !== undefined);
    assert.equal((event!.payload as { actor: string }).actor, "human:kim");

    // Double resolution is a conflict.
    assert.throws(
      () =>
        engine.resolveContradiction(group.groupId, {
          action: "retract",
          winnerRecordId: b.recordId,
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

test("T10: resolution by retraction closes the group; negatives are typed", () => {
  const { engine, dir } = tempEngine("resolve-retract");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(fact("lib", "Color", "Logo is blue"));
    const b = engine.addRecord(fact("lib", "Color", "Logo is green"));
    const group = engine.registerContradiction("lib", "Color", [a.recordId, b.recordId]);

    assert.throws(
      () =>
        engine.resolveContradiction(group.groupId, {
          action: "retract",
          winnerRecordId: b.recordId,
          actor: { kind: "agent", name: "auto-resolver" },
          reason: "bot decision",
        }),
      (err: unknown) => err instanceof PromotionForbiddenError,
      "agents cannot resolve contradictions",
    );
    assert.throws(
      () =>
        engine.resolveContradiction(group.groupId, {
          action: "supersede",
          winnerRecordId: "mem_not_in_group",
          actor: { kind: "human", name: "kim" },
          reason: "x",
        }),
      (err: unknown) => err instanceof ValidationError,
    );

    const resolved = engine.resolveContradiction(group.groupId, {
      action: "retract",
      winnerRecordId: b.recordId,
      actor: { kind: "human", name: "kim" },
      reason: "green is correct per brand guide",
    });
    assert.equal(resolved.status, "resolved");
    assert.equal(engine.getRecord(a.recordId).status, "retracted");
    assert.equal(engine.getRecord(b.recordId).status, "active");
    // The retraction is a reasoned revision in the append log.
    const loserHistory = engine.getRecordHistory(a.recordId);
    assert.match(loserHistory.revisions[1]!.reason ?? "", /contradiction .* resolved/);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T10: groups and resolution survive restarts", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t10-restart-"));
  const path = join(dir, "memory.db");
  let groupId: string;
  let winnerId: string;
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const a = engine.addRecord(fact("lib", "Timeout", "Timeout is 30s"));
    const b = engine.addRecord(fact("lib", "Timeout", "Timeout is 60s"));
    groupId = engine.registerContradiction("lib", "Timeout", [a.recordId, b.recordId]).groupId;
    winnerId = b.recordId;
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      assert.equal(engine.listOpenContradictions("lib").length, 1);
      engine.resolveContradiction(groupId, {
        action: "supersede",
        winnerRecordId: winnerId,
        actor: { kind: "human", name: "kim" },
        reason: "confirmed with infra",
      });
      assert.equal(engine.listOpenContradictions("lib").length, 0);
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});
