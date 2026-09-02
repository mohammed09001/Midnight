/**
 * Final Memory Engine architecture and product-truth gate (Task 46,
 * Phase VIII — V1 gate).
 *
 * A machine-verifiable audit of the eight product-truth clauses, each backed
 * by FRESH evidence executed at gate time (never prose):
 *
 * 1. ownership         — the public surface exposes canonical owners only
 *                        (no store leak, no store contract operation,
 *                        deterministic scope identity);
 * 2. contracts         — versioned envelope with stable version format,
 *                        major-version gating, typed unknown-op errors;
 * 3. standalone        — the engine adds/searches with no provider, no MCP
 *                        host, and no sibling engines (degraded hybrid
 *                        keeps the deterministic baseline);
 * 4. terminal          — every command surface works from fresh CLI
 *                        processes on a scratch store;
 * 5. provenance        — records trace to by-reference evidence, observed
 *                        claims require evidence, epistemic classes stay
 *                        distinguishable;
 * 6. privacy           — secret material is rejected, sensitive material is
 *                        excluded from derived exports, purges propagate to
 *                        derived stores, isolation defaults to strict,
 *                        retrieved content is labeled untrusted data;
 * 7. explanations      — lexical, ranked, fused and hybrid retrieval expose
 *                        why each record matched and how it ranks;
 * 8. extensibility     — providers plug in behind the neutral interface,
 *                        the contract surface is additive with a stable
 *                        major, and the engine has zero runtime
 *                        dependencies.
 *
 * The gate composes the Task 42–45 qualification suites as evidence and
 * runs its own checks on disposable scratch stores; the caller's store is
 * never touched. This module deliberately stands OUTSIDE the public surface
 * it audits: nothing in the engine imports it (the import graph stays
 * acyclic); the CLI and tests import it directly.
 */
import * as publicApi from "../index.ts";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import type { QualificationCheck } from "./corpora.ts";
import type { EmbeddingProvider } from "./embeddings.ts";
import type { MemoryEngine } from "./memoryEngine.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "cli", "cli.ts");

export interface GateClause {
  clause: string;
  checks: QualificationCheck[];
}

export interface ProductTruthGateReport {
  contractVersion: string;
  clauses: GateClause[];
  passed: boolean;
}

function check(name: string, pass: boolean, detail: string): QualificationCheck {
  return { name, pass, detail };
}

function scratchEngine(dir: string, name: string): MemoryEngine {
  const engine = new publicApi.MemoryEngine({ storePath: join(dir, `${name}.db`) });
  engine.open();
  return engine;
}

/** A deterministic third-party-style provider proving the neutral interface. */
function customProvider(): EmbeddingProvider {
  return {
    name: "external:gate-proof",
    model: "gate-model",
    version: "9.9.9",
    embed: (texts: string[]) => texts.map(() => new Float32Array(8)),
  };
}

function runCli(storePath: string, args: string[]): number {
  try {
    execFileSync(
      process.execPath,
      ["--experimental-strip-types", CLI_PATH, ...args, "--store", storePath],
      { encoding: "utf8", env: { ...process.env }, stdio: ["ignore", "pipe", "pipe"] },
    );
    return 0;
  } catch (err) {
    return (err as { status?: number }).status ?? 1;
  }
}

export function runProductTruthGate(): ProductTruthGateReport {
  const contractVersion = publicApi.MEMORY_ENGINE_CONTRACT_VERSION;
  const clauses: GateClause[] = [];
  const dir = mkdtempSync(join(tmpdir(), "mem-gate-"));
  try {
    // ---- 1. ownership ----
    {
      const checks: QualificationCheck[] = [];
      const exported = Object.keys(publicApi);
      checks.push(
        check(
          "public-surface-canonical",
          !exported.includes("MemoryStore") && exported.includes("MemoryEngine") && exported.includes("dispatch"),
          `${exported.length} export(s); store not exported`,
        ),
      );
      checks.push(
        check(
          "no-store-contract-operation",
          !publicApi.MEMORY_OPERATIONS.includes("memory.store" as never),
          `${publicApi.MEMORY_OPERATIONS.length} contract operation(s)`,
        ),
      );
      const a = scratchEngine(dir, "identity-a");
      const b = scratchEngine(dir, "identity-b");
      try {
        a.createScope("gate-scope", "Gate Scope");
        b.createScope("gate-scope", "Gate Scope");
        const deterministic = a.getScope("gate-scope").scopeId === b.getScope("gate-scope").scopeId;
        checks.push(check("scope-identity-deterministic", deterministic, "same project key → same scope id"));
      } finally {
        a.close();
        b.close();
      }
      clauses.push({ clause: "ownership", checks });
    }

    // ---- 2. contracts ----
    {
      const checks: QualificationCheck[] = [];
      checks.push(check("version-format", /^\d+\.\d+\.\d+$/.test(contractVersion), `contract ${contractVersion}`));
      const envelopeEngine = scratchEngine(dir, "dispatch");
      try {
        const stale = publicApi.dispatch(envelopeEngine, {
          contractVersion: "0.9.0",
          operation: "memory.search",
          request: {},
        });
        checks.push(
          check(
            "major-gating",
            !stale.ok && stale.error.code === "MEMORY_CONTRACT_MISMATCH",
            "0.x caller rejected with MEMORY_CONTRACT_MISMATCH",
          ),
        );
        const unknown = publicApi.dispatch(envelopeEngine, {
          contractVersion,
          operation: "memory.nonexistent" as never,
          request: {},
        });
        checks.push(
          check(
            "typed-unknown-operation",
            !unknown.ok && unknown.error.code === "MEMORY_VALIDATION_FAILED",
            "unknown operation returns a typed envelope error",
          ),
        );
        const sameMajor = publicApi.dispatch(envelopeEngine, {
          contractVersion: "1.0.0",
          operation: "memory.trust",
          request: {},
        });
        checks.push(
          check(
            "additive-contract-compat",
            sameMajor.ok === true,
            "same-major callers (e.g. 1.0.0/1.23.0) accepted against the current minor",
          ),
        );
      } finally {
        envelopeEngine.close();
      }
      clauses.push({ clause: "contracts", checks });
    }

    // ---- 3. standalone ----
    {
      const checks: QualificationCheck[] = [];
      const engine = scratchEngine(dir, "standalone");
      try {
        engine.createScope("gate", "Gate");
        engine.addRecord({
          scope: "gate",
          kind: "fact",
          subject: "Standalone fact",
          content: "works without any provider or host",
          actor: { kind: "human", name: "kim" },
          method: "asserted",
          epistemicClass: "observed",
          confidence: 0.9,
          sourceKind: "user_note",
          evidenceRefs: [{ engine: "external", ref: "note:standalone" }],
        });
        const lexical = engine.lexicalSearch("provider or host", { scope: "gate" });
        const hybrid = engine.hybridSearch("provider or host", { scope: "gate" });
        const status = engine.embeddingProjectionStatus("gate");
        const ok =
          lexical.hits.length === 1 &&
          hybrid.hits.length === 1 &&
          hybrid.path.semantic.available === false &&
          hybrid.hits[0]!.total > 0 &&
          status.status === "unavailable";
        checks.push(
          check(
            "runs-without-provider-mcp-siblings",
            ok,
            "add + lexical + degraded hybrid succeed with embeddings unavailable",
          ),
        );
      } finally {
        engine.close();
      }
      clauses.push({ clause: "standalone", checks });
    }

    // ---- 4. terminal ----
    {
      const checks: QualificationCheck[] = [];
      const storePath = join(dir, "terminal.db");
      const commands: Array<[string, string[]]> = [
        ["doctor", ["doctor"]],
        ["corpus-build", ["corpus", "build"]],
        ["corpus-verify", ["corpus", "verify"]],
        ["evaluate-retrieval", ["evaluate", "retrieval", "--no-semantic"]],
        ["qualify-lineage", ["qualify", "lineage"]],
        ["qualify-recovery", ["qualify", "recovery"]],
      ];
      for (const [name, args] of commands) {
        const status = runCli(storePath, args);
        checks.push(check(`cli-${name}`, status === 0, `exit ${status}`));
      }
      clauses.push({ clause: "terminal", checks });
    }

    // ---- 5–7. provenance / privacy / explanations over the corpus ----
    {
      const engine = scratchEngine(dir, "corpus");
      try {
        engine.buildQualificationCorpus();
        const scopeKey = "qualification-v1";
        const records = engine.searchRecords({ scope: scopeKey, status: "all" });

        // ---- 5. provenance ----
        {
          const checks: QualificationCheck[] = [];
          const allTraced = records.every((r) => r.evidenceRefs.length >= 1 && r.provenance.actor.kind !== undefined && r.provenance.sourceKind !== "unknown");
          checks.push(check("evidence-by-reference", allTraced, `${records.length} record(s) carry provenance + evidence refs`));
          let observedRequiresEvidence = false;
          try {
            engine.addRecord({
              scope: scopeKey,
              kind: "fact",
              subject: "Unobserved probe",
              content: "observed claim without evidence",
              actor: { kind: "human", name: "kim" },
              method: "asserted",
              epistemicClass: "observed",
              confidence: 0.9,
              sourceKind: "user_note",
            });
          } catch {
            observedRequiresEvidence = true;
          }
          checks.push(check("observed-requires-evidence", observedRequiresEvidence, "observed claim without evidence rejected"));
          const classes = new Set(records.map((r) => r.epistemicClass));
          checks.push(check("epistemic-classes-distinguishable", classes.size >= 3, `distinct classes: ${[...classes].sort().join(", ")}`));
          clauses.push({ clause: "provenance", checks });
        }

        // ---- 6. privacy ----
        {
          const checks: QualificationCheck[] = [];
          engine.setEmbeddingProvider(publicApi.localHashProvider);
          const projection = engine.buildEmbeddingProjection(scopeKey);
          const sensitiveExcluded = engine
            .contextExcerpts({ scope: scopeKey, at: "2026-07-01T00:00:00.000Z" })
            .excerpts.every((e) => e.privacyClass !== "sensitive" && e.trust === "untrusted-data");
          let secretRejected = false;
          try {
            engine.addRecord({
              scope: scopeKey,
              kind: "fact",
              subject: "Gate secret probe",
              content: "secret material",
              actor: { kind: "human", name: "kim" },
              method: "asserted",
              epistemicClass: "observed",
              confidence: 0.9,
              sourceKind: "user_note",
              evidenceRefs: [{ engine: "external", ref: "note:gate-secret" }],
              privacyClass: "secret" as never,
            });
          } catch {
            secretRejected = true;
          }
          const sensitive = records.find((r) => r.privacyClass === "sensitive");
          let purgePropagates = false;
          if (sensitive !== undefined) {
            engine.purgeByPrivacy({
              actor: { kind: "human", name: "kim" },
              reason: "gate: privacy propagation",
              privacyClasses: ["sensitive"],
              scope: scopeKey,
              origin: "gate",
            });
            engine.rebuildEmbeddingProjection(scopeKey);
            const db = engine.store.ensureOpen();
            const vectorRows = Number(
              (db.prepare("SELECT COUNT(*) AS n FROM memory_embeddings WHERE record_id = ?").get(sensitive.recordId) as Record<string, unknown>)["n"],
            );
            purgePropagates = vectorRows === 0;
          }
          const isolation = engine.policyStatus();
          checks.push(
            check(
              "privacy-posture",
              secretRejected && sensitiveExcluded && (projection.skippedPrivacy ?? 0) >= 1 && purgePropagates && isolation.projectIsolation === "strict",
              `secret rejected, sensitive excluded/redacted, purge propagates, isolation ${isolation.projectIsolation}`,
            ),
          );
          clauses.push({ clause: "privacy", checks });
        }

        // ---- 7. explanations ----
        {
          const checks: QualificationCheck[] = [];
          const lexicalExplains = engine
            .lexicalSearch("requests per minute", { scope: scopeKey })
            .hits.every((h) => typeof h.explanation.snippet === "string");
          const rankedExplains = engine
            .rankedSearch("requests per minute", { scope: scopeKey })
            .hits.every((h) => h.provenance.signals.authority !== undefined && typeof h.rank === "number");
          const fused = engine.fusedSearch("requests per minute", { scope: scopeKey });
          const fusedExplains = fused.hits.every((h) => Object.keys(h.signals).length === 5);
          const hybrid = engine.hybridSearch("requests per minute", { scope: scopeKey });
          const hybridExplains =
            hybrid.hits.every((h) =>
              h.signals.lexical.available &&
              h.signals.relation.available &&
              (!h.signals.semantic.available ? h.signals.semantic.reason !== undefined : h.signals.semantic.provider !== undefined),
            ) &&
            (hybrid.path.semantic.available || hybrid.path.semantic.reason !== undefined) &&
            hybrid.path.relation.available === true;
          checks.push(
            check(
              "retrieval-explains-itself",
              lexicalExplains && rankedExplains && fusedExplains && hybridExplains,
              "lexical, ranked, fused, and hybrid all expose why records matched and ranked",
            ),
          );
          clauses.push({ clause: "explanations", checks });
        }
      } finally {
        engine.close();
      }
    }

    // ---- 8. extensibility ----
    {
      const checks: QualificationCheck[] = [];
      const engine = scratchEngine(dir, "extensibility");
      try {
        engine.createScope("gate", "Gate");
        engine.addRecord({
          scope: "gate",
          kind: "fact",
          subject: "Extensibility fact",
          content: "pluggable provider surface",
          actor: { kind: "human", name: "kim" },
          method: "asserted",
          epistemicClass: "observed",
          confidence: 0.9,
          sourceKind: "user_note",
          evidenceRefs: [{ engine: "external", ref: "note:ext" }],
        });
        engine.setEmbeddingProvider(customProvider());
        engine.buildEmbeddingProjection("gate");
        const semantic = engine.semanticSearch("pluggable provider surface", { scope: "gate" });
        const providerPlugsIn = semantic.provider === "external:gate-proof" && semantic.model === "gate-model";
        checks.push(check("provider-neutral-pluggable", providerPlugsIn, "third-party provider identity flows through the public API"));
      } finally {
        engine.close();
      }
      let zeroDeps = false;
      try {
        const packageJson = JSON.parse(readFileSync(join(HERE, "..", "..", "package.json"), "utf8")) as { dependencies?: Record<string, string> };
        zeroDeps = packageJson.dependencies === undefined || Object.keys(packageJson.dependencies).length === 0;
      } catch {
        zeroDeps = false;
      }
      checks.push(check("zero-runtime-dependencies", zeroDeps, "package.json declares no runtime dependencies"));
      clauses.push({ clause: "extensibility", checks });
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }

  return {
    contractVersion,
    clauses,
    passed: clauses.flatMap((c) => c.checks).every((c) => c.pass),
  };
}
