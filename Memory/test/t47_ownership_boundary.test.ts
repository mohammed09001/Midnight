/**
 * Task 1 (Midnight Memory Execution 01) — ownership boundary verification.
 * Proves: a Performance evidence ref carrying a raw-payload-like object
 * (not a bare string id) is rejected at runtime, never stored; no source
 * file reaches into Performance's filesystem/SQLite directly; and the
 * ownership statement documentation actually landed.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t47-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

const REPO_ROOT = join(import.meta.dirname, "..");
const SRC_DIR = join(REPO_ROOT, "src");

function listTsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...listTsFiles(full));
    } else if (entry.name.endsWith(".ts")) {
      out.push(full);
    }
  }
  return out;
}

test("T47: a Performance evidence ref carrying a raw payload object is rejected, not stored", () => {
  const { engine, dir } = tempEngine("raw-payload");
  try {
    engine.createScope("lib", "Library");
    const result = engine.proposePerformanceLessons("lib", [
      // Simulates a careless/malicious caller trying to smuggle a raw
      // Performance payload through evidenceRefs instead of a bare id.
      {
        subject: "Smuggled payload",
        content: "attempted raw evidence embedding",
        evidenceRefs: [{ ref: "perf:1", rawPayload: "SECRET TRANSCRIPT" } as unknown as string],
      },
      // A well-formed lesson in the same batch must still succeed.
      { subject: "Good lesson", content: "evidence-backed", evidenceRefs: ["perf:run-1"] },
    ]);
    assert.equal(result.accepted.length, 1);
    assert.equal(result.accepted[0]!.subject, "Good lesson");
    assert.equal(result.rejected.length, 1);
    assert.equal(result.rejected[0]!.code, "MEMORY_VALIDATION_FAILED");
    assert.match(result.rejected[0]!.message, /entries must be non-empty/);
    // Nothing from the malformed lesson entered the candidate stream.
    const stream = engine.listCandidates({ scope: "lib", status: "open" });
    assert.equal(stream.length, 1);
    assert.equal(stream[0]!.subject, "Good lesson");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T47: no source file reaches into Performance's filesystem or a sibling SQLite store", () => {
  const forbidden = [/\.\.\/Performance/i, /\.\.\/\.\.\/Performance/i, /midnight_performance/i];
  for (const file of listTsFiles(SRC_DIR)) {
    const text = readFileSync(file, "utf8");
    for (const pattern of forbidden) {
      assert.ok(!pattern.test(text), `${file} must not reference Performance's filesystem (matched ${pattern})`);
    }
  }
});

test("T47: the ownership statement documentation landed in BOUNDARY.md and PERFORMANCE.md", () => {
  const boundary = readFileSync(join(REPO_ROOT, "docs", "BOUNDARY.md"), "utf8");
  assert.match(boundary, /## 0\. Canonical Ownership Statement/);
  assert.match(boundary, /Performance\s+Episodes/);
  const performanceDoc = readFileSync(join(REPO_ROOT, "docs", "PERFORMANCE.md"), "utf8");
  assert.match(performanceDoc, /does not own Performance's raw records/);
});
