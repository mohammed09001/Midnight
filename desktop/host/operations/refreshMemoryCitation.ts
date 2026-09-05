/**
 * `graph.refreshMemoryCitation` — Execution 09, Section C's explicit,
 * read-only refresh: spawns `python -m midnight_performance.memory_lineage_bridge`
 * for exactly ONE already-cited Memory reference and returns a brand-new
 * `MemoryCitationState` projection. Mirrors `getPromptRunGraph.ts`'s pattern
 * exactly: a strict request-field allow-list, an `execFile`-spawned bridge
 * under `BRIDGE_TIMEOUT_MS`, schema validation of stdout.
 *
 * Deliberately independent of `graph.getPromptRun`: this never re-fetches or
 * re-validates a `PromptRunGraphDocument`, and a `PromptRunGraphDocument`
 * already held by a caller is never mutated by calling this — the caller
 * decides what to do with the returned state (Section D: "old graph remains
 * unchanged").
 *
 * The bridge never fails closed for an unreachable/rejecting Memory
 * (Section E's truthful degraded mode is baked into `refresh_state` itself)
 * — it only exits non-zero for a genuinely malformed request (bad
 * reference format, non-Memory provider), which this operation maps to
 * `INVALID_REQUEST` rather than the generic `BRIDGE_UNAVAILABLE` a raw
 * non-zero exit would otherwise produce.
 */

import { execFile, type ExecFileException } from "node:child_process";
import { join } from "node:path";
import { BRIDGE_TIMEOUT_MS } from "../hostConfig.js";
import { HostError } from "../envelope.js";
import { loadSchema, validate } from "../schemaValidator.js";
import type { Operation, OperationContext } from "./activityListPromptRuns.js";

export type { Operation, OperationContext };

const ALLOWED_REQUEST_FIELDS = new Set(["referenceProvider", "referenceKind", "referenceValue"]);
const PYTHON_EXECUTABLE = process.env.MIDNIGHT_PYTHON || "python";

// Mirrors `memory_lineage_bridge.py`'s own EXIT_INVALID_REQUEST constant —
// no cross-language import exists, so this is duplicated deliberately, the
// same precedent `getPromptRunGraph.ts` already sets for `graph_bridge.py`.
const EXIT_INVALID_REQUEST = 4;

export const refreshMemoryCitation: Operation = async (request, context) => {
  for (const key of Object.keys(request)) {
    if (!ALLOWED_REQUEST_FIELDS.has(key)) {
      throw new HostError("INVALID_REQUEST", `unexpected request field '${key}'`);
    }
  }

  const referenceValue = request.referenceValue;
  if (typeof referenceValue !== "string" || referenceValue.length === 0) {
    throw new HostError("INVALID_REQUEST", "'referenceValue' must be a non-empty string");
  }

  const referenceProvider = request.referenceProvider;
  if (referenceProvider !== undefined && (typeof referenceProvider !== "string" || referenceProvider.length === 0)) {
    throw new HostError("INVALID_REQUEST", "'referenceProvider' must be a non-empty string when supplied");
  }

  const referenceKind = request.referenceKind;
  if (referenceKind !== undefined && (typeof referenceKind !== "string" || referenceKind.length === 0)) {
    throw new HostError("INVALID_REQUEST", "'referenceKind' must be a non-empty string when supplied");
  }

  const args = [
    "-m",
    "midnight_performance.memory_lineage_bridge",
    "--project",
    context.binding.projectId,
    "--reference-value",
    referenceValue,
    "--memory-repo-path",
    join(context.binding.projectRoot, "Memory"),
  ];
  if (typeof referenceProvider === "string") args.push("--reference-provider", referenceProvider);
  if (typeof referenceKind === "string") args.push("--reference-kind", referenceKind);
  // Mirrors `MIDNIGHT_PYTHON`'s override convention. Unset means "use
  // Memory's own default store location" (`--store-path` stays omitted) —
  // this exists so tests (and, if ever needed, an alternate deployment)
  // can point at an isolated Memory store without the Host hard-coding
  // one. Read per-call, not cached at module load, so tests may vary it.
  const memoryStorePath = process.env.MIDNIGHT_MEMORY_STORE_PATH;
  if (memoryStorePath) args.push("--store-path", memoryStorePath);

  const performancePackageDir = join(context.binding.projectRoot, "Performance");
  const stdout = await runMemoryLineageBridge(args, performancePackageDir);

  let document: unknown;
  try {
    document = JSON.parse(stdout);
  } catch {
    throw new HostError("BRIDGE_MALFORMED_OUTPUT", "Performance bridge did not return valid JSON");
  }

  const violations = validate(loadSchema("memory-citation-refresh-response.schema.json"), document);
  if (violations.length > 0) {
    throw new HostError(
      "BRIDGE_MALFORMED_OUTPUT",
      `Performance bridge output failed contract validation: ${violations.join("; ")}`,
    );
  }

  return document as Record<string, unknown>;
};

/** Mirrors `getPromptRunGraph.ts`'s own best-effort stderr extraction. */
function extractBridgeErrorMessage(stderr: string): string | null {
  const lines = stderr.split("\n").map((line) => line.trim()).filter((line) => line.length > 0);
  const lastLine = lines[lines.length - 1];
  if (!lastLine) return null;
  try {
    const parsed = JSON.parse(lastLine) as { message?: unknown };
    return typeof parsed.message === "string" ? parsed.message : null;
  } catch {
    return null;
  }
}

function runMemoryLineageBridge(args: readonly string[], cwd: string): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    execFile(
      PYTHON_EXECUTABLE,
      args as string[],
      { cwd, timeout: BRIDGE_TIMEOUT_MS, windowsHide: true, maxBuffer: 8 * 1024 * 1024 },
      (error: ExecFileException | null, stdout, stderr) => {
        if (error) {
          if (error.killed || error.signal) {
            reject(new HostError("BRIDGE_TIMEOUT", "Performance bridge timed out"));
            return;
          }
          const exitCode = typeof error.code === "number" ? error.code : null;
          const bridgeMessage = extractBridgeErrorMessage(stderr);
          if (exitCode === EXIT_INVALID_REQUEST) {
            reject(new HostError("INVALID_REQUEST", bridgeMessage ?? "invalid request"));
            return;
          }
          reject(new HostError("BRIDGE_UNAVAILABLE", stderr?.trim() || error.message));
          return;
        }
        resolvePromise(stdout);
      },
    );
  });
}
