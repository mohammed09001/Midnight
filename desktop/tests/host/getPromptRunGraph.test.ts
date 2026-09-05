import { afterEach, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { getPromptRunGraph } from "../../host/operations/getPromptRunGraph";
import { HostError } from "../../host/envelope";
import type { ProjectBinding } from "../../host/projectBinding";

const REPO_ROOT = resolve(__dirname, "..", "..", "..");
const PERFORMANCE_DIR = join(REPO_ROOT, "Performance");
const PYTHON = process.env.MIDNIGHT_PYTHON || "python";

/**
 * Seeds one real Prompt Run through the actual Python engine and returns
 * its CANONICAL identity — exactly what `ActivityEvent.promptRunId` would
 * hand the frontend, and the only identity form this operation (and the
 * real Desktop UI) may ever pass to the bridge. Using anything else here
 * (e.g. the raw `provider:event_id` stable key) would silently re-test the
 * pre-Execution-07 bug this suite exists to catch.
 */
function seedPromptRun(dataDir: string, projectId: string, eventId: string): string {
  mkdirSync(dataDir, { recursive: true });
  const script = [
    "import json",
    "from pathlib import Path",
    "from datetime import datetime, timezone",
    "from midnight_performance import record_prompt_run",
    `data_dir = Path(${JSON.stringify(dataDir)})`,
    `_, canonical = record_prompt_run(data_dir / 'evidence.jsonl', ${JSON.stringify(projectId)}, 'provider', ${JSON.stringify(eventId)}, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))`,
    "print(json.dumps({'canonical': canonical}))",
  ].join("\n");
  const stdout = execFileSync(PYTHON, ["-c", script], { cwd: PERFORMANCE_DIR, encoding: "utf-8" });
  return (JSON.parse(stdout) as { canonical: string }).canonical;
}

function binding(dataDir: string, projectId: string): ProjectBinding {
  return {
    descriptorVersion: 1,
    projectId,
    performanceDataDir: dataDir,
    projectRoot: REPO_ROOT,
    workspaceId: null,
  };
}

describe("graph.getPromptRun (Execution 07, end-to-end via the real Python bridge)", () => {
  const roots: string[] = [];
  afterEach(() => {
    while (roots.length) rmSync(roots.pop()!, { recursive: true, force: true });
  });
  function tempDataDir(): string {
    const root = mkdtempSync(join(tmpdir(), "midnight-graph-"));
    roots.push(root);
    return join(root, "data");
  }

  it("resolves a real Prompt Run by its canonical identity — the exact shape the frontend has", async () => {
    const dataDir = tempDataDir();
    const canonical = seedPromptRun(dataDir, "graph-e2e", "evt-1");
    const ctx = { binding: binding(dataDir, "graph-e2e") };

    const document = await getPromptRunGraph({ promptRunId: canonical }, ctx);

    expect(document.root).toBe(canonical);
    const nodes = document.nodes as { id: string }[];
    expect(nodes).toHaveLength(1);
    expect(nodes[0].id).toBe(canonical);
  }, 30_000);

  it("rejects an unknown canonical identity as NOT_FOUND, not a bridge crash", async () => {
    const dataDir = tempDataDir();
    seedPromptRun(dataDir, "graph-e2e-notfound", "evt-1");
    const ctx = { binding: binding(dataDir, "graph-e2e-notfound") };

    // A validly-shaped but never-recorded canonical identity.
    const unknownCanonical = "mp:v1:prompt_run:00000000-0000-0000-0000-000000000000";
    const failure = await getPromptRunGraph({ promptRunId: unknownCanonical }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("NOT_FOUND");
  }, 30_000);

  it("rejects a foreign/malformed cursor as INVALID_CURSOR", async () => {
    const dataDir = tempDataDir();
    const canonical = seedPromptRun(dataDir, "graph-e2e-cursor", "evt-1");
    const ctx = { binding: binding(dataDir, "graph-e2e-cursor") };

    const failure = await getPromptRunGraph({ promptRunId: canonical, cursor: "not-a-real-cursor" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_CURSOR");
  }, 30_000);

  it("rejects an unexpected request field before ever spawning the bridge", async () => {
    const ctx = { binding: binding(tempDataDir(), "graph-e2e-invalid") };
    const failure = await getPromptRunGraph({ promptRunId: "mp:v1:prompt_run:00000000-0000-0000-0000-000000000000", extra: "nope" }, ctx).catch(
      (error) => error,
    );
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });

  it("rejects a raw stable key — the pre-fix calling convention — as NOT_FOUND, not a crash", async () => {
    const dataDir = tempDataDir();
    seedPromptRun(dataDir, "graph-e2e-stable-key", "evt-1");
    const ctx = { binding: binding(dataDir, "graph-e2e-stable-key") };

    const failure = await getPromptRunGraph({ promptRunId: "provider:evt-1" }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("NOT_FOUND");
  }, 30_000);

  it("rejects an unknown focusNode as INVALID_FOCUS, not a bridge crash", async () => {
    const dataDir = tempDataDir();
    const canonical = seedPromptRun(dataDir, "graph-e2e-focus", "evt-1");
    const ctx = { binding: binding(dataDir, "graph-e2e-focus") };

    const bogusFocus = "mp:v1:agent_run:00000000-0000-0000-0000-000000000000";
    const failure = await getPromptRunGraph({ promptRunId: canonical, focusNode: bogusFocus }, ctx).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_FOCUS");
  }, 30_000);

  it("reports the real evidence checkpoint in projectionIdentity", async () => {
    const dataDir = tempDataDir();
    const canonical = seedPromptRun(dataDir, "graph-e2e-identity", "evt-1");
    const ctx = { binding: binding(dataDir, "graph-e2e-identity") };

    const document = await getPromptRunGraph({ promptRunId: canonical }, ctx);
    const identity = document.projectionIdentity as Record<string, unknown>;
    expect(identity.root).toBe(canonical);
    expect(typeof identity.evidenceCheckpoint).toBe("string");
    expect((identity.evidenceCheckpoint as string).length).toBeGreaterThan(0);
  }, 30_000);
});
