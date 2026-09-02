/**
 * CHILD LOOP 2 verification — Task 22: entity linking as a derived projection.
 * Proves: the bounded entity taxonomy (component/repository/technology/
 * decision), explicit `applies_to` entity extraction, subject auto-linking,
 * link-kind classification, first/last-seen instants, versioning, the
 * rebuild observability event, parser edge cases, determinism, and restart
 * survival. The projection is DERIVED (no canonical entity table).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryEngine } from "../src/index.ts";
import { parseEntityTarget } from "../src/engine/entities.ts";
import { NotFoundError } from "../src/contracts/errors.ts";

function tempEngine(name: string): { engine: MemoryEngine; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), `mem-t22-${name}-`));
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

test("T22: entity projection extracts explicit applies_to links across the taxonomy", () => {
  const { engine, dir } = tempEngine("extract");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Gateway decision", "gateway chosen", {
      relationHints: [{ type: "applies_to", target: "entity:component:api-gateway" }],
    }));
    engine.addRecord(rec("lib", "Repo note", "repo moved", {
      relationHints: [{ type: "applies_to", target: "entity:repository:memory-engine" }],
    }));
    engine.addRecord(rec("lib", "Tech note", "uses sqlite", {
      relationHints: [{ type: "applies_to", target: "entity:technology:sqlite" }],
    }));
    engine.addRecord(rec("lib", "Cadence decision", "ship tuesday", {
      relationHints: [{ type: "applies_to", target: "entity:decision:release-cadence" }],
    }));

    const projection = engine.entityProjection("lib");
    assert.equal(projection.scopeId, engine.getScope("lib").scopeId);
    assert.equal(projection.entityCount, 4);
    const keys = projection.entities.map((e) => e.entity).sort();
    assert.deepEqual(keys, [
      "component:api-gateway",
      "decision:release-cadence",
      "repository:memory-engine",
      "technology:sqlite",
    ]);
    for (const entry of projection.entities) {
      assert.equal(entry.records.length, 1);
      assert.equal(entry.records[0]!.linkKind, "applies_to");
      assert.equal(entry.explicitCount, 1);
      assert.equal(entry.autoCount, 0);
    }
    // Versioning surface present.
    assert.equal(projection.schemaVersion, "1");
    assert.ok(projection.version.startsWith("1.27.0.p"), "version carries the contract version + build counter");
    assert.ok(!Number.isNaN(Date.parse(projection.builtAt)));
    assert.ok(!Number.isNaN(Date.parse(projection.entities[0]!.firstSeenAt)));
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T22: subject auto-linking — records whose subject matches an entity name are linked", () => {
  const { engine, dir } = tempEngine("auto-link");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Gateway decision", "gateway chosen", {
      relationHints: [{ type: "applies_to", target: "entity:component:api-gateway" }],
    }));
    // Auto-link: subject exactly equals the entity name.
    engine.addRecord(rec("lib", "api-gateway", "another record about the gateway"));

    const projection = engine.entityProjection("lib");
    const gateway = projection.entities.find((e) => e.entity === "component:api-gateway")!;
    assert.equal(gateway.records.length, 2);
    const explicit = gateway.records.find((r) => r.linkKind === "applies_to");
    const auto = gateway.records.find((r) => r.linkKind === "subject");
    assert.ok(explicit !== undefined);
    assert.ok(auto !== undefined, "subject match auto-links a record");
    assert.equal(gateway.explicitCount, 1);
    assert.equal(gateway.autoCount, 1);
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T22: unknown entity kinds classify as 'other'; non-entity targets are ignored", () => {
  const { engine, dir } = tempEngine("other");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "Custom entity", "custom", {
      relationHints: [{ type: "applies_to", target: "entity:widget:thingamajig" }],
    }));
    // A non-applies_to relation is NOT treated as an entity link.
    engine.addRecord(rec("lib", "Related", "related", {
      relationHints: [{ type: "related", target: "entity:component:ignored" }],
    }));
    const projection = engine.entityProjection("lib");
    assert.equal(projection.entityCount, 1);
    assert.equal(projection.entities[0]!.kind, "other");
    assert.equal(projection.entities[0]!.name, "thingamajig");
    assert.equal(projection.entities[0]!.entity, "other:thingamajig");
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T22: rebuild forces a fresh projection and emits the observability event", () => {
  const { engine, dir } = tempEngine("rebuild");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "a", {
      relationHints: [{ type: "applies_to", target: "entity:component:x" }],
    }));
    const before = engine.entityProjection("lib");
    const rebuilt = engine.rebuildEntityProjection("lib");
    assert.equal(rebuilt.entityCount, 1);
    assert.ok(before.version !== rebuilt.version, "each build carries a fresh version stamp");
    assert.ok(
      engine.listEvents(20).some((e) => e.type === "memory.entities.projection.rebuilt"),
      "rebuild emits memory.entities.projection.rebuilt",
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T22: determinism — identical corpus yields identical entity sets", () => {
  const { engine, dir } = tempEngine("determinism");
  try {
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "a", {
      relationHints: [{ type: "applies_to", target: "entity:component:z" }],
    }));
    engine.addRecord(rec("lib", "B", "b", {
      relationHints: [{ type: "applies_to", target: "entity:technology:y" }],
    }));
    const p1 = engine.entityProjection("lib");
    const p2 = engine.entityProjection("lib");
    assert.deepEqual(
      p1.entities.map((e) => [e.entity, e.records.length]),
      p2.entities.map((e) => [e.entity, e.records.length]),
    );
  } finally {
    engine.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("T22: parser edge cases", () => {
  assert.deepEqual(parseEntityTarget("entity:component:api-gateway"), { kind: "component", name: "api-gateway" });
  assert.deepEqual(parseEntityTarget("entity:technology:sqlite"), { kind: "technology", name: "sqlite" });
  assert.deepEqual(parseEntityTarget("entity:decision:release-cadence"), { kind: "decision", name: "release-cadence" });
  assert.deepEqual(parseEntityTarget("entity:repository:memory-engine"), { kind: "repository", name: "memory-engine" });
  // Missing kind → "other"; unknown kind → "other".
  assert.deepEqual(parseEntityTarget("entity:api-gateway"), { kind: "other", name: "api-gateway" });
  assert.deepEqual(parseEntityTarget("entity:widget:thing"), { kind: "other", name: "thing" });
  // Non-entity / malformed targets → null.
  assert.equal(parseEntityTarget("mem_01ABC"), null);
  assert.equal(parseEntityTarget("engine:context:pack-1"), null);
  assert.equal(parseEntityTarget("entity:"), null);
  assert.equal(parseEntityTarget(""), null);
});

test("T22: unknown scope is a typed not-found; projection survives restart", () => {
  const dir = mkdtempSync(join(tmpdir(), "mem-t22-restart-"));
  const path = join(dir, "memory.db");
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    engine.createScope("lib", "Library");
    engine.addRecord(rec("lib", "A", "a", {
      relationHints: [{ type: "applies_to", target: "entity:component:gateway" }],
    }));
    assert.throws(
      () => engine.entityProjection("nope"),
      (err: unknown) => err instanceof NotFoundError,
    );
    engine.close();
  }
  {
    const engine = new MemoryEngine({ storePath: path });
    engine.open();
    try {
      const projection = engine.entityProjection("lib");
      assert.equal(projection.entityCount, 1);
      assert.equal(projection.entities[0]!.entity, "component:gateway");
    } finally {
      engine.close();
    }
  }
  rmSync(dir, { recursive: true, force: true });
});