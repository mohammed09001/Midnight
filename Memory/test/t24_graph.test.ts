/**
 * CHILD LOOP 1 verification — Task 24: optional relationship-graph projection.
 * Proves: the graph is a DERIVED projection (nodes for records/entities/
 * external refs; edges for typed relations with provenance, supersession
 * chains, contradiction groups); versioned + rebuildable with the
 * observability event; bounded traversal (out/in/both, relation-type filter,
 * depth cap + truncation) including the supersession-history experiment;
 * typed failures; determinism; and restart survival.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { NotFoundError, ValidationError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t24-${name}-`));
  const engine = new MemoryEngine({ storePath: join(dir, "memory.db") });
  engine.open();
  return { engine, dir };
}

function rec(
  scope: string,
  subject: string,
  content: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    scope,
    kind: "fact" as const,
    subject,
    content,
    actor: { kind: "human" as const, name: "kim" },
    method: "asserted",
    epistemicClass: "observed" as const,
    confidence: 0.9,
    sourceKind: "user_note" as const,
    evidenceRefs: [{ engine: "external" as const, ref: `note:${Math.random()}` }],
    ...overrides,
  };
}

test("T24: graph projection builds record/entity/external nodes and typed edges", () => {
  const { engine, dir } = tempEngine("projection");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "Gateway", "gateway"));
    const b = engine.addRecord(rec("lib", "Rate limit", "120 rpm"));
    engine.addRelation(a.recordId, {
      type: "related", target: b.recordId,
      actor: { kind: "engine", name: "pp" }, method: "linked",
    });
    engine.addRelation(a.recordId, {
      type: "applies_to", target: "entity:component:api-gateway",
      actor: { kind: "engine", name: "pp" }, method: "classified",
    });
    engine.addRelation(a.recordId, {
      type: "learned_from", target: "engine:study_document:lesson-9",
      actor: { kind: "engine", name: "pp" }, method: "extracted",
    });

    const graph = engine.graphProjection("lib");
    // Nodes: 2 records + 1 entity + 1 external.
    assert.equal(graph.nodeCount, 4);
    assert.ok(graph.nodes.some((n) => n.kind === "record" && n.id === a.recordId));
    assert.ok(graph.nodes.some((n) => n.kind === "record" && n.id === b.recordId));
    assert.ok(graph.nodes.some((n) => n.kind === "entity" && n.id === "entity:component:api-gateway"));
    assert.ok(graph.nodes.some((n) => n.kind === "external" && n.id === "engine:study_document:lesson-9"));
    // Edges: related (record→record), applies_to (record→entity), learned_from (record→external).
    assert.ok(graph.edges.some((e) => e.type === "related" && e.from === a.recordId && e.to === b.recordId));
    const applies = graph.edges.find((e) => e.type === "applies_to");
    assert.ok(applies !== undefined);
    assert.equal(applies!.to, "entity:component:api-gateway");
    // Typed relation edges carry provenance.
    const relatedEdge = graph.edges.find((e) => e.type === "related")!;
    assert.equal(relatedEdge.provenance!.actor.name, "pp");
    assert.equal(relatedEdge.provenance!.method, "linked");
    // Versioning surface present.
    assert.equal(graph.schemaVersion, "1");
    assert.ok(graph.version.startsWith("1.25.0.p"));
    assert.ok(!Number.isNaN(Date.parse(graph.builtAt)));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T24: graph surfaces supersession chains and contradiction groups", () => {
  const { engine, dir } = tempEngine("chain");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(rec("lib", "Deploy window", "Friday"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "Tuesday",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "schedule change",
    });
    // A contradiction group adds pairwise contradicts edges.
    const c1 = engine.addRecord(rec("lib", "Region", "eu-west-1"));
    const c2 = engine.addRecord(rec("lib", "Region", "eu-central-1"));
    engine.registerContradiction("lib", "Region", [c1.recordId, c2.recordId]);

    const graph = engine.graphProjection("lib");
    assert.ok(graph.edges.some((e) => e.type === "supersedes" && e.from === v2.recordId && e.to === v1.recordId));
    assert.ok(graph.edges.some((e) => e.type === "superseded_by" && e.from === v1.recordId && e.to === v2.recordId));
    assert.ok(graph.edges.some((e) => e.type === "contradicts" && e.from === c1.recordId && e.to === c2.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T24: traversal — out/in/both, relation-type filter, depth cap, truncation", () => {
  const { engine, dir } = tempEngine("traversal");
  try {
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "A", "a"));
    const b = engine.addRecord(rec("lib", "B", "b"));
    const c = engine.addRecord(rec("lib", "C", "c"));
    engine.addRelation(a.recordId, { type: "related", target: b.recordId, actor: { kind: "human", name: "kim" }, method: "x" });
    engine.addRelation(b.recordId, { type: "related", target: c.recordId, actor: { kind: "human", name: "kim" }, method: "x" });
    engine.addRelation(a.recordId, { type: "applies_to", target: "entity:component:gw", actor: { kind: "human", name: "kim" }, method: "x" });

    // Outgoing from A: B (depth 1), C (depth 2), entity (depth 1).
    const out = engine.traverseGraph("lib", a.recordId, { direction: "out", maxDepth: 3 });
    assert.ok(out.nodes.some((n) => n.id === b.recordId));
    assert.ok(out.nodes.some((n) => n.id === c.recordId));
    assert.ok(out.nodes.some((n) => n.id === "entity:component:gw"));

    // Depth cap: maxDepth 1 from A reaches only B + entity, not C.
    const shallow = engine.traverseGraph("lib", a.recordId, { direction: "out", maxDepth: 1 });
    assert.ok(!shallow.nodes.some((n) => n.id === c.recordId));
    assert.equal(shallow.truncated, true, "depth cap truncates reachable nodes");

    // Relation-type filter: only applies_to edges.
    const filtered = engine.traverseGraph("lib", a.recordId, { direction: "out", relationTypes: ["applies_to"], maxDepth: 3 });
    assert.ok(filtered.nodes.some((n) => n.id === "entity:component:gw"));
    assert.ok(!filtered.nodes.some((n) => n.id === b.recordId));

    // Incoming to C: B (depth 1), A (depth 2).
    const incoming = engine.traverseGraph("lib", c.recordId, { direction: "in", maxDepth: 3 });
    assert.ok(incoming.nodes.some((n) => n.id === b.recordId));
    assert.ok(incoming.nodes.some((n) => n.id === a.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T24: history experiment — traversing the supersession chain", () => {
  const { engine, dir } = tempEngine("history");
  try {
    engine.createScope("lib", "Library");
    const v1 = engine.addRecord(rec("lib", "Region", "eu-west-1"));
    const v2 = engine.supersedeRecord(v1.recordId, {
      content: "eu-central-1",
      actor: { kind: "human", name: "kim" },
      method: "decided",
      reason: "latency",
    });
    // Follow supersession history from the successor.
    const history = engine.traverseGraph("lib", v2.recordId, {
      direction: "out",
      relationTypes: ["supersedes"],
      maxDepth: 3,
    });
    const chain = history.nodes.map((n) => n.id);
    assert.ok(chain.includes(v1.recordId), "predecessor reachable via supersedes edge");
    assert.equal(history.edges.every((e) => e.type === "supersedes"), true);
    // Both directions (out + in) from the successor also surface superseded_by.
    const both = engine.traverseGraph("lib", v2.recordId, { direction: "both", relationTypes: ["supersedes", "superseded_by"], maxDepth: 3 });
    assert.ok(both.nodes.some((n) => n.id === v1.recordId));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T24: rebuild emits the observability event; determinism holds", () => {
  const { engine, dir } = tempEngine("rebuild");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "a"));
    const p1 = engine.graphProjection("lib");
    const rebuilt = engine.rebuildGraphProjection("lib");
    assert.equal(rebuilt.nodeCount, p1.nodeCount);
    assert.ok(p1.version !== rebuilt.version, "fresh version stamp per rebuild");
    assert.ok(engine.listEvents(20).some((e) => e.type === "memory.graph.projection.rebuilt"));
    // Deterministic content across builds.
    const p2 = engine.graphProjection("lib");
    assert.deepEqual(
      p1.nodes.map((n) => n.id),
      p2.nodes.map((n) => n.id),
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T24: negative — unknown start, empty start, unknown scope, restart survival", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t24-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    const a = engine.addRecord(rec("lib", "A", "a"));
    assert.throws(
      () => engine.traverseGraph("lib", "mem_nonexistent"),
      (err: unknown) => err instanceof NotFoundError,
    );
    assert.throws(
      () => engine.traverseGraph("lib", "   "),
      (err: unknown) => err instanceof ValidationError,
    );
    assert.throws(
      () => engine.graphProjection("nope"),
      (err: unknown) => err instanceof NotFoundError,
    );
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const graph = engine.graphProjection("lib");
      assert.equal(graph.nodeCount, 1);
      const traversal = engine.traverseGraph("lib", graph.nodes[0]!.id, { maxDepth: 2 });
      assert.ok(traversal.nodes.some((n) => n.id === graph.nodes[0]!.id));
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});