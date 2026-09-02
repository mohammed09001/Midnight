/**
 * CHILD LOOP 1 verification — Task 30: Integrate Search → Memory history.
 * Proves: useful search intent/session history is stored as RETRIEVAL CONTEXT
 * (append-only, scoped) WITHOUT promoting candidate repositories as durable
 * knowledge (no records, no promotable candidates are created); candidate
 * repositories are referenced by ref only; bounded inputs; list/get; typed
 * negatives; scope-deletion cleanup; contract dispatch; and restart
 * persistence.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, dispatch, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/index.ts";
import { ValidationError, NotFoundError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t30-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

test("T30: search sessions are stored as retrieval context, never as durable knowledge", () => {
  const { engine, dir } = tempEngine("history");
  try {
    engine.createScope("lib", "Library");
    const session = engine.recordSearchSession({
      scope: "lib",
      intent: "how does rate limiting work in the gateway?",
      actor: { kind: "human", name: "kim" },
      observedAt: "2026-08-30T12:00:00.000Z",
      resultRefs: [{ engine: "repository_search", ref: "docs/gateway.md" }],
      candidateRefs: [{ engine: "repository_search", ref: "acme/gateway" }],
      note: "user investigating gateway rate limits",
    });
    assert.ok(session.searchSessionId.startsWith("ses_"));
    assert.equal(session.scopeId, engine.getScope("lib").scopeId);
    assert.equal(session.intent, "how does rate limiting work in the gateway?");
    assert.equal(session.actor!.name, "kim");
    assert.equal(session.observedAt, "2026-08-30T12:00:00.000Z");
    assert.equal(session.resultRefs.length, 1);
    assert.equal(session.resultRefs[0]!.engine, "repository_search");
    assert.equal(session.candidateRefs[0]!.ref, "acme/gateway");

    // The history is CONTEXT, not durable knowledge: no records, no candidates.
    assert.equal(engine.searchRecords({ scope: "lib" }).length, 0);
    assert.equal(engine.listCandidates({ scope: "lib", status: "all" }).length, 0);

    // It is retrievable as history.
    const history = engine.listSearchSessions({ scope: "lib" });
    assert.equal(history.length, 1);
    assert.equal(history[0]!.searchSessionId, session.searchSessionId);
    // Direct lookup.
    assert.equal(engine.getSearchSession(session.searchSessionId).intent, session.intent);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T30: sessions accumulate newest-first and are scoped + limited", () => {
  const { engine, dir } = tempEngine("list");
  try {
    engine.createScope("lib", "Library");
    engine.createScope("other", "Other");
    const s1 = engine.recordSearchSession({ scope: "lib", intent: "first" });
    const s2 = engine.recordSearchSession({ scope: "lib", intent: "second" });
    engine.recordSearchSession({ scope: "other", intent: "elsewhere" });

    const all = engine.listSearchSessions({ scope: "lib" });
    assert.deepEqual(all.map((s) => s.intent), ["second", "first"]);
    assert.equal(all.length, 2);

    const limited = engine.listSearchSessions({ scope: "lib", limit: 1 });
    assert.equal(limited.length, 1);
    assert.equal(limited[0]!.searchSessionId, s2.searchSessionId);

    const global = engine.listSearchSessions();
    assert.equal(global.length, 3);
    assert.ok(s1.observedAt !== undefined);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T30: bounded — intent length and ref counts are validated", () => {
  const { engine, dir } = tempEngine("bounded");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.recordSearchSession({ scope: "lib", intent: "x".repeat(1025) }),
      (err: unknown) => err instanceof ValidationError,
    );
    const tooManyResults = Array.from({ length: 33 }, (_, i) => ({ engine: "repository_search" as const, ref: `r${i}` }));
    assert.throws(
      () => engine.recordSearchSession({ scope: "lib", intent: "q", resultRefs: tooManyResults }),
      (err: unknown) => err instanceof ValidationError,
    );
    const tooManyCandidates = Array.from({ length: 33 }, (_, i) => ({ engine: "repository_search" as const, ref: `c${i}` }));
    assert.throws(
      () => engine.recordSearchSession({ scope: "lib", intent: "q", candidateRefs: tooManyCandidates }),
      (err: unknown) => err instanceof ValidationError,
    );
    // An invalid evidence ref engine is refused.
    assert.throws(
      () => engine.recordSearchSession({ scope: "lib", intent: "q", resultRefs: [{ engine: "warp_drive" as never, ref: "x" }] }),
      (err: unknown) => err instanceof ValidationError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T30: negative — missing intent, bad observedAt, unknown scope, missing session", () => {
  const { engine, dir } = tempEngine("negatives");
  try {
    engine.createScope("lib", "Library");
    assert.throws(
      () => engine.recordSearchSession({ scope: "lib", intent: "   " }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.recordSearchSession({ scope: "lib", intent: "q", observedAt: "garbage" }),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.recordSearchSession({ scope: "nope", intent: "q" }),
      (err: unknown) => err instanceof NotFoundError,
    );
    assert.throws(
      () => engine.getSearchSession("ses_nonexistent"),
      (err: unknown) => err instanceof NotFoundError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T30: scope deletion purges its search-session history", () => {
  const { engine, dir } = tempEngine("scope-delete");
  try {
    engine.createScope("lib", "Library");
    engine.recordSearchSession({ scope: "lib", intent: "about to be deleted" });
    assert.equal(engine.listSearchSessions({ scope: "lib" }).length, 1);
    engine.deleteScope("lib", { actor: { kind: "human", name: "kim" }, reason: "done", mode: "tombstone" });
    assert.equal(engine.listSearchSessions({ scope: "lib" }).length, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T30: versioned contract — memory.search.session record/list through the dispatcher", () => {
  const { engine, dir } = tempEngine("contract");
  try {
    engine.createScope("lib", "Library");
    const rec = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.search.session",
      request: { action: "record", scope: "lib", intent: "gateway rate limits", candidateRefs: [{ engine: "repository_search", ref: "acme/gateway" }] },
    });
    assert.equal(rec.ok, true);
    if (rec.ok) {
      const result = rec.result as { session: { searchSessionId: string; candidateRefs: unknown[] } };
      assert.ok(result.session.searchSessionId.startsWith("ses_"));
      assert.equal(result.session.candidateRefs.length, 1);
    }
    const list = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.search.session",
      request: { action: "list", scope: "lib" },
    });
    assert.equal(list.ok, true);
    if (list.ok) {
      const result = list.result as { sessions: unknown[] };
      assert.equal(result.sessions.length, 1);
    }
    const bad = dispatch(engine, {
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: "memory.search.session",
      request: { action: "record", scope: "lib", intent: "" },
    });
    assert.equal(bad.ok, false);
    if (!bad.ok) assert.equal(bad.error.code, "MEMORY_VALIDATION_FAILED");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T30: search-session history survives restart", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t30-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.recordSearchSession({ scope: "lib", intent: "persisted intent" });
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const history = engine.listSearchSessions({ scope: "lib" });
      assert.equal(history.length, 1);
      assert.equal(history[0]!.intent, "persisted intent");
      assert.equal(engine.doctor().appliedMigrations.join(",").split(",").length, 12);
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});