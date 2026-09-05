import { describe, expect, it } from "vitest";
import { citationsForNode, hasUnresolvedCitation } from "../../src/graph/citations";
import type { EvidenceCitation, GraphEdge, GraphNode, PromptRunGraphDocument } from "../../src/graph/types";

const ROOT = "mp:v1:prompt_run:root";
const VERIFICATION_NODE = "mp:v1:verification_run:ver-1";
const FEEDBACK_NODE = "mp:v1:feedback_record:fb-1";

function node(id: string, kind: string): GraphNode {
  return {
    id, kind, layer: "verification", priority_tier: "primary", label: kind, claim_kind: "derived", provenance: [], observed_at: null,
    project_context: null, externally_referenced: false, gaps: [], source_claim_kind: null, source_layer: null,
  };
}

function edge(target: string, evidence: readonly string[], semantic_role: string | null): GraphEdge {
  return {
    source: ROOT, target, kind: "reference", claim_kind: "derived", evidence, confidence: null,
    method: "relationship-graph", method_version: "1", uncertainty: "direct reification", semantic_role,
  };
}

function citation(reference_id: string, evidence_kind: string, summary: string): EvidenceCitation {
  return { reference_id, evidence_kind, project: "mp:v1:project:p", observed_at: null, source: null, detail_available: true, summary };
}

function document(overrides: Partial<PromptRunGraphDocument>): PromptRunGraphDocument {
  return {
    version: 1, project: "mp:v1:project:p", root: ROOT, nodes: [], edges: [], citations: [], memoryLineage: [], gaps: [],
    truncated: false, truncationReasons: [], cursor: null, nextCursor: null,
    bounds: { maxDepth: null, maxNodes: 200, maxEdges: 400, allowedLayers: null, focusNode: null },
    projectionIdentity: { project: "mp:v1:project:p", root: ROOT, graphSchemaVersion: 1, graphAlgorithmMethod: "relationship-graph", graphAlgorithmVersion: "1", evidenceCheckpoint: "checkpoint-1" },
    integrity: { qualifies: true, findings: [] },
    ...overrides,
  };
}

describe("citationsForNode", () => {
  it("joins a verification citation to its node via the verified_by edge's evidence", () => {
    const doc = document({
      nodes: [node(VERIFICATION_NODE, "verification_run")],
      edges: [edge(VERIFICATION_NODE, ["ver-1"], "verified_by")],
      citations: [citation("ver-1", "verification_run", "status=passed")],
    });
    const citations = citationsForNode(doc, VERIFICATION_NODE);
    expect(citations).toHaveLength(1);
    expect(citations[0].summary).toBe("status=passed");
  });

  it("joins a feedback citation to its node via the feedback_for edge's evidence", () => {
    const doc = document({
      nodes: [node(FEEDBACK_NODE, "feedback_record")],
      edges: [edge(FEEDBACK_NODE, ["fb-1"], "feedback_for")],
      citations: [citation("fb-1", "feedback_record", "judgment=achieved")],
    });
    expect(citationsForNode(doc, FEEDBACK_NODE)).toHaveLength(1);
  });

  it("never cross-links a citation to a node of a different evidence kind sharing the same raw id", () => {
    // Deliberately reuses "shared-id" as both a verification and a feedback
    // reference id — a naive id-only join (ignoring semantic_role/evidence_kind)
    // would incorrectly attach both citations to both nodes.
    const feedbackNode = node(FEEDBACK_NODE, "feedback_record");
    const doc = document({
      nodes: [node(VERIFICATION_NODE, "verification_run"), feedbackNode],
      edges: [edge(VERIFICATION_NODE, ["shared-id"], "verified_by"), edge(FEEDBACK_NODE, ["shared-id"], "feedback_for")],
      citations: [citation("shared-id", "verification_run", "verification summary"), citation("shared-id", "feedback_record", "feedback summary")],
    });
    const verificationCitations = citationsForNode(doc, VERIFICATION_NODE);
    const feedbackCitations = citationsForNode(doc, FEEDBACK_NODE);
    expect(verificationCitations).toHaveLength(1);
    expect(verificationCitations[0].summary).toBe("verification summary");
    expect(feedbackCitations).toHaveLength(1);
    expect(feedbackCitations[0].summary).toBe("feedback summary");
  });

  it("returns nothing for a node with no citation-bearing edges (e.g. the root)", () => {
    const doc = document({ nodes: [node(ROOT, "prompt_run")] });
    expect(citationsForNode(doc, ROOT)).toEqual([]);
  });

  it("ignores edges whose semantic_role carries no citations (e.g. prompt_version)", () => {
    const versionNode = node("mp:v1:prompt_version:pv-1", "prompt_version");
    const doc = document({
      nodes: [versionNode],
      edges: [edge(versionNode.id, ["pv-1"], "prompt_version")],
    });
    expect(citationsForNode(doc, versionNode.id)).toEqual([]);
  });
});

describe("hasUnresolvedCitation", () => {
  it("is true when the referenced evidence id has an explicit unavailable:citation gap", () => {
    const doc = document({
      nodes: [node(VERIFICATION_NODE, "verification_run")],
      edges: [edge(VERIFICATION_NODE, ["ver-1"], "verified_by")],
      gaps: ["unavailable:citation:ver-1"],
    });
    expect(hasUnresolvedCitation(doc, VERIFICATION_NODE)).toBe(true);
  });

  it("is false when the citation resolved cleanly", () => {
    const doc = document({
      nodes: [node(VERIFICATION_NODE, "verification_run")],
      edges: [edge(VERIFICATION_NODE, ["ver-1"], "verified_by")],
      citations: [citation("ver-1", "verification_run", "status=passed")],
    });
    expect(hasUnresolvedCitation(doc, VERIFICATION_NODE)).toBe(false);
  });
});
