import type { EvidenceCitation, GraphEdge, PromptRunGraphDocument } from "./types";

/**
 * The node/edge ↔ citation join. Citations are a SIBLING list on the
 * document (Section C/E), never embedded on a node or edge directly — the
 * schema doesn't change for this (confirmed against
 * `graph-prompt-run-response.schema.json`), so the join is done here,
 * client-side, from data the document already carries:
 *
 * `evidence_citation.py`'s builders set `reference_id` to the same RAW
 * stable key `build_graph`'s `_reference()` puts into the connecting edge's
 * `evidence` tuple (e.g. `verification_citation(...)`'s `reference_id` is
 * `VerificationEvidence.identity`, exactly what `_reference(..., evidence=
 * verification_id, ...)` records) — so a citation belongs to node `N` when
 * some edge targeting `N` carries that citation's `reference_id` in its
 * `evidence` array, scoped by the edge's `semantic_role` (never inferred
 * from the target's entity `kind`, matching Section C's requirement that
 * the frontend stays opaque to node/edge kind for this purpose).
 *
 * This bridge's `_build_citations` only ever produces citations for three
 * domains today (verification/feedback/outcome) — the map below is
 * exhaustive against that, not an arbitrary subset.
 */
const SEMANTIC_ROLE_TO_EVIDENCE_KIND: Readonly<Record<string, string>> = {
  verified_by: "verification_run",
  feedback_for: "feedback_record",
  outcome_reference: "outcome_reference",
};

function citationKey(evidenceKind: string, referenceId: string): string {
  return `${evidenceKind}:${referenceId}`;
}

/** Every citation attached to `nodeId` via an inbound edge, in edge order. */
export function citationsForNode(document: PromptRunGraphDocument, nodeId: string): readonly EvidenceCitation[] {
  const byKey = new Map<string, EvidenceCitation>();
  for (const citation of document.citations) {
    byKey.set(citationKey(citation.evidence_kind, citation.reference_id), citation);
  }

  const result: EvidenceCitation[] = [];
  for (const edge of edgesTargeting(document.edges, nodeId)) {
    const evidenceKind = edge.semantic_role ? SEMANTIC_ROLE_TO_EVIDENCE_KIND[edge.semantic_role] : undefined;
    if (!evidenceKind) continue;
    for (const referenceId of edge.evidence) {
      const citation = byKey.get(citationKey(evidenceKind, referenceId));
      if (citation) result.push(citation);
    }
  }
  return result;
}

function edgesTargeting(edges: readonly GraphEdge[], nodeId: string): readonly GraphEdge[] {
  return edges.filter((edge) => edge.target === nodeId);
}

/** True when at least one citation this node's evidence edges reference
 * could not be resolved (an honest `unavailable:citation:<id>` gap on the
 * document) — lets the inspector show "evidence referenced but unavailable"
 * distinctly from "no evidence exists here at all." */
export function hasUnresolvedCitation(document: PromptRunGraphDocument, nodeId: string): boolean {
  for (const edge of edgesTargeting(document.edges, nodeId)) {
    if (!edge.semantic_role || !(edge.semantic_role in SEMANTIC_ROLE_TO_EVIDENCE_KIND)) continue;
    for (const referenceId of edge.evidence) {
      if (document.gaps.includes(`unavailable:citation:${referenceId}`)) return true;
    }
  }
  return false;
}
