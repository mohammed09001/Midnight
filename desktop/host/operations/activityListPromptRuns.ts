/**
 * The Desktop Host's one production-ready operation. Spawns the read-only
 * Python bridge (`python -m midnight_performance.desktop_bridge`) with
 * explicit, Host-resolved arguments — the renderer's request is validated
 * against a strict field allow-list (`limit`, `cursor` only) so it can never
 * smuggle a filesystem path or project override through to the subprocess.
 */

import { execFile } from "node:child_process";
import { join } from "node:path";
import { BRIDGE_TIMEOUT_MS } from "../hostConfig.js";
import { HostError } from "../envelope.js";
import type { ProjectBinding } from "../projectBinding.js";
import { loadSchema, validate } from "../schemaValidator.js";

export interface OperationContext {
  readonly binding: ProjectBinding;
}

export type Operation = (
  request: Record<string, unknown>,
  context: OperationContext,
) => Promise<Record<string, unknown>>;

const ALLOWED_REQUEST_FIELDS = new Set(["limit", "cursor"]);
const PYTHON_EXECUTABLE = process.env.MIDNIGHT_PYTHON || "python";

export const activityListPromptRuns: Operation = async (request, context) => {
  for (const key of Object.keys(request)) {
    if (!ALLOWED_REQUEST_FIELDS.has(key)) {
      throw new HostError("INVALID_REQUEST", `unexpected request field '${key}'`);
    }
  }

  const limit = request.limit;
  if (limit !== undefined && (typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 || limit > 100)) {
    throw new HostError("INVALID_REQUEST", "'limit' must be an integer between 1 and 100");
  }

  const cursor = request.cursor;
  if (cursor !== undefined && cursor !== null && typeof cursor !== "string") {
    throw new HostError("INVALID_REQUEST", "'cursor' must be a string or null");
  }

  const args = [
    "-m",
    "midnight_performance.desktop_bridge",
    "--data-dir",
    context.binding.performanceDataDir,
    "--project",
    context.binding.projectId,
  ];
  if (typeof limit === "number") args.push("--limit", String(limit));
  if (typeof cursor === "string") args.push("--cursor", cursor);

  const performancePackageDir = join(context.binding.projectRoot, "Performance");
  const stdout = await runBridge(args, performancePackageDir);

  let document: unknown;
  try {
    document = JSON.parse(stdout);
  } catch {
    throw new HostError("BRIDGE_MALFORMED_OUTPUT", "Performance bridge did not return valid JSON");
  }

  const violations = validate(loadSchema("activity-response.schema.json"), document);
  if (violations.length > 0) {
    throw new HostError(
      "BRIDGE_MALFORMED_OUTPUT",
      `Performance bridge output failed contract validation: ${violations.join("; ")}`,
    );
  }

  return document as Record<string, unknown>;
};

function runBridge(args: readonly string[], cwd: string): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    execFile(
      PYTHON_EXECUTABLE,
      args as string[],
      { cwd, timeout: BRIDGE_TIMEOUT_MS, windowsHide: true, maxBuffer: 8 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          if (error.killed || error.signal) {
            reject(new HostError("BRIDGE_TIMEOUT", "Performance bridge timed out"));
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
