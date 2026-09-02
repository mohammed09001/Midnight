/**
 * CHILD LOOP 1 verification — Task 43: retrieval evaluation.
 *
 * Proves: precision/recall-style measurement over frozen relevance judgments
 * with fully transparent per-query results; deterministic baselines (exact,
 * lexical, temporal, hybrid) and a frozen semantic gate that fails on any
 * degradation; the semantic surface COMPLEMENTS lexical AND-strictness
 * (retrieves relevant records where lexical retrieves none); the evaluation
 * is deterministic across independent builds; works without semantic
 * (baseline-only); and the CLI exposes it with honest exit codes.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MemoryEngine } from "../src/index.ts";
import type { RetrievalEvaluationReport } from "../src/index.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "src", "cli", "cli.ts");

function tempEngine(name: string): { engine: MemoryEngine; dir: string; storePath: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t43-${name}-`));
  const storePath = join(dir, "memory.db");
  const engine = new MemoryEngine({ storePath });
  engine.open();
  return { engine, dir, storePath };
}

function digest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");
}

test("T43: evaluation measures all strategies with transparent, frozen expectations", () => {
  const { engine, dir } = tempEngine("strategies");
  try {
    const report = engine.evaluateRetrieval();
    assert.equal(report.passed, true);
    const names = report.strategies.map((s) => s.name);
    assert.deepEqual(names, ["exact", "lexical", "temporal", "hybrid-baseline", "semantic", "hybrid-semantic"]);
    // Transparent results: every query exposes relevant + retrieved keys and metrics.
    for (const strategy of report.strategies) {
      assert.ok(strategy.queries.length > 0);
      for (const q of strategy.queries) {
        assert.ok(q.relevantKeys.length > 0);
        assert.ok(Number.isFinite(q.precision) && Number.isFinite(q.recall) && Number.isFinite(q.mrr));
      }
    }
    // Frozen baselines: exact and temporal are complete; lexical misses exactly
    // the two AND-strictness queries.
    const exact = report.strategies.find((s) => s.name === "exact")!;
    const temporal = report.strategies.find((s) => s.name === "temporal")!;
    assert.equal(exact.micro.recall, 1);
    assert.equal(temporal.micro.recall, 1);
    const lexical = report.strategies.find((s) => s.name === "lexical")!;
    const zeroRecall = lexical.queries.filter((q) => q.recall === 0).map((q) => q.name).sort();
    assert.deepEqual(zeroRecall, ["auth-token-disjoint", "sessions-paraphrase"]);
    assert.ok(lexical.micro.recall >= 0.55, `lexical recall ${lexical.micro.recall}`);
    // Transparent per-query audit: the AND-strict lexical queries retrieved nothing.
    const disjoint = lexical.queries.find((q) => q.name === "auth-token-disjoint")!;
    assert.deepEqual(disjoint.retrievedKeys, []);
    assert.equal(disjoint.relevantKeys.length, 2);
    // The frozen gate: semantic complements the baselines, never degrades.
    assert.equal(report.semanticGate!.verdict, "complements");
    const semantic = report.strategies.find((s) => s.name === "semantic")!;
    const semDisjoint = semantic.queries.find((q) => q.name === "auth-token-disjoint")!;
    assert.equal(semDisjoint.recall, 1, "semantic retrieves the AND-strict relevant records");
    // Privacy compatibility: the sensitive record is never semantically retrieved.
    const rotation = semantic.queries.find((q) => q.name === "api-key-rotation")!;
    assert.equal(rotation.recall, 0);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T43: determinism — two independent evaluations produce identical reports", () => {
  const a = tempEngine("det-a");
  const b = tempEngine("det-b");
  try {
    const reportA = a.engine.evaluateRetrieval();
    const reportB = b.engine.evaluateRetrieval();
    assert.equal(reportA.passed, true);
    assert.equal(reportB.passed, true);
    assert.deepEqual(reportA, reportB);
    assert.equal(digest(reportA), digest(reportB));
  } finally {
    a.engine.close();
    b.engine.close();
    rmSync(a.dir, { recursive: true, force: true });
    rmSync(b.dir, { recursive: true, force: true });
  }
});

test("T43: degradation — baseline-only evaluation works without any semantic strategy", () => {
  const { engine, dir } = tempEngine("no-semantic");
  try {
    const report = engine.evaluateRetrieval({ includeSemantic: false });
    assert.equal(report.passed, true);
    assert.equal(report.semanticGate, null);
    assert.deepEqual(
      report.strategies.map((s) => s.name),
      ["exact", "lexical", "temporal", "hybrid-baseline"],
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T43: falsifiable — deleting corpus truth moves metrics below the frozen bars", () => {
  const { engine, dir } = tempEngine("tamper");
  try {
    assert.equal(engine.evaluateRetrieval().passed, true);
    // Remove the auth-provider truth through the public lifecycle API.
    const auth = engine.searchRecords({ scope: "qualification-v1", exactSubject: "Auth provider" });
    for (const record of auth) {
      engine.deleteRecord(record.recordId, { actor: { kind: "human", name: "kim" }, reason: "tamper probe" });
    }
    const report = engine.evaluateRetrieval({ includeSemantic: false });
    assert.equal(report.passed, false, "deleted truth must be measurable as degradation");
    const failed = report.strategies.filter((s) => s.micro.recall < 0.55 || s.micro.recall < 0.99 && (s.name === "exact" || s.name === "temporal"));
    assert.ok(failed.length > 0, "at least one strategy must fall below its bar");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T43: terminal surface — evaluate retrieval via CLI with honest exit codes", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t43-cli-"));
  const storePath = join(dir, "memory.db");
  const reportPath = join(dir, "evaluation.json");
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
    const result = run(["evaluate", "retrieval", "--path", reportPath]);
    assert.equal(result.status, 0, result.stdout.slice(0, 400));
    const report = JSON.parse(result.stdout) as RetrievalEvaluationReport;
    assert.equal(report.passed, true);
    assert.equal(report.strategies.length, 6);
    // The --path evidence artifact exists and matches the emitted report.
    assert.deepEqual(JSON.parse(readFileSync(reportPath, "utf8")), report);
    const noSemantic = run(["evaluate", "retrieval", "--no-semantic"]);
    assert.equal(noSemantic.status, 0);
    const baselineOnly = JSON.parse(noSemantic.stdout) as RetrievalEvaluationReport;
    assert.equal(baselineOnly.semanticGate, null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
