import { afterEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { recordInsightFeedback } from "../../host/operations/recordInsightFeedback";
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

describe("insights.recordInsightFeedback", () => {
  const roots: string[] = [];
  afterEach(() => {
    // maxRetries/retryDelay: the bridge subprocess's sqlite3 file can still be
    // settling on Windows (AV/indexer scan) the instant after the child
    // process exits — Node's built-in ENOENT/EBUSY retry absorbs that race.
    while (roots.length) rmSync(roots.pop()!, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  });
  function tempDataDir(): string {
    const root = mkdtempSync(join(tmpdir(), "midnight-insights-feedback-"));
    roots.push(root);
    return join(root, "data");
  }

  it("rejects an unexpected request field before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-fb-e2e-invalid") };
    const failure = await recordInsightFeedback({ exposureId: "e1", outcome: "opened", extra: "nope" }, ctx).catch(
      (error) => error,
    );
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it("rejects a missing exposureId before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-fb-e2e-missing-id") };
    const failure = await recordInsightFeedback({ outcome: "opened" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it("rejects an empty exposureId before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-fb-e2e-empty-id") };
    const failure = await recordInsightFeedback({ exposureId: "", outcome: "opened" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it("rejects a missing outcome before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-fb-e2e-missing-outcome") };
    const failure = await recordInsightFeedback({ exposureId: "e1" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it("rejects an outcome outside the closed set before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-fb-e2e-bad-outcome") };
    const failure = await recordInsightFeedback({ exposureId: "e1", outcome: "liked" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it.each(["opened", "saved", "dismissed"] as const)(
    "accepts outcome '%s' as a valid request shape",
    async (outcome) => {
      const ctx = { binding: binding(tempDataDir(), `insights-fb-e2e-valid-${outcome}`) };
      const errorCode = await recordInsightFeedback({ exposureId: "e1", outcome }, ctx).catch(
        (error: HostError) => error.code,
      );
      // Whatever happens next is a bridge-availability outcome, not a
      // validation one — this request shape must never be rejected as
      // INVALID_REQUEST by the Host's own field/enum checks.
      expect(errorCode).not.toBe("INVALID_REQUEST");
    },
    30_000,
  );

  // `repo_intelligence_bridge.py` did not exist on disk when this test was
  // written (Performance/ is a parallel effort's exact contract, out of
  // scope to author here). Before it lands, invoking it fails closed with a
  // typed HostError (module not found -> non-zero exit -> BRIDGE_UNAVAILABLE,
  // since exit code 4 is a Python-side convention this module cannot trigger
  // on its own) rather than crashing; once it lands, this same call should
  // resolve to a schema-valid recorded response instead. Either outcome
  // satisfies this assertion, so this test stays meaningful (and green)
  // across that boundary.
  it("either returns a schema-valid recorded response or fails closed with a typed HostError, never a raw crash", async () => {
    const ctx = { binding: binding(tempDataDir(), "insights-fb-e2e-smoke") };
    try {
      const document = await recordInsightFeedback({ exposureId: "mp:v1:exposure:doesnotexist", outcome: "dismissed" }, ctx);
      expect(document.version).toBe(1);
      expect(document.recorded).toBe(true);
    } catch (error) {
      expect(error).toBeInstanceOf(HostError);
    }
  }, 30_000);
});
