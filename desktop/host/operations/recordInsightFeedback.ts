/**
 * `insights.recordInsightFeedback` — spawns `python -m
 * midnight_performance.repo_intelligence_bridge --record-feedback` to close
 * the feedback loop on one previously-exposed insight (open/save/dismiss).
 * Mirrors `refreshMemoryCitation.ts`'s pattern exactly: a strict
 * request-field allow-list, an `execFile`-spawned bridge under
 * `BRIDGE_TIMEOUT_MS`, schema validation of stdout, and mapping the
 * sibling bridges' shared EXIT_INVALID_REQUEST convention (an unknown
 * exposureId or malformed outcome) to `INVALID_REQUEST` rather than the
 * generic `BRIDGE_UNAVAILABLE` a raw non-zero exit would otherwise produce.
 *
 * ASSUMPTION: `repo_intelligence_bridge.py` did not exist yet when this file
 * was written (checked: no `Performance/midnight_performance/repo_intelligence_bridge.py`
 * on disk). This assumes a single bridge module with a `--record-feedback`
 * flag, per the plan's fallback instruction, and mirrors
 * `memory_lineage_bridge.py`'s/`graph_bridge.py`'s shared
 * `EXIT_INVALID_REQUEST = 4` convention since no cross-language import
 * exists to confirm the real value. If the sibling Python effort lands a
 * different exit code or a second bridge module, update
 * `EXIT_INVALID_REQUEST` and/or the `-m` argument below — this file is the
 * only place either would need to change.
 */

import { execFile, type ExecFileException } from "node:child_process";
import { join } from "node:path";
import { BRIDGE_TIMEOUT_MS } from "../hostConfig.js";
import { HostError } from "../envelope.js";
import { loadSchema, validate } from "../schemaValidator.js";
import type { Operation, OperationContext } from "./activityListPromptRuns.js";

export type { Operation, OperationContext };

const ALLOWED_REQUEST_FIELDS = new Set(["exposureId", "outcome"]);
const ALLOWED_OUTCOMES = new Set(["opened", "saved", "dismissed"]);
const PYTHON_EXECUTABLE = process.env.MIDNIGHT_PYTHON || "python";

// See the ASSUMPTION note above — mirrors `graph_bridge.py`'s own
// EXIT_NOT_FOUND/EXIT_INVALID_REQUEST constants. No cross-language import
// exists, so this is duplicated deliberately. An unknown exposureId is a
// "resource doesn't exist" outcome (NOT_FOUND), not a malformed-request one
// (INVALID_REQUEST) — the Host's own field/enum checks above already reject
// every malformed shape before the bridge is ever spawned.
const EXIT_NOT_FOUND = 2;
const EXIT_INVALID_REQUEST = 4;

export const recordInsightFeedback: Operation = async (request, context) => {
  for (const key of Object.keys(request)) {
    if (!ALLOWED_REQUEST_FIELDS.has(key)) {
      throw new HostError("INVALID_REQUEST", `unexpected request field '${key}'`);
    }
  }

  const exposureId = request.exposureId;
  if (typeof exposureId !== "string" || exposureId.length === 0) {
    throw new HostError("INVALID_REQUEST", "'exposureId' must be a non-empty string");
  }

  const outcome = request.outcome;
  if (typeof outcome !== "string" || !ALLOWED_OUTCOMES.has(outcome)) {
    throw new HostError("INVALID_REQUEST", "'outcome' must be one of 'opened', 'saved', 'dismissed'");
  }

  const args = [
    "-m",
    "midnight_performance.repo_intelligence_bridge",
    "--data-dir",
    context.binding.performanceDataDir,
    "--project",
    context.binding.projectId,
    "--record-feedback",
    "--exposure-id",
    exposureId,
    "--outcome",
    outcome,
  ];

  const performancePackageDir = join(context.binding.projectRoot, "Performance");
  const stdout = await runBridge(args, performancePackageDir);

  let document: unknown;
  try {
    document = JSON.parse(stdout);
  } catch {
    throw new HostError("BRIDGE_MALFORMED_OUTPUT", "Performance bridge did not return valid JSON");
  }

  const violations = validate(loadSchema("project-insight-feedback-response.schema.json"), document);
  if (violations.length > 0) {
    throw new HostError(
      "BRIDGE_MALFORMED_OUTPUT",
      `Performance bridge output failed contract validation: ${violations.join("; ")}`,
    );
  }

  return document as Record<string, unknown>;
};

/** Mirrors `refreshMemoryCitation.ts`'s own best-effort stderr extraction. */
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

function runBridge(args: readonly string[], cwd: string): Promise<string> {
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
          if (exitCode === EXIT_NOT_FOUND) {
            reject(new HostError("NOT_FOUND", bridgeMessage ?? "exposure not found"));
            return;
          }
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
