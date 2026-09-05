import type { PromptRunGraphDocument } from "./types";

/**
 * Execution 10, Section F: the "why are these two connected, and how
 * certain" answer for one node's INBOUND edges — every fact the Evidence
 * Inspector needs already lives on `GraphEdge`; this just joins it to the
 * connecting node's label so the panel never has to show a bare identity
 * string for "where this came from."
 */
export interface NodeRelationship {
  readonly sourceId: string;
  readonly sourceLabel: string;
  readonly semanticRole: string | null;
  readonly claimKind: string;
  readonly confidence: number | null;
  readonly uncertainty: string;
  readonly evidence: readonly string[];
}

export function relationshipsForNode(document: PromptRunGraphDocument, nodeId: string): readonly NodeRelationship[] {
  const labelById = new Map(document.nodes.map((node) => [node.id, node.label]));
  return document.edges
    .filter((edge) => edge.target === nodeId)
    .map((edge) => ({
      sourceId: edge.source,
      sourceLabel: labelById.get(edge.source) ?? edge.source,
      semanticRole: edge.semantic_role,
      claimKind: edge.claim_kind,
      confidence: edge.confidence,
      uncertainty: edge.uncertainty,
      evidence: edge.evidence,
    }));
}
