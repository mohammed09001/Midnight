/**
 * Task 2 (Midnight Memory Execution 01) — Library-origin identity migration.
 * Proves: the store-path env var prefers MIDNIGHT_MEMORY_STORE but still
 * falls back (deprecated) to LIBRARY_MEMORY_STORE; a pre-existing legacy
 * backup bundle still restores; and the renamed engine identity/contract
 * version landed.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine, MEMORY_ENGINE_ID, MEMORY_ENGINE_CONTRACT_VERSION, defaultStorePath } from "../src/index.ts";
import { BACKUP_SCHEMA_VERSION, LEGACY_BACKUP_FORMAT, type BackupData } from "../src/engine/backup.ts";

const ENV_KEYS = ["MIDNIGHT_MEMORY_STORE", "LIBRARY_MEMORY_STORE"] as const;

function withEnv(values: Partial<Record<(typeof ENV_KEYS)[number], string>>, fn: () => void): void {
  const saved: Record<string, string | undefined> = {};
  for (const key of ENV_KEYS) saved[key] = process.env[key];
  try {
    for (const key of ENV_KEYS) {
      if (values[key] !== undefined) process.env[key] = values[key];
      else delete process.env[key];
    }
    fn();
  } finally {
    for (const key of ENV_KEYS) {
      if (saved[key] !== undefined) process.env[key] = saved[key];
      else delete process.env[key];
    }
  }
}

test("T48: defaultStorePath prefers MIDNIGHT_MEMORY_STORE even when the legacy var is also set", () => {
  withEnv({ MIDNIGHT_MEMORY_STORE: "/tmp/new-path.db", LIBRARY_MEMORY_STORE: "/tmp/old-path.db" }, () => {
    assert.equal(defaultStorePath(), "/tmp/new-path.db");
  });
});

test("T48: defaultStorePath falls back to LIBRARY_MEMORY_STORE (deprecated) when only the legacy var is set", () => {
  withEnv({ LIBRARY_MEMORY_STORE: "/tmp/old-path.db" }, () => {
    const originalWrite = process.stderr.write.bind(process.stderr);
    let warned = "";
    process.stderr.write = ((chunk: string) => {
      warned += chunk;
      return true;
    }) as typeof process.stderr.write;
    try {
      assert.equal(defaultStorePath(), "/tmp/old-path.db");
    } finally {
      process.stderr.write = originalWrite;
    }
    assert.match(warned, /LIBRARY_MEMORY_STORE is deprecated/);
  });
});

test("T48: defaultStorePath falls back to the repo-local default when neither var is set", () => {
  withEnv({}, () => {
    assert.equal(defaultStorePath(), "data/memory-engine.db");
  });
});

test("T48: a hand-built legacy-format backup bundle still verifies and restores", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t48-legacy-restore-"));
  try {
    const data: BackupData = {
      scopes: [],
      contradictionGroups: [],
      records: [],
      revisions: [],
      candidates: [],
      searchSessions: [],
    };
    const checksum = createHash("sha256").update(JSON.stringify(data)).digest("hex");
    const legacyBundle = {
      format: LEGACY_BACKUP_FORMAT,
      schemaVersion: BACKUP_SCHEMA_VERSION,
      contractVersion: "1.0.0",
      createdAt: new Date().toISOString(),
      checksum,
      data,
    };

    const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
    engine.open();
    try {
      const check = engine.verifyBackup(legacyBundle);
      assert.equal(check.valid, true, check.errors.join("; "));
      const restored = engine.restoreBundle(legacyBundle);
      assert.equal(restored.restored, true);
      assert.equal(restored.scopes, 0);
      assert.equal(restored.records, 0);
    } finally {
      engine.close();
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T48: a bundle with an unrecognized format is still rejected", () => {
  const check_result = { format: "some-other-format", schemaVersion: BACKUP_SCHEMA_VERSION, contractVersion: "1.0.0", createdAt: new Date().toISOString(), checksum: "x", data: { scopes: [], contradictionGroups: [], records: [], revisions: [], candidates: [], searchSessions: [] } };
  const dir = mkdtempSync(join(tmpdir(), "mem-t48-reject-"));
  try {
    const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
    engine.open();
    try {
      const check = engine.verifyBackup(check_result);
      assert.equal(check.valid, false);
      assert.ok(check.errors.some((e) => e.includes("format must be")));
    } finally {
      engine.close();
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T48: the renamed engine identity and contract version landed", () => {
  assert.equal(MEMORY_ENGINE_ID, "midnight.memory-engine");
  assert.equal(MEMORY_ENGINE_CONTRACT_VERSION, "1.27.0");
});
