/**
 * CHILD LOOP 1 verification — Task 42: frozen Memory qualification corpora.
 *
 * Proves: the corpus materializes deterministically through the public engine
 * API only; verification freezes subject-keyed expectations into a stable
 * report (two independent builds produce identical reports); build is
 * replay-safe; the verifier DETECTS tampering and missing corpora (a corpus
 * that can never fail would be worthless); the embedding area is optional
 * (works without any provider); and the terminal surface (CLI) exposes
 * build/verify with honest exit codes.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MemoryEngine, QUALIFICATION_CORPUS_VERSION } from "../src/index.ts";
import type { QualificationReport } from "../src/index.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "src", "cli", "cli.ts");

function tempEngine(name: string): { engine: MemoryEngine; dir: string; storePath: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t42-${name}-`));
  const storePath = join(dir, "memory.db");
  const engine = new MemoryEngine({ storePath });
  engine.open();
  return { engine, dir, storePath };
}

function reportDigest(report: QualificationReport): string {
  return createHash("sha256").update(JSON.stringify(report), "utf8").digest("hex");
}

test("T42: corpus builds through the public API and all frozen expectations verify", () => {
  const { engine, dir } = tempEngine("build-verify");
  try {
    const build = engine.buildQualificationCorpus();
    assert.equal(build.corpusVersion, QUALIFICATION_CORPUS_VERSION);
    assert.equal(build.built, true);
    assert.equal(build.recordCount, 18);
    assert.deepEqual(build.embeddings, { recordCount: 17, skippedPrivacy: 1 });

    const report = engine.verifyQualificationCorpus();
    assert.equal(report.passed, true, `failed checks: ${report.checks.filter((c) => !c.pass).map((c) => `${c.name} (${c.detail})`).join("; ")}`);
    const names = report.checks.map((c) => c.name);
    for (const expected of [
      "scope-exists",
      "record-counts",
      "lexical-current-facts",
      "current-view",
      "historical-absent-from-current",
      "as-of-supersession",
      "supersession-lineage",
      "contradiction-pairs",
      "duplicates",
      "privacy-excerpts",
      "provenance-filters",
      "secret-rejected",
      "embeddings",
      "corpus-event",
    ]) {
      assert.ok(names.includes(expected), `missing check ${expected}`);
    }
    // The six corpus areas are all covered by the frozen checks.
    assert.ok(names.includes("contradiction-pairs"), "contradictions area");
    assert.ok(names.includes("supersession-lineage") && names.includes("as-of-supersession"), "supersession/historical area");
    assert.ok(names.includes("duplicates"), "duplicates area");
    assert.ok(names.includes("privacy-excerpts"), "privacy area");
    assert.ok(names.includes("provenance-filters"), "provenance area");
    assert.ok(names.includes("current-view"), "current-facts area");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T42: determinism — two independent builds produce byte-identical verification reports", () => {
  const a = tempEngine("determinism-a");
  const b = tempEngine("determinism-b");
  try {
    a.engine.buildQualificationCorpus();
    b.engine.buildQualificationCorpus();
    const reportA = a.engine.verifyQualificationCorpus();
    const reportB = b.engine.verifyQualificationCorpus();
    assert.equal(reportA.passed, true);
    assert.equal(reportB.passed, true);
    assert.deepEqual(reportA, reportB, "reports must be identical across independent builds");
    assert.equal(reportDigest(reportA), reportDigest(reportB));
  } finally {
    a.engine.close();
    b.engine.close();
    rmSync(a.dir, { recursive: true, force: true });
    rmSync(b.dir, { recursive: true, force: true });
  }
});

test("T42: replay safety — building twice is a no-op and verification still passes", () => {
  const { engine, dir } = tempEngine("replay");
  try {
    const first = engine.buildQualificationCorpus();
    assert.equal(first.built, true);
    const second = engine.buildQualificationCorpus();
    assert.equal(second.built, false);
    assert.equal(second.recordCount, first.recordCount);
    const report = engine.verifyQualificationCorpus();
    assert.equal(report.passed, true);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T42: the corpus discriminates — tampering and missing corpora FAIL verification", () => {
  const { engine, dir } = tempEngine("tamper");
  try {
    // Missing corpus: verification fails honestly instead of passing vacuously.
    const missing = engine.verifyQualificationCorpus();
    assert.equal(missing.passed, false);
    assert.equal(missing.checks[0]!.name, "scope-exists");
    assert.equal(missing.checks[0]!.pass, false);

    engine.buildQualificationCorpus();
    assert.equal(engine.verifyQualificationCorpus().passed, true);

    // Tamper through the public API: retract a current fact.
    const rateLimit = engine
      .searchRecords({ scope: "qualification-v1", exactSubject: "Rate limit" })
      .find((r) => r.status === "active")!;
    engine.retractRecord(rateLimit.recordId, {
      actor: { kind: "human", name: "kim" },
      reason: "tamper probe",
    });
    const report = engine.verifyQualificationCorpus();
    assert.equal(report.passed, false, "tampering must be detected");
    const failed = report.checks.filter((c) => !c.pass).map((c) => c.name);
    assert.ok(failed.includes("record-counts"), `record-counts must fail, failed: ${failed.join(",")}`);
    assert.ok(failed.includes("current-view"), `current-view must fail, failed: ${failed.join(",")}`);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T42: degradation — the corpus builds and verifies without any embedding provider", () => {
  const { engine, dir } = tempEngine("no-embeddings");
  try {
    const build = engine.buildQualificationCorpus({ includeEmbeddings: false });
    assert.equal(build.built, true);
    assert.equal(build.embeddings, null);
    // No provider was ever configured for this engine.
    assert.equal(engine.embeddingProjectionStatus("qualification-v1").status, "unavailable");

    const report = engine.verifyQualificationCorpus({ includeEmbeddings: false });
    assert.equal(report.embeddingsChecked, false);
    assert.equal(
      report.passed,
      true,
      `failed: ${report.checks.filter((c) => !c.pass).map((c) => `${c.name} (${c.detail})`).join("; ")}`,
    );
    assert.ok(!report.checks.some((c) => c.name === "embeddings"));

    // Requesting the embedding area without a projection reports failure honestly.
    const withEmbeddings = engine.verifyQualificationCorpus();
    assert.equal(withEmbeddings.checks.find((c) => c.name === "embeddings")!.pass, false);
    assert.equal(withEmbeddings.passed, false);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T42: terminal surface — corpus build/verify via CLI with honest exit codes", () => {
  const { engine, dir, storePath } = tempEngine("cli");
  try {
    engine.close();
    const cliArgs = ["--experimental-strip-types", CLI_PATH];
    const run = (args: string[]): { stdout: string; status: number } => {
      try {
        const stdout = execFileSync(process.execPath, [...cliArgs, ...args, "--store", storePath], {
          encoding: "utf8",
          env: { ...process.env },
        });
        return { stdout, status: 0 };
      } catch (err) {
        const e = err as { stdout?: string; status?: number };
        return { stdout: e.stdout ?? "", status: e.status ?? 1 };
      }
    };

    // Verify before build: exit 1 with a structured report.
    const before = run(["corpus", "verify"]);
    assert.equal(before.status, 1);
    const beforeReport = JSON.parse(before.stdout) as QualificationReport;
    assert.equal(beforeReport.passed, false);

    // Build: exit 0 and the store now qualifies.
    const build = run(["corpus", "build"]);
    assert.equal(build.status, 0);
    const buildResult = JSON.parse(build.stdout) as { built: boolean; recordCount: number };
    assert.equal(buildResult.built, true);
    assert.equal(buildResult.recordCount, 18);

    // Verify: exit 0, passed true.
    const after = run(["corpus", "verify"]);
    assert.equal(after.status, 0);
    const afterReport = JSON.parse(after.stdout) as QualificationReport;
    assert.equal(afterReport.passed, true);

    // Re-build is a replay-safe no-op.
    const rebuild = run(["corpus", "build"]);
    assert.equal(rebuild.status, 0);
    assert.equal((JSON.parse(rebuild.stdout) as { built: boolean }).built, false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
