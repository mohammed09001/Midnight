/**
 * CHILD LOOP 1–3 verification — Tasks 33–35: Memory CLI, MCP/host-native read
 * tools, and mutation authorization + confirmation.
 *
 * T33: `record related` (and the related view surface) completes the CLI set
 *      (search/get/history/related/propose/promote/revise/contradictions/
 *      health) with stable JSON output.
 * T34: the host-native tool registry exposes READ tools always and MUTATION
 *      tools SEPARATELY (only when the host opts in); the MCP stdio adapter
 *      speaks initialize/tools/list/tools/call over JSON-RPC; mutations are
 *      refused when not enabled.
 * T35: explicit project/user mutation policy gates agent-initiated
 *      promote/revise/delete (MutationForbiddenError unless the agent is
 *      explicitly allowed); events log actor AND origin.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { fileURLToPath } from "node:url";

import { MemoryEngine } from "../src/index.ts";
import { MEMORY_TOOLS, readTools, findTool } from "../src/index.ts";
import { MutationForbiddenError } from "../src/contracts/errors.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = join(HERE, "..", "src", "cli", "cli.ts");

function tempEngine(name: string): { engine: MemoryEngine; dir: string; path: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t33-${name}-`));
  const path = join(dir, "memory.db");
  const engine = new MemoryEngine({ storePath: path });
  engine.open();
  return { engine, dir, path };
}

const AGENT = { kind: "agent" as const, name: "worker-a" };
const KIM = { kind: "human" as const, name: "kim" };

// ---- Task 33: CLI ------------------------------------------------------------

test("T33: record related surfaces relations via the CLI and the engine", () => {
  const { engine, dir, path } = tempEngine("cli-related");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord({ scope: "lib", kind: "fact", subject: "A", content: "a", actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9, sourceKind: "user_note", evidenceRefs: [{ engine: "external", ref: "n" }] });
    const b = engine.addRecord({ scope: "lib", kind: "fact", subject: "B", content: "b", actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9, sourceKind: "user_note", evidenceRefs: [{ engine: "external", ref: "n" }] });
    engine.addRelation(a.recordId, { type: "related", target: b.recordId, actor: KIM, method: "linked" });
    // Engine surface.
    const related = engine.related(a.recordId, "out");
    assert.ok(related.outgoing.some((h) => h.type === "related" && h.target === b.recordId));
    // CLI surface (stable JSON).
    const stdout = execFileSync(process.execPath, ["--experimental-strip-types", CLI_PATH, "record", "related", "--id", a.recordId, "--store", path], { encoding: "utf8", env: { ...process.env } });
    const parsed = JSON.parse(stdout) as { outgoing: Array<{ type: string }> };
    assert.ok(parsed.outgoing.some((h) => h.type === "related"));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

// ---- Task 34: MCP / host-native read tools ----------------------------------

test("T34: the host-native tool registry exposes read tools always, mutations separately", () => {
  assert.ok(MEMORY_TOOLS.some((t) => t.name === "memory_search"));
  assert.ok(MEMORY_TOOLS.some((t) => t.name === "memory_health"));
  const read = readTools();
  assert.ok(read.every((t) => t.category === "read"));
  assert.ok(!read.some((t) => t.name === "memory_promote"), "mutations are NOT in the read-only surface");
  // Every tool has a JSON-Schema object inputSchema.
  for (const t of read) {
    assert.equal(t.inputSchema.type, "object");
  }
  assert.ok(findTool("memory_get") !== undefined);
  assert.ok(findTool("memory_nope") === undefined);
});

test("T34: MCP stdio adapter — initialize, read-only tools/list, tools/call health, mutations refused", async () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t33-mcp-read-"));
  const path = join(dir, "memory.db");
  mkdirSync(dir, { recursive: true });
  const child = spawn(process.execPath, ["--experimental-strip-types", CLI_PATH, "mcp", "--store", path], { stdio: ["pipe", "pipe", "inherit"], env: { ...process.env } });
  try {
    const init = await sendMcp(child, { jsonrpc: "2.0", id: 1, method: "initialize", params: {} });
    assert.equal(init.result.serverInfo.name, "midnight-memory");
    assert.ok(init.result.capabilities.tools !== undefined);

    const list = await sendMcp(child, { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
    const names = list.result.tools.map((t: { name: string }) => t.name);
    assert.ok(names.includes("memory_search"));
    assert.ok(!names.includes("memory_delete"), "mutations are NOT listed by default (read-only)");

    const health = await sendMcp(child, { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "memory_health", arguments: {} } });
    assert.equal(health.result.content[0].type, "text");
    const report = JSON.parse(health.result.content[0].text) as { healthy: boolean };
    assert.equal(report.healthy, true);

    // A mutation tool is a protocol error when mutations are not enabled.
    const mut = await sendMcp(child, { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "memory_delete", arguments: {} } });
    assert.ok(mut.error !== undefined, "mutation call without allowMutations is refused");
  } finally {
    child.kill();
    await new Promise((r) => child.on("close", r));
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T34: MCP with --allow-mutations exposes mutations, gated by the scope mutation policy", async () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t33-mcp-mut-"));
  const path = join(dir, "memory.db");
  mkdirSync(dir, { recursive: true });
  // Seed a scope + record + a restricted mutation policy allowing ONLY kim.
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.addRecord({ scope: "lib", kind: "fact", subject: "A", content: "a", actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9, sourceKind: "user_note", evidenceRefs: [{ engine: "external", ref: "n" }] });
    engine.setScopeMutationPolicy("lib", { mode: "restricted", allow: ["human:kim"] });
    engine.close();
  }
  const child = spawn(process.execPath, ["--experimental-strip-types", CLI_PATH, "mcp", "--allow-mutations", "--store", path], { stdio: ["pipe", "pipe", "inherit"], env: { ...process.env } });
  try {
    await sendMcp(child, { jsonrpc: "2.0", id: 1, method: "initialize", params: {} });
    const list = await sendMcp(child, { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
    assert.ok(list.result.tools.some((t: { name: string }) => t.name === "memory_delete"), "mutations listed when allowed");

    // The tool default actor is "agent:memory-tool" — NOT in the restricted
    // allow list → the mutation is refused by the policy.
    const denied = await sendMcp(child, { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "memory_delete", arguments: { recordId: "mem_x", reason: "r", actorName: "worker-a" } } });
    assert.ok(denied.result.isError === true || denied.error !== undefined, "unauthorized agent mutation is refused");
  } finally {
    child.kill();
    await new Promise((r) => child.on("close", r));
    rmSync(dir, { recursive: true, force: true });
  }
});

// ---- Task 35: mutation authorization + origin -------------------------------

test("T35: restricted mutation policy requires explicit authorization for agent-initiated mutations", () => {
  const { engine, dir } = tempEngine("policy");
  try {
    engine.createScope("lib", "Library");
    const r = engine.addRecord({ scope: "lib", kind: "fact", subject: "A", content: "a", actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9, sourceKind: "user_note", evidenceRefs: [{ engine: "external", ref: "n" }] });
    engine.setScopeMutationPolicy("lib", { mode: "restricted", allow: ["human:kim"] });
    // Agent-initiated delete is refused by the explicit policy.
    assert.throws(
      () => engine.deleteRecord(r.recordId, { actor: AGENT, reason: "cleanup" }),
      (err: unknown) => err instanceof MutationForbiddenError,
    );
    // A human in the allow list succeeds.
    const deleted = engine.deleteRecord(r.recordId, { actor: KIM, reason: "cleanup", origin: "cli" });
    assert.equal(deleted.status, "deleted");
    // Open (default) policy: structural rules apply (agents still blocked).
    engine.setScopeMutationPolicy("lib", { mode: "open", allow: [] });
    const r2 = engine.addRecord({ scope: "lib", kind: "fact", subject: "B", content: "b", actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9, sourceKind: "user_note", evidenceRefs: [{ engine: "external", ref: "n" }] });
    assert.throws(
      () => engine.deleteRecord(r2.recordId, { actor: AGENT, reason: "x" }),
      (err: unknown) => err instanceof Error, // CorrectionForbiddenError (structural)
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T35: explicitly authorizing a specific agent in the policy permits its mutation; origin is logged", () => {
  const { engine, dir } = tempEngine("explicit-agent");
  try {
    engine.createScope("lib", "Library");
    const r = engine.addRecord({ scope: "lib", kind: "fact", subject: "A", content: "a", actor: KIM, method: "m", epistemicClass: "observed", confidence: 0.9, sourceKind: "user_note", evidenceRefs: [{ engine: "external", ref: "n" }] });
    engine.setScopeMutationPolicy("lib", { mode: "restricted", allow: ["agent:worker-a"] });
    // The project has EXPLICITLY authorized this agent for mutations.
    const revised = engine.reviseRecord(r.recordId, { content: "a2", actor: AGENT, method: "agent-revise", reason: "authorized by policy", origin: "mcp" });
    assert.equal(revised.content, "a2");
    // The revision event logs both actor and origin.
    const events = engine.listEvents(20).filter((e) => e.type === "memory.record.revised");
    const last = events[0]!;
    const payload = last.payload as { actor: string; origin: string };
    assert.equal(payload.actor, "agent:worker-a");
    assert.equal(payload.origin, "mcp");
    // A different agent is still refused.
    assert.throws(
      () => engine.deleteRecord(r.recordId, { actor: { kind: "agent", name: "worker-b" }, reason: "x" }),
      (err: unknown) => err instanceof MutationForbiddenError,
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

function sendMcp(child: ChildProcess, msg: Record<string, unknown>): Promise<{ result: any; error?: { code: number; message: string } }> {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const onData = (chunk: Buffer): void => {
      buffer += chunk.toString("utf8");
      const nl = buffer.indexOf("\n");
      if (nl === -1) return;
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line.length === 0) return;
      child.stdout!.off("data", onData);
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(line) as Record<string, unknown>;
      } catch {
        reject(new Error(`unparseable MCP response: ${line}`));
        return;
      }
      resolve(parsed as unknown as { result: any; error?: { code: number; message: string } });
    };
    child.stdout!.on("data", onData);
    child.stdin!.write(`${JSON.stringify(msg)}\n`);
  });
}