/**
 * CHILD LOOP 2 verification — Task 8: Memory candidate intake pipeline.
 * Proves: proposals enter a candidate stream (never directly durable),
 * intake authorization (allowlist of caller keys), required reason +
 * recorded producer/caller/evidence/requested scope, stream listing, and
 * explicit rejection.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { IntakeUnauthorizedError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t8-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function proposal(scope: string) {
  return {
    scope,
    kind: "fact" as const,
    subject: "Bundle size",
    content: "Bundle grew 30% after the analytics dependency",
    actor: { kind: "agent" as const, name: "analyzer", agentType: "llm" },
    method: "inferred",
    epistemicClass: "inferred" as const,
    confidence: 0.6,
    sourceKind: "agent_inference" as const,
    reason: "flagged during release review",
    caller: { kind: "engine" as const, name: "project_projection" },
  };
}

test("T8: proposals land in the candidate stream, never directly in durable knowledge", () => {
  const { engine, dir } = tempEngine("stream-not-durable");
  try {
    engine.createScope("lib", "Library");
    const candidate = engine.addCandidate(proposal("lib"));
    assert.equal(candidate.status, "open");
    assert.ok(candidate.candidateId.startsWith("cand_"));
    // Nothing leaked into durable records.
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
    // Producer, reason, caller, evidence, scope all recorded.
    assert.equal(candidate.provenance.actor.name, "analyzer");
    assert.equal(candidate.reason, "flagged during release review");
    assert.equal(candidate.caller?.kind, "engine");
    assert.equal(candidate.caller?.name, "project_projection");
    assert.equal(candidate.scopeId, engine.getScope("lib").scopeId);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T8: reason is required — proposals must say why they exist", () => {
  const { engine, dir } = tempEngine("reason-required");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.addCandidate({ ...proposal("lib"), reason: "" }),
      (err: unknown) => err instanceof ValidationError && err.message.includes("reason is required"),
    );
    assert.throws(
      () => engine.addCandidate({ ...proposal("lib"), reason: "   " }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.equal(engine.listCandidates({ scope: "lib" }).length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T8: open intake by default; allowlist mode admits only authorized callers", () => {
  const { engine, dir } = tempEngine("authorization");
  try {
    engine.createScope("lib", "Library");
    // Default: open — any caller may propose.
    const openScoped = engine.addCandidate(proposal("lib"));
    assert.equal(openScoped.status, "open");

    // Lock intake down to two callers.
    const scope = engine.setScopeIntakePolicy("lib", {
      mode: "allowlist",
      allow: ["engine:repository_sync", "human:kim"],
    });
    assert.equal(scope.intakePolicy.mode, "allowlist");

    // Authorized caller passes.
    const authorized = engine.addCandidate({
      ...proposal("lib"),
      subject: "Authorized proposal",
      caller: { kind: "engine", name: "repository_sync" },
    });
    assert.equal(authorized.status, "open");

    // Unauthorized caller is refused with a typed code.
    assert.throws(
      () =>
        engine.addCandidate({
          ...proposal("lib"),
          subject: "Unauthorized",
          caller: { kind: "engine", name: "rogue_engine" },
        }),
      (err: unknown) => err instanceof IntakeUnauthorizedError,
    );
    assert.throws(
      () =>
        engine.addCandidate({
          ...proposal("lib"),
          subject: "No caller at all",
          caller: undefined,
        }),
      (err: unknown) => err instanceof IntakeUnauthorizedError,
    );
    // Nothing from the rejected attempts persisted.
    assert.equal(
      engine.listCandidates({ scope: "lib", status: "open" }).length,
      2, // open-mode proposal + authorized one
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T8: stream lists oldest-first, filterable by status and scope", () => {
  const { engine, dir } = tempEngine("stream-order");
  try {
    engine.createScope("alpha", "Alpha");
    engine.createScope("beta", "Beta");
    const c1 = engine.addCandidate({ ...proposal("alpha"), subject: "First" });
    const c2 = engine.addCandidate({ ...proposal("alpha"), subject: "Second" });
    engine.addCandidate({ ...proposal("beta"), subject: "Other scope" });

    const stream = engine.listCandidates({ scope: "alpha", status: "open" });
    assert.deepEqual(
      stream.map((c) => c.candidateId),
      [c1.candidateId, c2.candidateId],
    );
    // Promote one: open stream shrinks, all-stream retains.
    engine.promoteCandidate(c1.candidateId, {
      actor: { kind: "human", name: "kim" },
    });
    assert.equal(engine.listCandidates({ scope: "alpha", status: "open" }).length, 1);
    assert.equal(engine.listCandidates({ scope: "alpha", status: "promoted" }).length, 1);
    assert.equal(engine.listCandidates({ scope: "alpha" }).length, 2);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T8: explicit rejection removes from the open stream with reason and actor", () => {
  const { engine, dir } = tempEngine("reject");
  try {
    engine.createScope("lib", "Library");
    const candidate = engine.addCandidate(proposal("lib"));
    assert.throws(
      () =>
        engine.rejectCandidate(candidate.candidateId, {
          actor: { kind: "human", name: "kim" },
          reason: "  ",
        }),
      (err: unknown) => err instanceof ValidationError,
    );
    // Agents cannot reject either (stream decisions are non-agent).
    assert.throws(
      () =>
        engine.rejectCandidate(candidate.candidateId, {
          actor: { kind: "agent", name: "triage-bot" },
          reason: "bot says no",
        }),
      (err: unknown) => err instanceof Error,
    );
    const rejected = engine.rejectCandidate(candidate.candidateId, {
      actor: { kind: "human", name: "kim" },
      reason: "duplicate of an existing record",
    });
    assert.equal(rejected.status, "rejected");
    assert.equal(engine.listCandidates({ scope: "lib", status: "open" }).length, 0);
    const event = engine.listEvents(10).find((e) => e.type === "memory.candidate.rejected");
    assert.ok(event !== undefined);
    assert.equal((event!.payload as { reason: string }).reason, "duplicate of an existing record");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T8: intake policy and candidates survive restarts", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t8-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.setScopeIntakePolicy("lib", { mode: "allowlist", allow: ["engine:project_projection"] });
    engine.addCandidate(proposal("lib"));
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const scope = engine.getScope("lib");
      assert.deepEqual(scope.intakePolicy, {
        mode: "allowlist",
        allow: ["engine:project_projection"],
      });
      assert.equal(engine.listCandidates({ scope: "lib" }).length, 1);
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});
