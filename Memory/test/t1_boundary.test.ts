/**
 * CHILD LOOP 1 verification — Task 1: Freeze the Memory Engine product
 * boundary. Proves: canonical durable store, versioned contract surface,
 * versioned events (metadata-only), explicit failure/degraded behavior,
 * observability (doctor/events), terminal-first CLI usable without a game.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { MemoryEngine, MEMORY_ENGINE_CONTRACT_VERSION } from "../src/engine/memoryEngine.ts";
import { StoreUnavailableError, MigrationError } from "../src/contracts/errors.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "src", "cli", "cli.ts");

function tempStore(name: string): string {
  const dir = mkdtempSync(join(tmpdir(), `mem-t1-${name}-`));
  return join(dir, "memory.db");
}

test("T1: fresh store opens, migrates to head, and reports created", () => {
  const path = tempStore("fresh");
  const engine = new MemoryEngine({ storePath: path });
  try {
    engine.open();
    assert.equal(engine.store.created, true);
    const report = engine.doctor();
    assert.equal(report.healthy, true);
    assert.equal(report.contractVersion, MEMORY_ENGINE_CONTRACT_VERSION);
    assert.equal(report.journalMode, "wal");
    assert.equal(report.integrity, "ok");
    assert.ok(report.appliedMigrations.length >= 1, "at least one migration applied");
    assert.ok(report.appliedMigrations.every((v) => Number.isInteger(v)));
  } finally {
    engine.close();
  }
});

test("T1: reopen is idempotent — migrations do not re-apply, state survives restart", () => {
  const path = tempStore("restart");
  const first = new MemoryEngine({ storePath: path });
  first.open();
  const migrationsAfterFirst = first.doctor().appliedMigrations;
  first.store.appendEvent("memory.test.ping", { n: 1 });
  first.close();

  const second = new MemoryEngine({ storePath: path });
  second.open();
  try {
    assert.equal(second.store.created, false);
    const migrationsAfterSecond = second.doctor().appliedMigrations;
    assert.deepEqual(migrationsAfterSecond, migrationsAfterFirst);
    const events = second.listEvents(10);
    assert.equal(events.length, 1);
    assert.equal(events[0]!.type, "memory.test.ping");
    assert.equal(events[0]!.contractVersion, MEMORY_ENGINE_CONTRACT_VERSION);
  } finally {
    second.close();
  }
});

test("T1: events are versioned, reference-only, and listed newest-first", () => {
  const path = tempStore("events");
  const engine = new MemoryEngine({ storePath: path });
  engine.open();
  try {
    engine.store.appendEvent("memory.record.created", { recordId: "mem_x", scopeId: "scp_y" });
    engine.store.appendEvent("memory.scope.created", { scopeId: "scp_y" });
    const events = engine.listEvents(10);
    assert.equal(events.length, 2);
    assert.equal(events[0]!.type, "memory.scope.created");
    assert.ok(events[0]!.eventId.startsWith("evt_"), "event identity has evt_ prefix");
    // Metadata-only payloads: no content bodies in the event surface.
    const payloadJson = JSON.stringify(events.map((e) => e.payload));
    assert.doesNotMatch(payloadJson, /"content"/);
  } finally {
    engine.close();
  }
});

test("T1: negative — corrupt store file fails open with typed error, no silent fallback", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t1-corrupt-"));
  const path = join(dir, "memory.db");
  writeFileSync(path, Buffer.from("this is not a sqlite database at all", "utf8"));
  const engine = new MemoryEngine({ storePath: path });
  assert.throws(
    () => engine.open(),
    (err: unknown) => err instanceof StoreUnavailableError,
    "open must fail with MEMORY_STORE_UNAVAILABLE",
  );
  const report = engine.doctor();
  assert.equal(report.healthy, false);
  assert.equal(report.errorCode, "MEMORY_STORE_UNAVAILABLE");
});

test("T1: negative — uncreatable store path fails with typed error", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t1-blocked-"));
  const blocker = join(dir, "blocker");
  writeFileSync(blocker, "i am a file, not a directory");
  const path = join(blocker, "inner", "memory.db");
  const engine = new MemoryEngine({ storePath: path });
  assert.throws(
    () => engine.open(),
    (err: unknown) => err instanceof StoreUnavailableError,
  );
});

test("T1: doctor never throws on degraded stores and reports unhealthy", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t1-doctor-"));
  const path = join(dir, "memory.db");
  writeFileSync(path, Buffer.from("corrupt: not a database", "utf8"));
  const engine = new MemoryEngine({ storePath: path });
  // Doctor answers without throwing on a degraded store.
  const report = engine.doctor();
  assert.equal(report.healthy, false);
  assert.equal(report.errorCode, "MEMORY_STORE_UNAVAILABLE");
  assert.ok(report.errorMessage !== undefined);
  rmSync(dir, { recursive: true, force: true });
});

test("T1: negative — migration failure surfaces as MEMORY_MIGRATION_FAILED", async () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t1-mig-"));
  const path = join(dir, "memory.db");
  // Pre-create a conflicting table so migration 1 collides.
  writeFileSync(path, Buffer.alloc(0));
  const { DatabaseSync } = await import("node:sqlite");
  const raw = new DatabaseSync(path);
  raw.exec("CREATE TABLE engine_events (x TEXT);");
  raw.close();
  const engine = new MemoryEngine({ storePath: path });
  assert.throws(
    () => engine.open(),
    (err: unknown) => err instanceof MigrationError,
  );
  void dir;
});

test("T1: CLI doctor works end-to-end from a terminal surface (no game)", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t1-cli-"));
  const path = join(dir, "memory.db");
  mkdirSync(dir, { recursive: true });
  const stdout = execFileSync(
    process.execPath,
    ["--experimental-strip-types", CLI_PATH, "doctor", "--store", path],
    { encoding: "utf8", env: { ...process.env } },
  );
  const report = JSON.parse(stdout) as { healthy: boolean; contractVersion: string; journalMode: string };
  assert.equal(report.healthy, true);
  assert.equal(report.contractVersion, MEMORY_ENGINE_CONTRACT_VERSION);
  assert.equal(report.journalMode, "wal");
});
