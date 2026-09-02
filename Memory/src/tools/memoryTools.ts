/**
 * Host-native Memory tool registry (Task 34).
 *
 * Exposes authorized READ/QUERY tools for agents using current MCP / host-
 * native capabilities. READ tools (search/get/history/related/explain/current/
 * lexical/timeline/context/health) are always available. MUTATION tools
 * (propose/promote/revise/delete) are SEPARATELY PERMISSIONED: they are only
 * listed/exposed when the host opts in (`allowMutations`), and each mutation
 * call flows through the engine's mutation authorization + origin logging
 * (Task 35), so agent-initiated mutations require an explicit project/user
 * policy and are always attributable.
 *
 * Tool `inputSchema` uses JSON Schema (object root) per the MCP tools shape.
 * Zero runtime dependencies: the registry is a bounded Memory-owned surface;
 * the MCP stdio adapter (src/tools/mcpServer.ts) speaks the JSON-RPC subset.
 */
import type { MemoryEngine } from "../engine/memoryEngine.ts";
import type { ActorInput } from "../engine/records.ts";

export type ToolCategory = "read" | "mutation";

export interface MemoryTool {
  name: string;
  title?: string;
  description: string;
  category: ToolCategory;
  /** JSON Schema (object root) describing the tool arguments. */
  inputSchema: Record<string, unknown>;
  handler(engine: MemoryEngine, args: Record<string, unknown>): unknown;
}

function str(args: Record<string, unknown>, key: string): string | undefined {
  const v = args[key];
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

function num(args: Record<string, unknown>, key: string): number | undefined {
  const v = args[key];
  return typeof v === "number" ? v : undefined;
}

function bool(args: Record<string, unknown>, key: string): boolean | undefined {
  const v = args[key];
  return typeof v === "boolean" ? v : undefined;
}

const requireStr = (args: Record<string, unknown>, key: string): string => {
  const v = str(args, key);
  if (v === undefined) throw new Error(`${key} is required`);
  return v;
};

const actorFrom = (args: Record<string, unknown>): ActorInput => ({
  kind: (str(args, "actorKind") as ActorInput["kind"]) ?? "agent",
  name: str(args, "actorName") ?? "memory-tool",
});

const READ_TOOLS: MemoryTool[] = [
  {
    name: "memory_search",
    description: "Search durable memory records with structured filters (scope, subject, tag, source engine, confidence, validity, time).",
    category: "read",
    inputSchema: {
      type: "object",
      properties: {
        scope: { type: "string" },
        query: { type: "string", description: "free-text subject/content contains" },
        exactSubject: { type: "string" },
        tag: { type: "string" },
        sourceEngine: { type: "string" },
        confidenceMin: { type: "number" },
        validAt: { type: "string" },
        limit: { type: "integer" },
      },
    },
    handler: (engine, args) =>
      engine.searchRecords({
        scope: str(args, "scope"),
        subjectContains: str(args, "query"),
        exactSubject: str(args, "exactSubject"),
        tag: str(args, "tag"),
        sourceEngine: str(args, "sourceEngine"),
        confidenceMin: num(args, "confidenceMin"),
        validAt: str(args, "validAt"),
        limit: num(args, "limit"),
      }),
  },
  {
    name: "memory_get",
    description: "Fetch a single memory record by id.",
    category: "read",
    inputSchema: { type: "object", properties: { recordId: { type: "string" } }, required: ["recordId"] },
    handler: (engine, args) => engine.getRecord(requireStr(args, "recordId")),
  },
  {
    name: "memory_history",
    description: "Fetch a record's full revision history and supersession chain.",
    category: "read",
    inputSchema: { type: "object", properties: { recordId: { type: "string" } }, required: ["recordId"] },
    handler: (engine, args) => engine.getRecordHistory(requireStr(args, "recordId")),
  },
  {
    name: "memory_related",
    description: "Fetch a record's outgoing/incoming relations, supersession links, and contradiction group.",
    category: "read",
    inputSchema: {
      type: "object",
      properties: { recordId: { type: "string" }, direction: { type: "string", enum: ["out", "in", "both"] } },
      required: ["recordId"],
    },
    handler: (engine, args) => engine.related(requireStr(args, "recordId"), (str(args, "direction") as "out" | "in" | "both") ?? "both"),
  },
  {
    name: "memory_explain",
    description: "Full provenance/authority/validity/contradiction/evidence-gap explanation for a record.",
    category: "read",
    inputSchema: { type: "object", properties: { recordId: { type: "string" }, at: { type: "string" } }, required: ["recordId"] },
    handler: (engine, args) => engine.explainRecord(requireStr(args, "recordId"), str(args, "at")),
  },
  {
    name: "memory_current",
    description: "The validity-aware current view for a scope (optionally a subject).",
    category: "read",
    inputSchema: {
      type: "object",
      properties: { scope: { type: "string" }, subject: { type: "string" }, at: { type: "string" }, limit: { type: "integer" } },
      required: ["scope"],
    },
    handler: (engine, args) => engine.currentRecords({ scope: requireStr(args, "scope"), subject: str(args, "subject"), at: str(args, "at"), limit: num(args, "limit") }),
  },
  {
    name: "memory_lexical",
    description: "BM25 lexical keyword search with per-hit field explanations and diagnostics.",
    category: "read",
    inputSchema: {
      type: "object",
      properties: { query: { type: "string" }, scope: { type: "string" }, limit: { type: "integer" } },
      required: ["query"],
    },
    handler: (engine, args) => engine.lexicalSearch(requireStr(args, "query"), { scope: str(args, "scope"), limit: num(args, "limit") }),
  },
  {
    name: "memory_timeline",
    description: "How a decision/subject evolved across time, with retirement reasons.",
    category: "read",
    inputSchema: { type: "object", properties: { scope: { type: "string" }, subject: { type: "string" } }, required: ["scope", "subject"] },
    handler: (engine, args) => engine.decisionTimeline(requireStr(args, "scope"), requireStr(args, "subject")),
  },
  {
    name: "memory_context",
    description: "Bounded context-oriented retrieval with explicit size/time/project filters and provenance-rich results.",
    category: "read",
    inputSchema: {
      type: "object",
      properties: {
        scope: { type: "string" },
        size: { type: "integer" },
        at: { type: "string" },
        minAuthority: { type: "string" },
        minConfidence: { type: "number" },
        sourceKinds: { type: "array", items: { type: "string" } },
      },
      required: ["scope"],
    },
    handler: (engine, args) =>
      engine.contextQuery({
        scope: requireStr(args, "scope"),
        query: str(args, "query"),
        size: num(args, "size"),
        at: str(args, "at"),
        minAuthority: str(args, "minAuthority") as never,
        minConfidence: num(args, "minConfidence"),
        sourceKinds: Array.isArray(args.sourceKinds) ? (args.sourceKinds as never) : undefined,
      }),
  },
  {
    name: "memory_health",
    description: "Store health: integrity, journal mode, applied migrations, event count.",
    category: "read",
    inputSchema: { type: "object", properties: {} },
    handler: (engine) => engine.doctor(),
  },
];

const MUTATION_TOOLS: MemoryTool[] = [
  {
    name: "memory_propose",
    description: "Propose a candidate into the intake stream (never a direct record). Requires a reason; caller for allowlist intake.",
    category: "mutation",
    inputSchema: {
      type: "object",
      properties: {
        scope: { type: "string" }, subject: { type: "string" }, content: { type: "string" }, reason: { type: "string" },
        sourceKind: { type: "string" }, actorKind: { type: "string" }, actorName: { type: "string" },
      },
      required: ["scope", "subject", "content", "reason"],
    },
    handler: (engine, args) =>
      engine.addCandidate({
        scope: requireStr(args, "scope"),
        kind: "fact",
        subject: requireStr(args, "subject"),
        content: requireStr(args, "content"),
        actor: actorFrom(args),
        method: "tool_propose",
        epistemicClass: "derived",
        confidence: num(args, "confidence") ?? 0.6,
        sourceKind: (str(args, "sourceKind") as never) ?? "unknown",
        reason: requireStr(args, "reason"),
      }),
  },
  {
    name: "memory_promote",
    description: "Promote a candidate (policy-gated; agents can never promote without an explicit project/user policy). Requires actor.",
    category: "mutation",
    inputSchema: {
      type: "object",
      properties: { candidateId: { type: "string" }, actorKind: { type: "string" }, actorName: { type: "string" } },
      required: ["candidateId", "actorName"],
    },
    handler: (engine, args) =>
      engine.promoteCandidate(requireStr(args, "candidateId"), { actor: actorFrom(args), origin: "mcp" }),
  },
  {
    name: "memory_revise",
    description: "Correct an active record (attributed; agents are refused unless explicitly authorized). Requires actor + reason.",
    category: "mutation",
    inputSchema: {
      type: "object",
      properties: {
        recordId: { type: "string" }, content: { type: "string" }, method: { type: "string" }, reason: { type: "string" },
        actorKind: { type: "string" }, actorName: { type: "string" },
      },
      required: ["recordId", "content", "reason", "actorName"],
    },
    handler: (engine, args) =>
      engine.reviseRecord(requireStr(args, "recordId"), {
        content: requireStr(args, "content"),
        actor: actorFrom(args),
        method: str(args, "method") ?? "tool_revise",
        reason: requireStr(args, "reason"),
        origin: "mcp",
      }),
  },
  {
    name: "memory_delete",
    description: "Tombstone a record (scrubs content, retains identity). Attributed; agents are refused unless explicitly authorized.",
    category: "mutation",
    inputSchema: {
      type: "object",
      properties: { recordId: { type: "string" }, reason: { type: "string" }, actorKind: { type: "string" }, actorName: { type: "string" } },
      required: ["recordId", "reason", "actorName"],
    },
    handler: (engine, args) =>
      engine.deleteRecord(requireStr(args, "recordId"), { actor: actorFrom(args), reason: requireStr(args, "reason"), origin: "mcp" }),
  },
];

export const MEMORY_TOOLS: readonly MemoryTool[] = [...READ_TOOLS, ...MUTATION_TOOLS];

export function readTools(): MemoryTool[] {
  return [...READ_TOOLS];
}

export function findTool(name: string): MemoryTool | undefined {
  return MEMORY_TOOLS.find((t) => t.name === name);
}