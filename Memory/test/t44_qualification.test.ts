/**
 * CHILD LOOP 2 verification — Task 44: contradiction/supersession qualification.
 *
 * Proves: historical facts remain queryable (as-of, timeline, lexical with
 * status filter, revision chain) and current truth resolves correctly
 * (winner-only current view, no open groups) WITHOUT destructive overwrite
 * (predecessor content/hash/reason intact; corpus-wide hash recomputation) —
 * all over the frozen corpus, deterministically, with honest CLI exit codes
 * and a falsifiable failure path.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MemoryEngine } from "../src/index.ts";
import type { LineageQualificationReport } from "../src/index.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "src", "cli", "cli.ts");

function tempEngine(name: string): { engine: MemoryEngine; dir: string; storePath: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t44-${name}-`));
  const storePath = join(dir, "memory.db");
  const engine = new MemoryEngine({ storePath });
  engine.open();
  return { engine, dir, storePath };
}

function digest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");
}

test("T44: lineage invariants qualify over the frozen corpus", () => {
  const { engine, dir } = tempEngine("qualify");
  try {
    const report = engine.qualifyContradictionSupersession();
    assert.equal(report.passed, true, `failed: ${report.checks.filter((c) => !c.pass).map((c) => `${c.name} (${c.detail})`).join("; ")}`);
    assert.deepEqual(
      report.checks.map((c) => c.name),
      [
        "chain-integrity",
        "predecessor-immutability",
        "resolution-non-destructive",
        "historical-queryable",
        "current-truth-resolves",
        "no-destructive-overwrite",
      ],
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T44: determinism — two independent qualifications produce identical reports", () => {
  const a = tempEngine("det-a");
  const b = tempEngine("det-b");
  try {
    const reportA = a.engine.qualifyContradictionSupersession();
    const reportB = b.engine.qualifyContradictionSupersession();
    assert.equal(reportA.passed, true);
    assert.deepEqual(reportA, reportB);
    assert.equal(digest(reportA), digest(reportB));
  } finally {
    a.engine.close();
    b.engine.close();
    rmSync(a.dir, { recursive: true, force: true });
    rmSync(b.dir, { recursive: true, force: true });
  }
});

test("T44: falsifiable — forged current truth fails qualification", () => {
  const { engine, dir } = tempEngine("tamper");
  try {
    assert.equal(engine.qualifyContradictionSupersession().passed, true);
    // Forge an extra active "Auth provider" record through the public API:
    // the current view must no longer resolve to exactly the winning version.
    engine.addRecord({
      scope: "qualification-v1",
      kind: "fact",
      subject: "Auth provider",
      content: "Forged auth provider claim",
      actor: { kind: "human", name: "impostor" },
      method: "asserted",
      epistemicClass: "observed",
      confidence: 0.5,
      sourceKind: "user_note",
      evidenceRefs: [{ engine: "external", ref: "note:forged" }],
    });
    const report = engine.qualifyContradictionSupersession();
    assert.equal(report.passed, false, "forged current truth must be detected");
    const failed = report.checks.filter((c) => !c.pass).map((c) => c.name);
    assert.ok(failed.includes("current-truth-resolves"), `current-truth-resolves must fail, failed: ${failed.join(",")}`);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T44: terminal surface — qualify lineage via CLI with honest exit codes", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t44-cli-"));
  const storePath = join(dir, "memory.db");
  const reportPath = join(dir, "lineage.json");
  try {
    const run = (args: string[]): { stdout: string; status: number } => {
      try {
        const stdout = execFileSync(
          process.execPath,
          ["--experimental-strip-types", CLI_PATH, ...args, "--store", storePath],
          { encoding: "utf8", env: { ...process.env } },
        );
        return { stdout, status: 0 };
      } catch (err) {
        const e = err as { stdout?: string; status?: number };
        return { stdout: e.stdout ?? "", status: e.status ?? 1 };
      }
    };
    const result = run(["qualify", "lineage", "--path", reportPath]);
    assert.equal(result.status, 0, result.stdout.slice(0, 400));
    const report = JSON.parse(result.stdout) as LineageQualificationReport;
    assert.equal(report.passed, true);
    assert.equal(report.checks.length, 6);
    assert.deepEqual(JSON.parse(readFileSync(reportPath, "utf8")), report);
    // Restart-safety: a fresh process re-qualifies the same store.
    const rerun = run(["qualify", "lineage"]);
    assert.equal(rerun.status, 0);
    assert.equal((JSON.parse(rerun.stdout) as LineageQualificationReport).passed, true);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
