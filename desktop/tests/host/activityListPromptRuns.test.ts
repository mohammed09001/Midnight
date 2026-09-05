import { afterEach, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { activityListPromptRuns } from "../../host/operations/activityListPromptRuns";
import type { ProjectBinding } from "../../host/projectBinding";

const REPO_ROOT = resolve(__dirname, "..", "..", "..");
const PERFORMANCE_DIR = join(REPO_ROOT, "Performance");
const PYTHON = process.env.MIDNIGHT_PYTHON || "python";

/**
 * Seeds `count` Prompt Runs directly through the real Python engine (one
 * subprocess, not one per record). `provider_event_id` is namespaced by
 * `projectId` — the deterministic Prompt Run identity is derived from
 * `provider:event_id` only (not the project), so two projects reusing the
 * same event-id numbering would otherwise mint identical canonical IDs by
 * construction, which would make a "no cross-project leakage" assertion
 * meaningless rather than a real isolation check.
 */
function seedLedger(dataDir: string, projectId: string, count: number): void {
  mkdirSync(dataDir, { recursive: true });
  const script = [
    "from pathlib import Path",
    "from datetime import datetime, timedelta, timezone",
    "from midnight_performance import record_prompt_run",
    `data_dir = Path(${JSON.stringify(dataDir)})`,
    `project = ${JSON.stringify(projectId)}`,
    `count = ${count}`,
    "base = datetime(2026, 1, 1, tzinfo=timezone.utc)",
    "for i in range(count):",
    `    record_prompt_run(data_dir / 'evidence.jsonl', project, 'provider', f'{project}-evt-{i:04d}', observed_at=base + timedelta(minutes=i))`,
  ].join("\n");
  execFileSync(PYTHON, ["-c", script], { cwd: PERFORMANCE_DIR });
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

describe("activity.listPromptRuns (Execution 03, end-to-end via the real Python bridge)", () => {
  const roots: string[] = [];
  afterEach(() => {
    while (roots.length) rmSync(roots.pop()!, { recursive: true, force: true });
  });
  function tempDataDir(): string {
    const root = mkdtempSync(join(tmpdir(), "midnight-activity-"));
    roots.push(root);
    return join(root, "data");
  }

  it("paginates more than 100 Prompt Runs via cursor with deterministic ordering and no duplicates", async () => {
    const dataDir = tempDataDir();
    seedLedger(dataDir, "activity-e2e", 205);
    const ctx = { binding: binding(dataDir, "activity-e2e") };

    const collected: string[] = [];
    let cursor: string | undefined;
    let pages = 0;
    for (;;) {
      const request: Record<string, unknown> = { limit: 100 };
      if (cursor) request.cursor = cursor;
      const result = await activityListPromptRuns(request, ctx);
      const events = result.events as { promptRunId: string; occurredAt: string }[];
      collected.push(...events.map((event) => event.promptRunId));
      pages += 1;
      expect(pages).toBeLessThan(10);
      if (result.complete) {
        expect(result.nextCursor).toBeNull();
        break;
      }
      expect(result.nextCursor).toBeTruthy();
      cursor = result.nextCursor as string;
    }

    expect(collected).toHaveLength(205);
    expect(new Set(collected).size).toBe(205); // no duplicate Prompt Runs across pages
    expect(pages).toBe(3);
  }, 30_000);

  it("never returns another project's identity, even when handed a foreign cursor", async () => {
    const dataDirA = tempDataDir();
    const dataDirB = tempDataDir();
    seedLedger(dataDirA, "project-a", 3);
    seedLedger(dataDirB, "project-b", 3);

    const ctxA = { binding: binding(dataDirA, "project-a") };
    const ctxB = { binding: binding(dataDirB, "project-b") };

    const pageA = await activityListPromptRuns({ limit: 1 }, ctxA);
    const cursorFromA = pageA.nextCursor as string;
    expect(cursorFromA).toBeTruthy();

    // A cursor minted for project A must never be usable against project B.
    await expect(activityListPromptRuns({ cursor: cursorFromA }, ctxB)).rejects.toThrow();

    const resultA = await activityListPromptRuns({}, ctxA);
    const resultB = await activityListPromptRuns({}, ctxB);
    const idsA = (resultA.events as { promptRunId: string }[]).map((event) => event.promptRunId);
    const idsB = (resultB.events as { promptRunId: string }[]).map((event) => event.promptRunId);
    expect(idsA.some((id) => idsB.includes(id))).toBe(false);
  }, 30_000);
});
