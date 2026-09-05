/**
 * `graph.getPromptRun` — spawns the read-only Python bridge (`python -m
 * midnight_performance.graph_bridge`) for one real Prompt Run's Actual
 * Performance Graph. Mirrors `activityListPromptRuns.ts`'s pattern exactly:
 * a strict request-field allow-list, an `execFile`-spawned bridge under
 * `BRIDGE_TIMEOUT_MS`, and schema validation of the bridge's stdout before
 * it ever reaches a caller.
 *
 * `promptRunId` must be the CANONICAL Prompt Run identity (e.g.
 * `mp:v1:prompt_run:<uuid>`) — the only Prompt Run identity Desktop's
 * frontend ever has (`ActivityEvent.promptRunId`). The bridge fails closed
 * with a distinct exit code (never a fabricated empty graph) when the
 * identity doesn't resolve to a real, project-scoped Prompt Run, or when a
 * supplied cursor is malformed/foreign — this operation maps those exit
 * codes to `NOT_FOUND`/`INVALID_CURSOR` `HostError`s instead of the generic
 * `BRIDGE_UNAVAILABLE` a raw non-zero exit would otherwise produce.
 */

import { execFile, type ExecFileException } from "node:child_process";
import { join } from "node:path";
import { BRIDGE_TIMEOUT_MS } from "../hostConfig.js";
import { HostError } from "../envelope.js";
import { loadSchema, validate } from "../schemaValidator.js";
import type { Operation, OperationContext } from "./activityListPromptRuns.js";

export type { Operation, OperationContext };

const ALLOWED_REQUEST_FIELDS = new Set(["promptRunId", "maxDepth", "maxNodes", "maxEdges", "allowedLayers", "cursor", "focusNode"]);
const PYTHON_EXECUTABLE = process.env.MIDNIGHT_PYTHON || "python";

// Mirrors `Performance/midnight_performance/graph_bridge.py`'s own
// EXIT_NOT_FOUND/EXIT_INVALID_CURSOR/EXIT_INVALID_REQUEST/EXIT_INVALID_FOCUS
// constants — no cross-language import exists, so these are duplicated
// deliberately; that module is the source of truth if the two ever need to
// be reconciled.
const EXIT_NOT_FOUND = 2;
const EXIT_INVALID_CURSOR = 3;
const EXIT_INVALID_REQUEST = 4;
const EXIT_INVALID_FOCUS = 5;

export const getPromptRunGraph: Operation = async (request, context) => {
  for (const key of Object.keys(request)) {
    if (!ALLOWED_REQUEST_FIELDS.has(key)) {
      throw new HostError("INVALID_REQUEST", `unexpected request field '${key}'`);
    }
  }

  const promptRunId = request.promptRunId;
  if (typeof promptRunId !== "string" || promptRunId.length === 0) {
    throw new HostError("INVALID_REQUEST", "'promptRunId' must be a non-empty string");
  }

  const maxDepth = request.maxDepth;
  if (maxDepth !== undefined && (typeof maxDepth !== "number" || !Number.isInteger(maxDepth) || maxDepth < 1)) {
    throw new HostError("INVALID_REQUEST", "'maxDepth' must be a positive integer");
  }

  const maxNodes = request.maxNodes;
  if (maxNodes !== undefined && (typeof maxNodes !== "number" || !Number.isInteger(maxNodes) || maxNodes < 1)) {
    throw new HostError("INVALID_REQUEST", "'maxNodes' must be a positive integer");
  }

  const maxEdges = request.maxEdges;
  if (maxEdges !== undefined && (typeof maxEdges !== "number" || !Number.isInteger(maxEdges) || maxEdges < 1)) {
    throw new HostError("INVALID_REQUEST", "'maxEdges' must be a positive integer");
  }

  const allowedLayers = request.allowedLayers;
  if (
    allowedLayers !== undefined &&
    (!Array.isArray(allowedLayers) || !allowedLayers.every((layer) => typeof layer === "string" && layer.length > 0))
  ) {
    throw new HostError("INVALID_REQUEST", "'allowedLayers' must be an array of non-empty strings");
  }

  const cursor = request.cursor;
  if (cursor !== undefined && cursor !== null && typeof cursor !== "string") {
    throw new HostError("INVALID_REQUEST", "'cursor' must be a string or null");
  }

  const focusNode = request.focusNode;
  if (focusNode !== undefined && (typeof focusNode !== "string" || focusNode.length === 0)) {
    throw new HostError("INVALID_REQUEST", "'focusNode' must be a non-empty string");
  }

  const args = [
    "-m",
    "midnight_performance.graph_bridge",
    "--data-dir",
    context.binding.performanceDataDir,
    "--project",
    context.binding.projectId,
    "--prompt-run-id",
    promptRunId,
  ];
  if (typeof maxDepth === "number") args.push("--max-depth", String(maxDepth));
  if (typeof maxNodes === "number") args.push("--max-nodes", String(maxNodes));
  if (typeof maxEdges === "number") args.push("--max-edges", String(maxEdges));
  if (Array.isArray(allowedLayers) && allowedLayers.length > 0) args.push("--layers", allowedLayers.join(","));
  if (typeof cursor === "string") args.push("--cursor", cursor);
  if (typeof focusNode === "string") args.push("--focus-node", focusNode);

  const performancePackageDir = join(context.binding.projectRoot, "Performance");
  const stdout = await runGraphBridge(args, performancePackageDir);

  let document: unknown;
  try {
    document = JSON.parse(stdout);
  } catch {
    throw new HostError("BRIDGE_MALFORMED_OUTPUT", "Performance bridge did not return valid JSON");
  }

  const violations = validate(loadSchema("graph-prompt-run-response.schema.json"), document);
  if (violations.length > 0) {
    throw new HostError(
      "BRIDGE_MALFORMED_OUTPUT",
      `Performance bridge output failed contract validation: ${violations.join("; ")}`,
    );
  }

  return document as Record<string, unknown>;
};

/** Best-effort extraction of the bridge's own structured stderr message — a
 * cosmetic `-m`-invocation RuntimeWarning (Execution 03) can precede it, so
 * this reads only the last non-blank stderr line. Falls back to `null` (the
 * caller supplies a generic message) rather than ever throwing here. */
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

function runGraphBridge(args: readonly string[], cwd: string): Promise<string> {
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
            reject(new HostError("NOT_FOUND", bridgeMessage ?? "Prompt Run not found"));
            return;
          }
          if (exitCode === EXIT_INVALID_CURSOR) {
            reject(new HostError("INVALID_CURSOR", bridgeMessage ?? "invalid continuation cursor"));
            return;
          }
          if (exitCode === EXIT_INVALID_REQUEST) {
            reject(new HostError("INVALID_REQUEST", bridgeMessage ?? "invalid request"));
            return;
          }
          if (exitCode === EXIT_INVALID_FOCUS) {
            reject(new HostError("INVALID_FOCUS", bridgeMessage ?? "invalid focus node"));
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
