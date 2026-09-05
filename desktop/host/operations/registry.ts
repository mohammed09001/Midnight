/**
 * The Desktop Host's entire operation dispatch surface (requirements 9/10):
 * narrowly named operations only, never generic process/filesystem access.
 * Today this is exactly `{"activity.listPromptRuns", "graph.getPromptRun",
 * "graph.refreshMemoryCitation", "insights.getTerminalCard",
 * "insights.recordInsightFeedback"}`. `graph.getPromptRun` reads the real,
 * bounded Actual Performance Graph for one Prompt Run (Execution 06's
 * materializer) — the Expected Graph and any Expected-vs-Actual overlay
 * remain permanently out of scope for this whole execution series and are
 * never reserved here. `graph.refreshMemoryCitation` (Execution 09) is a
 * SEPARATE, narrowly-scoped read: one cited Memory reference's current
 * state, never a second way to fetch or mutate a Prompt Run graph. Adding
 * any further graph read means adding a new named entry, never a generic
 * passthrough.
 *
 * `insights.getTerminalCard` (Execution 12) reads Repo Intelligent's single
 * current terminal insight card for a project — never a list — and
 * `insights.recordInsightFeedback` is this registry's one deliberate WRITE:
 * it closes the feedback loop (open/save/dismiss) on one already-exposed
 * insight into `repo_intelligence_store`, and touches nothing else (never a
 * second way to mutate a Prompt Run graph or Memory record).
 *
 * This module deliberately does NOT import `read_tools.py`'s generic
 * MCP-shaped `performance.read_projection` / `performance.request_analysis`
 * surface (which can reach the `recommendations` projection by name) or
 * `orchestration.PerformanceCapability.PROMPT_GENERATE` — satisfying the
 * requirement that neither is part of the default Desktop/MCP read surface.
 * `desktop/tests/host/hostRegistry.test.ts` asserts this registry's key set
 * stays exactly `["activity.listPromptRuns", "graph.getPromptRun",
 * "graph.refreshMemoryCitation", "insights.getTerminalCard",
 * "insights.recordInsightFeedback"]`.
 */

import { activityListPromptRuns } from "./activityListPromptRuns.js";
import type { Operation } from "./activityListPromptRuns.js";
import { getPromptRunGraph } from "./getPromptRunGraph.js";
import { refreshMemoryCitation } from "./refreshMemoryCitation.js";
import { getTerminalCard } from "./getTerminalCard.js";
import { recordInsightFeedback } from "./recordInsightFeedback.js";

export const OPERATIONS: Readonly<Record<string, Operation>> = Object.freeze({
  "activity.listPromptRuns": activityListPromptRuns,
  "graph.getPromptRun": getPromptRunGraph,
  "graph.refreshMemoryCitation": refreshMemoryCitation,
  "insights.getTerminalCard": getTerminalCard,
  "insights.recordInsightFeedback": recordInsightFeedback,
});
