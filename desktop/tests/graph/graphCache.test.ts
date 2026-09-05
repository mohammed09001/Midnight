import { describe, expect, it } from "vitest";
import { buildGraphCacheKey, GraphCache, sliceFromBounds } from "../../src/graph/graphCache";
import type { GraphProjectionIdentity } from "../../src/graph/types";

function identity(overrides: Partial<GraphProjectionIdentity> = {}): GraphProjectionIdentity {
  return {
    project: "mp:v1:project:p1",
    root: "mp:v1:prompt_run:root1",
    graphSchemaVersion: 1,
    graphAlgorithmMethod: "relationship-graph",
    graphAlgorithmVersion: "1",
    evidenceCheckpoint: "checkpoint-1",
    ...overrides,
  };
}

const SLICE = { maxDepth: null, maxNodes: 200, maxEdges: 400, allowedLayers: null, focusNode: null, cursor: null };

describe("buildGraphCacheKey", () => {
  it("produces the same key for identical inputs (deterministic slice)", () => {
    expect(buildGraphCacheKey(identity(), SLICE)).toBe(buildGraphCacheKey(identity(), SLICE));
  });

  it("produces a different key when evidenceCheckpoint changes (cache invalidation after evidence changes)", () => {
    const before = buildGraphCacheKey(identity({ evidenceCheckpoint: "checkpoint-1" }), SLICE);
    const after = buildGraphCacheKey(identity({ evidenceCheckpoint: "checkpoint-2" }), SLICE);
    expect(before).not.toBe(after);
  });

  it("produces a different key for a different project, even with everything else identical", () => {
    const projectA = buildGraphCacheKey(identity({ project: "mp:v1:project:a" }), SLICE);
    const projectB = buildGraphCacheKey(identity({ project: "mp:v1:project:b" }), SLICE);
    expect(projectA).not.toBe(projectB);
  });

  it("produces a different key for a different slice (maxDepth)", () => {
    const shallow = buildGraphCacheKey(identity(), { ...SLICE, maxDepth: 1 });
    const deep = buildGraphCacheKey(identity(), { ...SLICE, maxDepth: 2 });
    expect(shallow).not.toBe(deep);
  });

  it("produces a different key for a different focusNode (neighborhood expansion)", () => {
    const unfocused = buildGraphCacheKey(identity(), SLICE);
    const focused = buildGraphCacheKey(identity(), { ...SLICE, focusNode: "mp:v1:agent_run:a1" });
    expect(unfocused).not.toBe(focused);
  });

  it("sorts allowedLayers so key order does not matter", () => {
    const a = buildGraphCacheKey(identity(), { ...SLICE, allowedLayers: ["prompt", "verification"] });
    const b = buildGraphCacheKey(identity(), { ...SLICE, allowedLayers: ["verification", "prompt"] });
    expect(a).toBe(b);
  });

  it("includes the memory checkpoint only when explicitly given", () => {
    const withoutMemory = buildGraphCacheKey(identity(), SLICE, null);
    const withMemory = buildGraphCacheKey(identity(), SLICE, "memory-rev-1");
    expect(withoutMemory).not.toBe(withMemory);
  });
});

describe("sliceFromBounds", () => {
  it("carries every bound field plus the given cursor", () => {
    const slice = sliceFromBounds(
      { maxDepth: 2, maxNodes: 50, maxEdges: 100, allowedLayers: ["prompt"], focusNode: "mp:v1:agent_run:a1" },
      "cursor-abc",
    );
    expect(slice).toEqual({
      maxDepth: 2, maxNodes: 50, maxEdges: 100, allowedLayers: ["prompt"], focusNode: "mp:v1:agent_run:a1", cursor: "cursor-abc",
    });
  });
});

describe("GraphCache", () => {
  it("returns undefined for a key never set", () => {
    const cache = new GraphCache<string>();
    expect(cache.get("nope")).toBeUndefined();
  });

  it("returns exactly what was set for a given key", () => {
    const cache = new GraphCache<string>();
    cache.set("a", "value-a");
    expect(cache.get("a")).toBe("value-a");
  });

  it("never bleeds one project's entry into a lookup for another project's key", () => {
    const cache = new GraphCache<string>();
    const projectAKey = buildGraphCacheKey(identity({ project: "mp:v1:project:a" }), SLICE);
    const projectBKey = buildGraphCacheKey(identity({ project: "mp:v1:project:b" }), SLICE);
    cache.set(projectAKey, "project-a-document");
    expect(cache.get(projectBKey)).toBeUndefined();
    expect(cache.get(projectAKey)).toBe("project-a-document");
  });

  it("evicts the least recently used entry once maxEntries is exceeded", () => {
    const cache = new GraphCache<string>(2);
    cache.set("a", "1");
    cache.set("b", "2");
    cache.set("c", "3"); // evicts "a" (least recently used)
    expect(cache.get("a")).toBeUndefined();
    expect(cache.get("b")).toBe("2");
    expect(cache.get("c")).toBe("3");
  });

  it("counts a get() as recent use, protecting it from the next eviction", () => {
    const cache = new GraphCache<string>(2);
    cache.set("a", "1");
    cache.set("b", "2");
    cache.get("a"); // "a" is now more recently used than "b"
    cache.set("c", "3"); // evicts "b", not "a"
    expect(cache.get("a")).toBe("1");
    expect(cache.get("b")).toBeUndefined();
  });

  it("clear() removes every entry", () => {
    const cache = new GraphCache<string>();
    cache.set("a", "1");
    cache.clear();
    expect(cache.get("a")).toBeUndefined();
    expect(cache.size).toBe(0);
  });
});
