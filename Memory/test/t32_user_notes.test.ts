/**
 * CHILD LOOP 1 verification — Task 32: Integrate Project user notes.
 * Proves: explicit user-authored notes/decisions are FIRST-CLASS memory
 * records (direct, durable, searchable) within their declared scope; the
 * producing actor MUST be human (agents/engines use the candidate pipeline);
 * a user DECISION carries STRONGER subjective authority (`user_decision` tier,
 * above `user_reported`) while a note carries `user_reported`; the observed-
 * requires-evidence authority rule stays intact; idempotency works; and the
 * versioned contract dispatch works.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t32-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

const KIM = { kind: "human" as const, name: "kim" };

test("T32: a user note becomes a first-class durable record with user_reported authority", () => {
  const { engine, dir } = tempEngine("note");
  try {
    engine.createScope("lib", "Library");
    const record = engine.addUserNote({
      scope: "lib",
      subject: "Release preference",
      content: "I prefer Tuesday releases",
      kind: "note",
      actor: KIM,
    });
    assert.equal(record.status, "active");
    assert.equal(record.kind, "note");
    assert.equal(record.provenance.sourceKind, "user_note");
    assert.equal(record.provenance.actor.name, "kim");
    assert.equal(record.epistemicClass, "derived");
    assert.equal(record.scopeId, engine.getScope("lib").scopeId);
    // First-class: durable and searchable in the declared scope.
    assert.equal(engine.searchRecords({ scope: "lib", exactSubject: "Release preference" }).length, 1);
    // Authority: user_reported.
    assert.equal(engine.explainAuthority(record.recordId).tier, "user_reported");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T32: a user DECISION carries STRONGER subjective authority (user_decision tier)", () => {
  const { engine, dir } = tempEngine("decision");
  try {
    engine.createScope("lib", "Library");
    const decision = engine.addUserNote({
      scope: "lib",
      subject: "Region",
      content: "We deploy to eu-central-1",
      kind: "decision",
      actor: KIM,
    });
    const note = engine.addUserNote({
      scope: "lib",
      subject: "Preference",
      content: "I prefer Tuesday",
      kind: "note",
      actor: KIM,
    });
    assert.equal(decision.kind, "decision");
    assert.equal(decision.provenance.sourceKind, "user_decision");
    assert.equal(note.provenance.sourceKind, "user_note");
    // Stronger subjective authority: the decision tier ranks above user_reported.
    assert.equal(engine.explainAuthority(decision.recordId).tier, "user_decision");
    assert.equal(engine.explainAuthority(note.recordId).tier, "user_reported");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T32: non-human actors are refused — agents/engines use the candidate pipeline", () => {
  const { engine, dir } = tempEngine("non-human");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.addUserNote({ scope: "lib", subject: "X", content: "x", kind: "note", actor: { kind: "agent", name: "worker-a" } }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.addUserNote({ scope: "lib", subject: "X", content: "x", kind: "note", actor: { kind: "engine", name: "repository_sync" } }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T32: the observed-requires-evidence authority rule stays intact on this surface", () => {
  const { engine, dir } = tempEngine("epistemic-honesty");
  try {
    engine.createScope("lib", "Library");
    // A user declaring "observed" still needs evidence (authority invariant).
    assert.throws(
      () => engine.addUserNote({ scope: "lib", subject: "X", content: "x", kind: "note", actor: KIM, epistemicClass: "observed" }),
      (err: unknown) => err instanceof ValidationError && err.message.includes("evidenceRefs"),
    );
    // With evidence, observed works.
    const record = engine.addUserNote({
      scope: "lib", subject: "Observation", content: "noticed under load", kind: "note", actor: KIM,
      epistemicClass: "observed",
      evidenceRefs: [{ engine: "external", ref: "run:1" }],
    });
    assert.equal(record.epistemicClass, "observed");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T32: idempotency works on the user-note surface", () => {
  const { engine, dir } = tempEngine("idempotency");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addUserNote({ scope: "lib", subject: "Note", content: "once", kind: "note", actor: KIM, idempotencyKey: "user:note-1" });
    const b = engine.addUserNote({ scope: "lib", subject: "Note", content: "once", kind: "note", actor: KIM, idempotencyKey: "user:note-1" });
    assert.equal(a.recordId, b.recordId);
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T32: versioned contract — memory.user.note through the dispatcher", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    const envelope = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.user.note",
      request: { scope: "lib", kind: "decision", subject: "Cadence", content: "release every two weeks", actor: KIM },
    });
    assert.equal(envelope.ok, true);
    if (envelope.ok) {
      const result = envelope.result as { record: { kind: string; provenance: { sourceKind: string } } };
      assert.equal(result.record.kind, "decision");
      assert.equal(result.record.provenance.sourceKind, "user_decision");
    }
    // An agent actor through the contract is a typed error, never a silent accept.
    const agent = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.user.note",
      request: { scope: "lib", subject: "X", content: "x", actor: { kind: "agent", name: "worker" } },
    });
    assert.equal(agent.ok, false);
    if (!agent.ok) assert.equal(agent.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});