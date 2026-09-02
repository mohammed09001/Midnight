/**
 * CHILD LOOP 3 verification — Task 12: revision and correction semantics.
 * Proves: user/authorized-engine corrections land as NEW immutable
 * revisions with actor + required reason; agents are refused direct
 * corrections; and historical provenance is NEVER silently mutated
 * (revision rows keep their original actor/method/sourceKind forever).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { CorrectionForbiddenError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t12-${name}-`));
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
    evidenceRefs: [{ engine: "external" as const, ref: "note:1" }],
  };
}

test("T12: user corrections append revisions with actor and required reason", () => {
  const { engine, dir } = tempEngine("user-correction");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Retry policy", "3 retries, 1s backoff"));
    // Missing/blank reason refused — corrections are never silent.
    assert.throws(
      () =>
        engine.reviseRecord(v1.recordId, {
          content: "5 retries",
          actor: { kind: "human", name: "kim" },
          method: "corrected",
        } as never),
      (err: unknown) => err instanceof ValidationError && err.message.includes("reason is required"),
    );
    assert.throws(
      () =>
        engine.reviseRecord(v1.recordId, {
          content: "5 retries",
          actor: { kind: "human", name: "kim" },
          method: "corrected",
          reason: "  ",
        }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Nothing written by the refused attempts.
    assert.equal(engine.getRecord(v1.recordId).revision, 1);

    const v2 = engine.reviseRecord(v1.recordId, {
      content: "5 retries, 2s backoff",
      actor: { kind: "human", name: "kim" },
      method: "corrected",
      reason: "ops tuned the retry budget",
    });
    assert.equal(v2.revision, 2);
    assert.equal(v2.createdAt, v1.createdAt, "createdAt immutable across correction");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T12: authorized-engine corrections are first-class and attributed", () => {
  const { engine, dir } = tempEngine("engine-correction");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Schema drift", "Column renamed in migration 12"));
    const v2 = engine.reviseRecord(v1.recordId, {
      content: "Column renamed in migration 12 (verified)",
      actor: { kind: "engine", name: "study_lineage_versioning" },
      method: "verified-correction",
      reason: "lineage verification pass",
    });
    assert.equal(v2.revision, 2);
    assert.equal(v2.provenance.actor.kind, "engine");
    const event = engine.listEvents(10).find((e) => e.type === "memory.record.revised");
    assert.equal((event!.payload as { actor: string }).actor, "engine:study_lineage_versioning");
    assert.equal((event!.payload as { reason: string }).reason, "lineage verification pass");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T12: THE CORE RULE — historical provenance is never silently mutated", () => {
  const { engine, dir } = tempEngine("provenance-immutability");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Deadline", "Beta ships Aug 30"));
    // A second actor corrects the content — the FIRST revision's provenance
    // must remain exactly as originally written.
    engine.reviseRecord(v1.recordId, {
      content: "Beta ships Sep 02",
      actor: { kind: "engine", name: "project_projection" },
      method: "corrected",
      reason: "schedule slip",
    });
    engine.reviseRecord(v1.recordId, {
      content: "Beta ships Sep 05",
      actor: { kind: "human", name: "alex" },
      method: "corrected",
      reason: "final slip",
    });

    const history = engine.getRecordHistory(v1.recordId);
    assert.equal(history.revisions.length, 3);
    // Revision 1: ORIGINAL provenance intact.
    const rev1 = history.revisions[0]!;
    assert.equal(rev1.provenance.actor.name, "kim");
    assert.equal(rev1.provenance.actor.kind, "human");
    assert.equal(rev1.provenance.method, "asserted");
    assert.equal(rev1.provenance.sourceKind, "user_note");
    assert.equal(rev1.content, "Beta ships Aug 30");
    // Revision 2: correcting engine attributed.
    assert.equal(history.revisions[1]!.provenance.actor.name, "project_projection");
    assert.equal(history.revisions[1]!.reason, "schedule slip");
    // Revision 3: current actor attributed.
    assert.equal(history.revisions[2]!.provenance.actor.name, "alex");
    // Append-log integrity confirms the chain was never rewritten.
    assert.equal(engine.checkAppendIntegrity().consistent, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T12: agents cannot correct directly — intake pipeline is their path", () => {
  const { engine, dir } = tempEngine("agent-refused");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Endpoint", "GET /users"));
    assert.throws(
      () =>
        engine.reviseRecord(v1.recordId, {
          content: "GET /v2/users",
          actor: { kind: "agent", name: "refactorer", agentType: "llm" },
          method: "corrected",
          reason: "api version bump observed",
        }),
      (err: unknown) => err instanceof CorrectionForbiddenError,
    );
    assert.equal(engine.getRecord(v1.recordId).revision, 1, "no partial state from refusal");
    // The agent's path: propose a candidate for policy-gated promotion.
    const candidate = engine.addCandidate({
      scope: "lib",
      kind: "fact",
      subject: "Endpoint",
      content: "GET /v2/users",
      actor: { kind: "agent", name: "refactorer", agentType: "llm" },
      method: "observed",
      epistemicClass: "inferred",
      confidence: 0.7,
      sourceKind: "agent_inference",
      reason: "observed new endpoint in traffic",
      caller: { kind: "agent", name: "refactorer" },
    });
    assert.equal(candidate.status, "open");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T12: corrections survive restart with full history", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t12-restart-"));
  const path = join(dir, "memory.db");
  let recordId: string;
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(fact("lib", "Region", "eu-west-1"));
    engine.reviseRecord(v1.recordId, {
      content: "eu-central-1",
      actor: { kind: "human", name: "kim" },
      method: "corrected",
      reason: "migration",
    });
    recordId = v1.recordId;
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const history = engine.getRecordHistory(recordId);
      assert.equal(history.revisions.length, 2);
      assert.equal(history.revisions[0]!.provenance.actor.name, "kim");
      assert.equal(history.revisions[1]!.content, "eu-central-1");
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});
