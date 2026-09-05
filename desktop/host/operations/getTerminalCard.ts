/**
 * `insights.getTerminalCard` — spawns the read-only Python bridge (`python
 * -m midnight_performance.repo_intelligence_bridge`) for the current
 * project's single terminal insight card. Mirrors
 * `activityListPromptRuns.ts`'s pattern exactly: a strict request-field
 * allow-list, an `execFile`-spawned bridge under `BRIDGE_TIMEOUT_MS`, and
 * schema validation of the bridge's stdout before it ever reaches a caller.
 *
 * `decide_terminal_card` (Python) is deliberately single-candidate — this
 * operation never returns a list of insights, only ONE current card (or
 * none, with a `reason`). `userPull` maps to the bridge's `--user-pull`
 * flag, matching `ExposureChannel.USER_PULL` — a user actively pulling
 * always outranks a proactive push.
 */

import { execFile } from "node:child_process";
import { join } from "node:path";
import { BRIDGE_TIMEOUT_MS } from "../hostConfig.js";
import { HostError } from "../envelope.js";
import { loadSchema, validate } from "../schemaValidator.js";
import type { Operation, OperationContext } from "./activityListPromptRuns.js";

export type { Operation, OperationContext };

const ALLOWED_REQUEST_FIELDS = new Set(["userPull"]);
const PYTHON_EXECUTABLE = process.env.MIDNIGHT_PYTHON || "python";

export const getTerminalCard: Operation = async (request, context) => {
  for (const key of Object.keys(request)) {
    if (!ALLOWED_REQUEST_FIELDS.has(key)) {
      throw new HostError("INVALID_REQUEST", `unexpected request field '${key}'`);
    }
  }

  const userPull = request.userPull;
  if (userPull !== undefined && typeof userPull !== "boolean") {
    throw new HostError("INVALID_REQUEST", "'userPull' must be a boolean");
  }

  const args = [
    "-m",
    "midnight_performance.repo_intelligence_bridge",
    "--data-dir",
    context.binding.performanceDataDir,
    "--project",
    context.binding.projectId,
  ];
  if (userPull === true) args.push("--user-pull");

  const performancePackageDir = join(context.binding.projectRoot, "Performance");
  const stdout = await runBridge(args, performancePackageDir);

  let document: unknown;
  try {
    document = JSON.parse(stdout);
  } catch {
    throw new HostError("BRIDGE_MALFORMED_OUTPUT", "Performance bridge did not return valid JSON");
  }

  const violations = validate(loadSchema("project-insight-response.schema.json"), document);
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
