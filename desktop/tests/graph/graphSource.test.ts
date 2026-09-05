import { describe, expect, it } from "vitest";
import { fetchPromptRunGraph, parsePromptRunGraphDocument } from "../../src/graph/graphSource";
import { PerformanceHostError, PerformanceInvalidResponseError, DESKTOP_HOST_URL } from "../../src/activity/performanceSource";
import type { PerformanceFetch } from "../../src/activity/performanceSource";

const ROOT = "mp:v1:prompt_run:aaaaaaaa-0000-5000-8000-000000000001";
const VERSION_NODE = "mp:v1:prompt_version:aaaaaaaa-0000-5000-8000-000000000002";

function baseDocument(overrides: Record<string, unknown> = {}) {
  return {
    version: 1,
    project: "mp:v1:project:aaaaaaaa-0000-5000-8000-000000000000",
    root: ROOT,
    nodes: [
      {
        id: ROOT, kind: "prompt_run", layer: "prompt", priority_tier: "primary", label: "Prompt Run", claim_kind: "derived",
        provenance: [], observed_at: "2026-01-01T00:00:00Z", project_context: "mp:v1:project:aaaaaaaa-0000-5000-8000-000000000000",
        externally_referenced: false, gaps: [], source_claim_kind: "observed", source_layer: "normalized",
      },
    ],
    edges: [],
    citations: [],
    memoryLineage: [],
    gaps: ["unavailable:prompt_version"],
    truncated: false,
    truncationReasons: [],
    cursor: null,
    nextCursor: null,
    bounds: { maxDepth: null, maxNodes: 200, maxEdges: 400, allowedLayers: null, focusNode: null },
    projectionIdentity: {
      project: "mp:v1:project:aaaaaaaa-0000-5000-8000-000000000000", root: ROOT, graphSchemaVersion: 1,
      graphAlgorithmMethod: "relationship-graph", graphAlgorithmVersion: "1", evidenceCheckpoint: "checkpoint-1",
    },
    integrity: { qualifies: true, findings: [] },
    ...overrides,
  };
}

function successEnvelope(result: unknown) {
  return { contractVersion: 1, operation: "graph.getPromptRun", ok: true, result };
}

function errorEnvelope(code: string, message = "Desktop Host error") {
  return { contractVersion: 1, operation: "graph.getPromptRun", ok: false, error: { code, message } };
}

function respond(body: unknown): PerformanceFetch {
  return (url, init) => {
    expect(url).toBe(DESKTOP_HOST_URL);
    expect(init?.method).toBe("POST");
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  };
}

describe("parsePromptRunGraphDocument", () => {
  it("accepts a well-formed document", () => {
    const document = parsePromptRunGraphDocument(baseDocument());
    expect(document.root).toBe(ROOT);
    expect(document.nodes).toHaveLength(1);
    expect(document.nodes[0].id).toBe(ROOT);
  });

  it("parses nodes, edges, and citations with their snake_case fields intact", () => {
    const document = parsePromptRunGraphDocument(
      baseDocument({
        nodes: [
          ...baseDocument().nodes,
          {
            id: VERSION_NODE, kind: "prompt_version", layer: "prompt", priority_tier: "primary", label: "Prompt Version", claim_kind: "derived",
            provenance: [], observed_at: null, project_context: null, externally_referenced: false, gaps: [],
            source_claim_kind: null, source_layer: null,
          },
        ],
        edges: [
          {
            source: ROOT, target: VERSION_NODE, kind: "reference", claim_kind: "derived", evidence: ["pv-1"],
            confidence: null, method: "relationship-graph", method_version: "1", uncertainty: "direct reification",
            semantic_role: "prompt_version",
          },
        ],
        gaps: [],
      }),
    );
    expect(document.edges).toHaveLength(1);
    expect(document.edges[0].semantic_role).toBe("prompt_version");
    expect(document.edges[0].evidence).toEqual(["pv-1"]);
  });

  it("throws PerformanceInvalidResponseError on a missing root", () => {
    const malformed = baseDocument();
    delete (malformed as Record<string, unknown>).root;
    expect(() => parsePromptRunGraphDocument(malformed)).toThrow(PerformanceInvalidResponseError);
  });

  it("throws on a malformed node rather than silently dropping it (edges reference nodes by identity)", () => {
    const malformed = baseDocument({ nodes: [{ kind: "prompt_run" }] });
    expect(() => parsePromptRunGraphDocument(malformed)).toThrow(PerformanceInvalidResponseError);
  });

  it("rejects an unsupported contract version", () => {
    expect(() => parsePromptRunGraphDocument(baseDocument({ version: 2 }))).toThrow(PerformanceInvalidResponseError);
  });
});

describe("fetchPromptRunGraph", () => {
  it("sends promptRunId and optional bounds in the request body", async () => {
    let capturedBody: unknown;
    const fetchImpl: PerformanceFetch = (_url, init) => {
      capturedBody = JSON.parse(String(init?.body));
      return Promise.resolve(new Response(JSON.stringify(successEnvelope(baseDocument())), { status: 200 }));
    };
    await fetchPromptRunGraph(ROOT, { maxNodes: 5, allowedLayers: ["prompt"] }, fetchImpl);
    expect(capturedBody).toEqual({
      contractVersion: 1,
      operation: "graph.getPromptRun",
      request: { promptRunId: ROOT, maxNodes: 5, allowedLayers: ["prompt"] },
    });
  });

  it("resolves the parsed document on a successful envelope", async () => {
    const document = await fetchPromptRunGraph(ROOT, {}, respond(successEnvelope(baseDocument())));
    expect(document.root).toBe(ROOT);
  });

  it("maps a NOT_FOUND host error to a PerformanceHostError carrying that code", async () => {
    const failure = await fetchPromptRunGraph(ROOT, {}, respond(errorEnvelope("NOT_FOUND", "no such Prompt Run"))).catch((e) => e);
    expect(failure).toBeInstanceOf(PerformanceHostError);
    expect((failure as PerformanceHostError).code).toBe("NOT_FOUND");
  });

  it("maps an INVALID_CURSOR host error to a PerformanceHostError carrying that code", async () => {
    const failure = await fetchPromptRunGraph(ROOT, { cursor: "bad" }, respond(errorEnvelope("INVALID_CURSOR"))).catch((e) => e);
    expect(failure).toBeInstanceOf(PerformanceHostError);
    expect((failure as PerformanceHostError).code).toBe("INVALID_CURSOR");
  });
});
