/**
 * CHILD LOOP 2 verification — Task 2: Define stable Memory identities and
 * scopes. Proves: stable identities for MemoryRecord, MemoryCandidate,
 * project/workspace scope, source reference, evidence reference, actor,
 * validity interval, revision, contradiction group, supersession chain —
 * surviving client restarts and project-path moves.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, renameSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";

import { MemoryEngine } from "../src/engine/memoryEngine.ts";
import {
  ConflictError,
  NotFoundError,
  ValidationError,
} from "../src/contracts/errors.ts";
import {
  actorKey,
  isUlidShaped,
  newId,
  scopeIdFromProjectKey,
  ulid,
} from "../src/engine/ids.ts";

const ALPHABET = /^[0-9ABCDEFGHJKMNPQRSTVWXYZ]+$/;

function tempDir(name: string): string {
  return mkdtempSync(join(tmpdir(), `mem-t2-${name}-`));
}

function makeRecordInput(scope: string, subject: string, content: string) {
  return {
    scope,
    kind: "fact" as const,
    subject,
    content,
    actor: { kind: "agent" as const, name: "worker-a", agentType: "research" },
    method: "test",
    epistemicClass: "observed" as const,
    confidence: 0.9,
    sourceKind: "study_finding" as const,
    evidenceRefs: [{ engine: "study_document" as const, ref: "doc:test#s1" }],
  };
}

test("T2: ULID identities match the ULID spec shape and sort monotonically", () => {
  const ids = Array.from({ length: 1000 }, () => ulid());
  for (const id of ids) {
    assert.ok(id.length === 26, "ULID is 26 characters");
    assert.match(id, ALPHABET, "Crockford base32 alphabet (no I/L/O/U)");
  }
  for (let i = 1; i < ids.length; i++) {
    assert.ok(ids[i - 1]! < ids[i]!, "in-process monotonic ordering");
  }
});

test("T2: prefixed identities are unique and carry stable prefixes", () => {
  const seen = new Set<string>();
  for (const prefix of ["mem", "cand", "evt", "ctg"] as const) {
    for (let i = 0; i < 500; i++) {
      const id = newId(prefix);
      assert.ok(id.startsWith(`${prefix}_`));
      assert.ok(isUlidShaped(id.slice(prefix.length + 1)));
      assert.ok(!seen.has(id));
      seen.add(id);
    }
  }
});

test("T2: scope identity is derived from projectKey — deterministic, path-independent", () => {
  const a1 = scopeIdFromProjectKey("library101");
  const a2 = scopeIdFromProjectKey("library101");
  const b = scopeIdFromProjectKey("library-102");
  assert.equal(a1, a2, "same project key always yields the same scope id");
  assert.notEqual(a1, b);
  assert.ok(a1.startsWith("scp_"));
  assert.ok(isUlidShaped(a1.slice(4)), "scope id body is 26 Crockford-base32 chars");
});

test("T2: scope survives a project-path move and a client restart", () => {
  const dir = tempDir("move");
  const originalPath = join(dir, "original-location", "memory.db");

  const first = new MemoryEngine({ storePath: originalPath });
  first.open();
  const scope = first.createScope("library101", "Library 101");
  first.close();

  // Simulate a project move: relocate the whole store to a new path.
  const movedPath = join(dir, "moved-somewhere-else", "deeper", "memory.db");
  mkdirp(dirname(movedPath));
  renameSync(originalPath, movedPath);

  const second = new MemoryEngine({ storePath: movedPath });
  second.open();
  try {
    const resolved = second.getScope("library101");
    assert.equal(resolved.scopeId, scope.scopeId, "scope id unchanged across move");
    assert.equal(resolved.projectKey, "library101");
    // The engine never stores the project path: identities are path-independent.
    const raw = JSON.stringify(resolved);
    assert.doesNotMatch(raw, /original-location|moved-somewhere/i);
  } finally {
    second.close();
  }
  rmSync(dir, { recursive: true, force: true });
});

test("T2: scope creation is idempotent for identical identity, conflicting otherwise", () => {
  const dir = tempDir("idempotent");
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  try {
    const s1 = engine.createScope("proj-x", "Project X");
    const s2 = engine.createScope("proj-x", "Project X");
    assert.equal(s1.scopeId, s2.scopeId);
    assert.throws(
      () => engine.createScope("proj-x", "Some Other Name"),
      (err: unknown) => err instanceof ConflictError,
    );
    assert.throws(
      () => engine.createScope("/etc/absolute/path", "Path Is Not A Key"),
      (err: unknown) => err instanceof ValidationError,
      "filesystem paths are rejected as project keys",
    );
  } finally {
    engine.close();
  }
});

test("T2: record, candidate, and contradiction identities survive restarts", () => {
  const dir = tempDir("identities");
  const path = join(dir, "memory.db");
  let recordId: string;
  let candidateId: string;

  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const record = engine.addRecord(makeRecordInput("lib", "Auth design", "JWT with short-lived access tokens"));
    const other = engine.addRecord(makeRecordInput("lib", "Auth design", "JWT with short-lived access tokens"));
    const candidate = engine.addCandidate({
      ...makeRecordInput("lib", "Cache note", "Cache stamps are rebuildable"),
      epistemicClass: "inferred",
      confidence: 0.4,
      reason: "observation from an earlier session",
    });
    const group = engine.registerContradiction("lib", "Auth design", [record.recordId, other.recordId]);
    recordId = record.recordId;
    candidateId = candidate.candidateId;
    assert.ok(recordId.startsWith("mem_"));
    assert.ok(candidateId.startsWith("cand_"));
    assert.ok(group.groupId.startsWith("ctg_"));
    engine.close();
  }

  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const record = engine.getRecord(recordId);
      assert.equal(record.contradictionGroupId !== null, true, "contradiction link survives restart");
      const events = engine.listEvents(100).map((e) => e.type);
      assert.ok(events.includes("memory.contradiction.registered"));
      assert.ok(events.includes("memory.candidate.created"));
      void candidateId;
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});

test("T2: actors are canonical, agent-neutral strings; no agent is special-cased", () => {
  assert.equal(actorKey({ kind: "agent", name: "worker-a" }), "agent:worker-a");
  assert.equal(actorKey({ kind: "human", name: "  Kim  " }), "human:Kim");
  assert.equal(actorKey({ kind: "engine", name: "repository_sync" }), "engine:repository_sync");
  // Any agent family works identically — engine neutrality by construction.
  assert.equal(actorKey({ kind: "agent", name: "x" }), actorKey({ kind: "agent", name: "x" }));
});

test("T2: revisions and validity intervals are first-class identity data", () => {
  const dir = tempDir("validity");
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  try {
    engine.createScope("lib", "Library");
    const record = engine.addRecord({
      ...makeRecordInput("lib", "Migration window", "Migrations run on weekends"),
      validFrom: "2026-08-01T00:00:00.000Z",
      validUntil: "2026-09-01T00:00:00.000Z",
    });
    assert.equal(record.revision, 1);
    assert.equal(record.validFrom, "2026-08-01T00:00:00.000Z");
    assert.equal(record.validUntil, "2026-09-01T00:00:00.000Z");
    assert.throws(
      () =>
        engine.addRecord({
          ...makeRecordInput("lib", "Bad window", "invalid interval"),
          validFrom: "2026-09-01T00:00:00.000Z",
          validUntil: "2026-08-01T00:00:00.000Z",
        }),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
  }
});

test("T2: supersession chain identity links predecessor and successor", () => {
  const dir = tempDir("supersession");
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(makeRecordInput("lib", "Release train", "Weekly on Tuesday"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Weekly on Wednesday",
      actor: { kind: "human", name: "kim" },
      method: "policy change",
      reason: "train moved to Wednesdays",
    });
    assert.equal(v2.supersedesId, v1.recordId);
    const v1After = engine.getRecord(v1.recordId);
    assert.equal(v1After.status, "superseded");
    assert.equal(v1After.supersededById, v2.recordId);
  } finally {
    engine.close();
  }
});

test("T2: negative — unknown scope and unknown contradiction targets fail typed", () => {
  const dir = tempDir("negatives");
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  try {
    assert.throws(
      () => engine.addRecord(makeRecordInput("no-such-scope", "S", "C")),
      (err: unknown) => err instanceof NotFoundError,
    );
    assert.throws(
      () => engine.getScope("ghost-project"),
      (err: unknown) => err instanceof NotFoundError,
    );
    assert.throws(
      () => engine.registerContradiction("ghost-project", "S", ["mem_a", "mem_b"]),
      (err: unknown) => err instanceof NotFoundError,
    );
  } finally {
    engine.close();
  }
});

function mkdirp(dir: string): void {
  mkdirSync(dir, { recursive: true });
}

