/**
 * MCP stdio adapter (Task 34).
 *
 * A bounded, Memory-owned MCP-compatible server speaking the JSON-RPC 2.0
 * subset over stdio (newline-delimited messages per the MCP stdio transport):
 * `initialize`, `notifications/initialized`, `tools/list`, `tools/call`.
 *
 * READ tools are always exposed. MUTATION tools are SEPARATELY PERMISSIONED:
 * they are listed/called only when the host opts in (`allowMutations:
 * true`), and every mutation call flows through the engine's mutation
 * authorization + origin logging (Task 35) with `origin: "mcp"` — so an
 * agent-initiated mutation requires an explicit project/user policy and is
 * always attributable.
 *
 * Tool shape follows the current MCP spec line (2026-07-28): `name`,
 * `description`, `inputSchema` (JSON Schema object root); `tools/call` returns
 * `{content: [{type: "text", text}]}` (JSON-serialized) and reports tool
 * execution failures with `isError: true`. Zero runtime dependencies.
 */
import { createInterface } from "node:readline";
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import type { MemoryEngine } from "../engine/memoryEngine.ts";
import { MEMORY_TOOLS, readTools } from "./memoryTools.ts";

export interface McpServerOptions {
  /** Expose the separately-permissioned mutation tools. Default false (read-only). */
  allowMutations?: boolean;
}

interface JsonRpcMessage {
  jsonrpc?: string;
  id?: unknown;
  method?: string;
  params?: Record<string, unknown>;
}

const PROTOCOL_VERSION = "2026-07-28";

function send(message: unknown): void {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function writeResponse(id: unknown, result: unknown, error?: { code: number; message: string }): void {
  if (error !== undefined) {
    send({ jsonrpc: "2.0", id, error });
  } else {
    send({ jsonrpc: "2.0", id, result });
  }
}

function handleMessage(engine: MemoryEngine, options: McpServerOptions, msg: JsonRpcMessage): void {
  // Notifications (no id) never get a response.
  if (msg.id === undefined) return;

  if (msg.method === "initialize") {
    writeResponse(msg.id, {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: { tools: {} },
      serverInfo: { name: "midnight-memory", version: MEMORY_ENGINE_CONTRACT_VERSION },
    });
    return;
  }

  switch (msg.method) {
    case "tools/list": {
      const tools = (options.allowMutations === true ? MEMORY_TOOLS : readTools()).map((t) => ({
        name: t.name,
        ...(t.title !== undefined ? { title: t.title } : {}),
        description: t.description,
        inputSchema: t.inputSchema,
      }));
      writeResponse(msg.id, { tools });
      return;
    }
    case "tools/call": {
      const params = msg.params ?? {};
      const name = typeof params["name"] === "string" ? params["name"] : "";
      const tool = MEMORY_TOOLS.find((t) => t.name === name);
      if (tool === undefined) {
        writeResponse(msg.id, undefined, { code: -32602, message: `Unknown tool: ${name}` });
        return;
      }
      if (tool.category === "mutation" && options.allowMutations !== true) {
        writeResponse(msg.id, undefined, {
          code: -32001,
          message: `tool '${name}' is a mutation and is not enabled: mutations are separately permissioned (start with allowMutations)`,
        });
        return;
      }
      try {
        const value = tool.handler(engine, (params["arguments"] ?? {}) as Record<string, unknown>);
        writeResponse(msg.id, { content: [{ type: "text", text: JSON.stringify(value) }] });
      } catch (err) {
        writeResponse(msg.id, {
          content: [{ type: "text", text: err instanceof Error ? err.message : String(err) }],
          isError: true,
        });
      }
      return;
    }
    default:
      writeResponse(msg.id, undefined, { code: -32601, message: `Method not found: ${String(msg.method)}` });
  }
}

/**
 * Run the MCP stdio server until stdin closes. Reads newline-delimited
 * JSON-RPC messages from stdin and writes responses to stdout (only valid MCP
 * messages on stdout; diagnostics may go to stderr).
 */
export function runMcpServer(engine: MemoryEngine, options: McpServerOptions = {}): void {
  const rl = createInterface({ input: process.stdin });
  rl.on("line", (line) => {
    const trimmed = line.trim();
    if (trimmed.length === 0) return;
    let msg: JsonRpcMessage;
    try {
      msg = JSON.parse(trimmed) as JsonRpcMessage;
    } catch {
      // Malformed input is ignored (the transport must stay clean); log to stderr.
      process.stderr.write("ignoring malformed MCP message\n");
      return;
    }
    handleMessage(engine, options, msg);
  });
}