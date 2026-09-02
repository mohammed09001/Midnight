/**
 * CHILD LOOP 3 verification — Task 9: deterministic promotion policies.
 * Proves: three deterministic policies (explicit_user_decision,
 * verified_study_fact, repeated_evidence_backed_lesson), determinism,
 * policy gating on every promotion, and the structural rule that agents
 * can propose but can NEVER promote (or reject).
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
} from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t9-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function candidateInput(scope: string, overrides: Record<string, unknown> = {}) {
  return {
    scope,
    kind: "fact" as const,
    subject: "Lesson",
    content: "Cache stamps are rebuildable",
    actor: { kind: "agent" as const, name: "analyzer", agentType: "llm" },
    method: "inferred",
    epistemicClass: "inferred" as const,
    confidence: 0.6,
    sourceKind: "agent_inference" as const,
    reason: "proposed lesson",
    ...overrides,
  };
}

test("T9: verified_study_fact — study finding observed with evidence promotes deterministically", () => {
  const { engine, dir } = tempEngine("verified-study");
  try {
    engine.createScope("lib", "Library");
    const candidate = engine.addCandidate(
      candidateInput("lib", {
        sourceKind: "study_finding",
        epistemicClass: "observed",
        confidence: 0.95,
        method: "extracted",
        evidenceRefs: [{ engine: "study_document", ref: "doc:study-3#f1" }],
      }),
    );
    const assessment = engine.evaluatePromotion(candidate.candidateId);
    assert.equal(assessment.eligible, true);
    assert.deepEqual(assessment.matchedPolicies, ["verified_study_fact"]);
    // Auto-path: exactly one matched policy → promotion without explicit policy.
    const record = engine.promoteCandidate(candidate.candidateId, {
      actor: { kind: "engine", name: "study_document" },
    });
    assert.equal(record.status, "active");
    const event = engine.listEvents(10).find((e) => e.type === "memory.candidate.promoted");
    assert.equal((event!.payload as { policy: string }).policy, "verified_study_fact");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T9: verified_study_fact is strict — inference or non-study sources never match", () => {
  const { engine, dir } = tempEngine("verified-strict");
  try {
    engine.createScope("lib", "Library");
    // Study finding but claimed as inferred → no match.
    const inferred = engine.addCandidate(
      candidateInput("lib", {
        sourceKind: "study_finding",
        epistemicClass: "inferred",
        evidenceRefs: [{ engine: "study_document", ref: "doc:study-3#f1" }],
      }),
    );
    const a1 = engine.evaluatePromotion(inferred.candidateId);
    assert.equal(a1.eligible, false);
    assert.deepEqual(a1.matchedPolicies, []);
    // Observed via a human note (not a study finding) → no study-fact match.
    const humanObserved = engine.addCandidate(
      candidateInput("lib", {
        subject: "Human observed claim",
        sourceKind: "user_note",
        epistemicClass: "observed",
        evidenceRefs: [{ engine: "external", ref: "note:9" }],
      }),
    );
    assert.equal(engine.evaluatePromotion(humanObserved.candidateId).eligible, false);
    // Non-matching candidates require a human decision to promote.
    assert.throws(
      () =>
        engine.promoteCandidate(inferred.candidateId, {
          actor: { kind: "engine", name: "study_document" },
        }),
      (err: unknown) => err instanceof ConflictError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T9: repeated_evidence_backed_lesson — repetition by distinct evidence or re-proposals", () => {
  const { engine, dir } = tempEngine("repeated");
  try {
    engine.createScope("lib", "Library");
    // Two DISTINCT evidence refs on one candidate → repeat signal.
    const multiEvidence = engine.addCandidate(
      candidateInput("lib", {
        subject: "Multi-evidence lesson",
        evidenceRefs: [
          { engine: "study_document", ref: "doc:a" },
          { engine: "repository_sync", ref: "repo:b" },
        ],
      }),
    );
    const a = engine.evaluatePromotion(multiEvidence.candidateId);
    assert.ok(a.matchedPolicies.includes("repeated_evidence_backed_lesson"));

    // One candidate with one ref, proposed twice with same subject+content.
    const first = engine.addCandidate(
      candidateInput("lib", {
        subject: "Repeated lesson",
        evidenceRefs: [{ engine: "external", ref: "note:1" }],
      }),
    );
    const single = engine.evaluatePromotion(first.candidateId);
    assert.ok(!single.matchedPolicies.includes("repeated_evidence_backed_lesson"));
    const second = engine.addCandidate(
      candidateInput("lib", {
        subject: "Repeated lesson",
        evidenceRefs: [{ engine: "external", ref: "note:2" }],
        reason: "seen again in a different session",
        idempotencyKey: "run-2",
      }),
    );
    const repeated = engine.evaluatePromotion(second.candidateId);
    assert.ok(
      repeated.matchedPolicies.includes("repeated_evidence_backed_lesson"),
      `re-proposal counts as repetition: ${repeated.reasons.join("; ")}`,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T9: THE CORE RULE — agents can propose but can NEVER promote", () => {
  const { engine, dir } = tempEngine("agents-cannot-promote");
  try {
    engine.createScope("lib", "Library");
    // A fully policy-eligible candidate (verified study fact).
    const candidate = engine.addCandidate(
      candidateInput("lib", {
        sourceKind: "study_finding",
        epistemicClass: "observed",
        confidence: 0.99,
        method: "extracted",
        evidenceRefs: [{ engine: "study_document", ref: "doc:study-9#f1" }],
      }),
    );
    assert.equal(engine.evaluatePromotion(candidate.candidateId).eligible, true);
    // …yet an agent actor can never be the promoter, even via user policy.
    assert.throws(
      () =>
        engine.promoteCandidate(candidate.candidateId, {
          actor: { kind: "agent", name: "autonomous-agent", agentType: "llm" },
        }),
      (err: unknown) => err instanceof PromotionForbiddenError,
      "AI may assist classification but cannot self-promote",
    );
    assert.throws(
      () =>
        engine.promoteCandidate(candidate.candidateId, {
          actor: { kind: "agent", name: "autonomous-agent" },
          policy: "explicit_user_decision",
        }),
      (err: unknown) => err instanceof PromotionForbiddenError,
    );
    // The candidate is still open — nothing slipped through.
    assert.equal(engine.listCandidates({ scope: "lib", status: "open" }).length, 1);
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T9: explicit_user_decision — a human approver is the policy", () => {
  const { engine, dir } = tempEngine("user-decision");
  try {
    engine.createScope("lib", "Library");
    const candidate = engine.addCandidate(candidateInput("lib"));
    // No auto policy matched → engine promotion refused…
    assert.throws(
      () =>
        engine.promoteCandidate(candidate.candidateId, {
          actor: { kind: "engine", name: "memory" },
        }),
      (err: unknown) => err instanceof ConflictError,
    );
    // …but a human decision promotes deterministically.
    const record = engine.promoteCandidate(candidate.candidateId, {
      actor: { kind: "human", name: "kim" },
      policy: "explicit_user_decision",
    });
    assert.equal(record.status, "active");
    const event = engine.listEvents(10).find((e) => e.type === "memory.candidate.promoted");
    assert.equal((event!.payload as { approvedBy: string }).approvedBy, "human:kim");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T9: determinism — identical evaluation repeated, and across restart", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t9-determinism-"));
  const path = join(dir, "memory.db");
  let candidateId: string;
  let firstReasons: string[];
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const candidate = engine.addCandidate(candidateInput("lib"));
    candidateId = candidate.candidateId;
    const a1 = engine.evaluatePromotion(candidateId);
    const a2 = engine.evaluatePromotion(candidateId);
    assert.deepEqual(a1, a2, "same state ⇒ same assessment");
    firstReasons = a1.reasons;
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const again = engine.evaluatePromotion(candidateId);
      assert.deepEqual(again.reasons, firstReasons, "assessment stable across restarts");
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});

test("T9: promotion of a non-open candidate stays a conflict; unknown policy rejected", () => {
  const { engine, dir } = tempEngine("edges");
  try {
    engine.createScope("lib", "Library");
    const candidate = engine.addCandidate(candidateInput("lib"));
    assert.throws(
      () =>
        engine.promoteCandidate(candidate.candidateId, {
          actor: { kind: "human", name: "kim" },
          policy: "vibes_based_promotion" as never,
        }),
      (err: unknown) => err instanceof ConflictError || err instanceof Error,
      "only configured policies are accepted",
    );
    engine.promoteCandidate(candidate.candidateId, {
      actor: { kind: "human", name: "kim" },
      policy: "explicit_user_decision",
    });
    assert.throws(
      () =>
        engine.promoteCandidate(candidate.candidateId, {
          actor: { kind: "human", name: "kim" },
          policy: "explicit_user_decision",
        }),
      (err: unknown) => err instanceof ConflictError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
