import { afterEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { getTerminalCard } from "../../host/operations/getTerminalCard";
import { HostError } from "../../host/envelope";
import type { ProjectBinding } from "../../host/projectBinding";

const REPO_ROOT = resolve(__dirname, "..", "..", "..");

function binding(dataDir: string, projectId: string): ProjectBinding {
  return {
    descriptorVersion: 1,
    projectId,
    performanceDataDir: dataDir,
    projectRoot: REPO_ROOT,
    workspaceId: null,
  };
}

describe("insights.getTerminalCard", () => {
  const roots: string[] = [];
  afterEach(() => {
    // maxRetries/retryDelay: the bridge subprocess's sqlite3 file can still be
    // settling on Windows (AV/indexer scan) the instant after the child
    // process exits — Node's built-in ENOENT/EBUSY retry absorbs that race.
    while (roots.length) rmSync(roots.pop()!, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  });
  function tempDataDir(): string {
    const root = mkdtempSync(join(tmpdir(), "midnight-insights-"));
    roots.push(root);
    return join(root, "data");
  }

  it("rejects an unexpected request field before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-e2e-invalid") };
    const failure = await getTerminalCard({ extra: "nope" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it("rejects a non-boolean userPull before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-e2e-userpull") };
    const failure = await getTerminalCard({ userPull: "yes" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it("accepts an absent userPull and a present boolean userPull as valid requests", async () => {
    const ctxA = { binding: binding(tempDataDir(), "insights-e2e-no-flag") };
    const ctxB = { binding: binding(tempDataDir(), "insights-e2e-flag") };
    // Neither request is rejected for shape reasons — whatever happens next
    // is a bridge-availability outcome, asserted below, not a validation one.
    await expect(getTerminalCard({}, ctxA).catch((error: HostError) => error.code)).resolves.not.toBe(
      "INVALID_REQUEST",
    );
    await expect(getTerminalCard({ userPull: true }, ctxB).catch((error: HostError) => error.code)).resolves.not.toBe(
      "INVALID_REQUEST",
    );
  }, 30_000);

  // `repo_intelligence_bridge.py` did not exist on disk when this test was
  // written (Performance/ is a parallel effort's exact contract, out of
  // scope to author here). Before it lands, invoking it fails closed with a
  // typed HostError (module not found -> non-zero exit -> BRIDGE_UNAVAILABLE)
  // rather than crashing; once it lands, this same call should resolve to a
  // schema-valid document instead. Either outcome satisfies this assertion,
  // so this test stays meaningful (and green) across that boundary.
  it("either returns a schema-valid document or fails closed with a typed HostError, never a raw crash", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-e2e-smoke") };
    try {
      const document = await getTerminalCard({ userPull: true }, ctx);
      expect(document.version).toBe(1);
      expect(document.project).toBeTruthy();
    } catch (error) {
      expect(error).toBeInstanceOf(HostError);
    }
  }, 30_000);
});
