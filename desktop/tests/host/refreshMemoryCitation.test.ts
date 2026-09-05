import { afterEach, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { refreshMemoryCitation } from "../../host/operations/refreshMemoryCitation";
import { HostError } from "../../host/envelope";
import type { ProjectBinding } from "../../host/projectBinding";

const REPO_ROOT = resolve(__dirname, "..", "..", "..");
const MEMORY_CLI = join(REPO_ROOT, "Memory", "src", "cli", "cli.ts");

function runMemoryCli(args: readonly string[], storePath: string): string {
  return execFileSync("node", ["--experimental-strip-types", MEMORY_CLI, ...args, "--store", storePath], {
    encoding: "utf-8",
  });
}

function binding(projectId: string): ProjectBinding {
  return {
    descriptorVersion: 1,
    projectId,
    performanceDataDir: join(REPO_ROOT, "Performance"),
    projectRoot: REPO_ROOT,
    workspaceId: null,
  };
}

describe("graph.refreshMemoryCitation (Execution 09, end-to-end via the real Memory + Performance bridges)", () => {
  const roots: string[] = [];
  const previousStorePath = process.env.MIDNIGHT_MEMORY_STORE_PATH;
  afterEach(() => {
    while (roots.length) rmSync(roots.pop()!, { recursive: true, force: true });
    if (previousStorePath === undefined) delete process.env.MIDNIGHT_MEMORY_STORE_PATH;
    else process.env.MIDNIGHT_MEMORY_STORE_PATH = previousStorePath;
  });

  function tempStorePath(): string {
    const root = mkdtempSync(join(tmpdir(), "midnight-memory-lineage-"));
    roots.push(root);
    return join(root, "memory.db");
  }

  it("reports a pinned citation's live current state", async () => {
    const storePath = tempStorePath();
    process.env.MIDNIGHT_MEMORY_STORE_PATH = storePath;
    const projectId = "refresh-e2e-1";
    // Performance's local project key maps to a Memory scope key via
    // project_key_for_identity — mirror that exactly rather than guessing
    // a scope key, so `scope create` targets the same scope the bridge
    // will resolve internally.
    const scopeKeyJson = execFileSync(
      "python",
      [
        "-c",
        [
          "import json",
          "from midnight_performance import EntityKind, deterministic_identity, project_key_for_identity",
          `print(json.dumps(project_key_for_identity(deterministic_identity(EntityKind.PROJECT, ${JSON.stringify(projectId)}))))`,
        ].join("\n"),
      ],
      { cwd: join(REPO_ROOT, "Performance"), encoding: "utf-8" },
    );
    const scopeKey = JSON.parse(scopeKeyJson) as string;
    runMemoryCli(["scope", "create", "--key", scopeKey, "--name", "Refresh E2E"], storePath);
    const addedJson = runMemoryCli(
      ["record", "add", "--scope", scopeKey, "--subject", "S", "--content", "v1", "--evidence", "external:e2e-1", "--source-kind", "user_note"],
      storePath,
    );
    const recordId = (JSON.parse(addedJson) as { recordId: string }).recordId;

    const document = await refreshMemoryCitation(
      { referenceValue: `${recordId}#rev1` },
      { binding: binding(projectId) },
    );

    const state = document.state as Record<string, unknown>;
    expect(state.currentStatusKnown).toBe(true);
    expect(state.currentRevision).toBe(1);
    expect(state.pinnedRevision).toBe(1);
    expect(state.newerRevisionAvailable).toBe(false);
  }, 30_000);

  it("reports Memory-unavailable as a truthful degraded result via the schema-validated document, not a Host failure", async () => {
    const storePath = tempStorePath();
    process.env.MIDNIGHT_MEMORY_STORE_PATH = storePath;
    // No scope/record ever created against this fresh store -- the
    // reference is well-formed but nothing in Memory can ever match it.
    const document = await refreshMemoryCitation(
      { referenceValue: "rec-never-existed#rev1" },
      { binding: binding("refresh-e2e-missing") },
    );
    const state = document.state as Record<string, unknown>;
    expect(state.currentStatusKnown).toBe(false);
    expect((state.gaps as string[]).some((gap) => gap.includes("unavailable"))).toBe(true);
  }, 30_000);

  it("rejects a malformed reference value as INVALID_REQUEST before any Memory call", async () => {
    const failure = await refreshMemoryCitation(
      { referenceValue: "not-a-pinned-reference" },
      { binding: binding("refresh-e2e-malformed") },
    ).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  }, 30_000);

  it("rejects an unexpected request field before ever spawning the bridge", async () => {
    const failure = await refreshMemoryCitation(
      { referenceValue: "rec-1#rev1", extra: "nope" },
      { binding: binding("refresh-e2e-invalid") },
    ).catch((error) => error);
    expect(failure).toBeInstanceOf(HostError);
    expect((failure as HostError).code).toBe("INVALID_REQUEST");
  });
});
