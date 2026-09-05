import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { OPERATIONS } from "../../host/operations/registry";

const HOST_DIR = join(__dirname, "..", "..", "host");
// Forbidden module/name references — checked against actual code lines
// (imports and string literals used as identifiers), never doc-comment
// prose, so this file's own explanation of what it deliberately avoids
// does not trip its own audit.
const FORBIDDEN_IMPORT_PATTERN = /^\s*import\b.*from\s+["'][^"']*(read_tools|orchestration)[^"']*["']/;
const FORBIDDEN_STRING_LITERALS = ["performance.read_projection", "performance.request_analysis", "prompt.generate", "PROMPT_GENERATE"];
const CODE_LINE = /^\s*(\*|\/\/|\/\*)/; // comment lines are excluded from the literal scan

function collectTsFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "dist" || entry === "node_modules") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...collectTsFiles(full));
    } else if (entry.endsWith(".ts")) {
      files.push(full);
    }
  }
  return files;
}

describe("Desktop Host operation registry (Execution 03, requirement 17; Execution 12 addition)", () => {
  it("exposes exactly the five named operations and nothing else", () => {
    expect(Object.keys(OPERATIONS)).toEqual([
      "activity.listPromptRuns",
      "graph.getPromptRun",
      "graph.refreshMemoryCitation",
      "insights.getTerminalCard",
      "insights.recordInsightFeedback",
    ]);
  });

  it("contains only read-shaped operation names, except the one explicit, narrowly-scoped write", () => {
    const mutationHints = ["write", "create", "update", "delete", "record", "mutate", "propose", "promote", "revise"];
    for (const name of Object.keys(OPERATIONS)) {
      // Execution 12: `insights.recordInsightFeedback` is the registry's one
      // deliberate write — it closes the feedback loop (open/save/dismiss)
      // on an already-exposed insight into `repo_intelligence_store`, per
      // the fixed contract. Every other operation stays read-shaped.
      if (name === "insights.recordInsightFeedback") continue;
      const lower = name.toLowerCase();
      for (const hint of mutationHints) {
        expect(lower).not.toContain(hint);
      }
    }
  });

  it("never imports Performance's generic MCP read surface or orchestration module, anywhere under desktop/host", () => {
    const files = collectTsFiles(HOST_DIR);
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      for (const line of readFileSync(file, "utf-8").split("\n")) {
        expect(line, `${file} must not import read_tools/orchestration`).not.toMatch(FORBIDDEN_IMPORT_PATTERN);
      }
    }
  });

  it("never uses the generic read_projection/request_analysis/prompt.generate identifiers as live code", () => {
    const files = collectTsFiles(HOST_DIR);
    for (const file of files) {
      for (const line of readFileSync(file, "utf-8").split("\n")) {
        if (CODE_LINE.test(line)) continue; // skip documentation lines
        for (const forbidden of FORBIDDEN_STRING_LITERALS) {
          expect(line, `${file} must not reference '${forbidden}' as live code`).not.toContain(forbidden);
        }
      }
    }
  });

  it("only ever invokes the narrow desktop_bridge module, never a broader Performance entry point", () => {
    const source = readFileSync(join(HOST_DIR, "operations", "activityListPromptRuns.ts"), "utf-8");
    expect(source).toContain("midnight_performance.desktop_bridge");
  });

  it("only ever invokes the narrow graph_bridge module, never a broader Performance entry point", () => {
    const source = readFileSync(join(HOST_DIR, "operations", "getPromptRunGraph.ts"), "utf-8");
    expect(source).toContain("midnight_performance.graph_bridge");
  });

  it("only ever invokes the narrow memory_lineage_bridge module, never a broader Performance entry point", () => {
    const source = readFileSync(join(HOST_DIR, "operations", "refreshMemoryCitation.ts"), "utf-8");
    expect(source).toContain("midnight_performance.memory_lineage_bridge");
  });

  it("only ever invokes the narrow repo_intelligence_bridge module for insights.getTerminalCard", () => {
    const source = readFileSync(join(HOST_DIR, "operations", "getTerminalCard.ts"), "utf-8");
    expect(source).toContain("midnight_performance.repo_intelligence_bridge");
  });

  it("only ever invokes the narrow repo_intelligence_bridge module for insights.recordInsightFeedback", () => {
    const source = readFileSync(join(HOST_DIR, "operations", "recordInsightFeedback.ts"), "utf-8");
    expect(source).toContain("midnight_performance.repo_intelligence_bridge");
  });
});
