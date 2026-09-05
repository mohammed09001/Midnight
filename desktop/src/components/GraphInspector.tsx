import type { EvidenceCitation, GraphNode, MemoryLineageEntry } from "../graph/types";
import type { NodeRelationship } from "../graph/relationships";

interface GraphInspectorProps {
  node: GraphNode;
  citations: readonly EvidenceCitation[];
  hasUnresolvedCitation: boolean;
  onClose: () => void;
  /** Execution 09: the pinned (or, once refreshed, last-refreshed) lineage
   * state for this node. `null`/`undefined` for every non-`memory_record`
   * node and for a `memory_record` node with no recognizable pinned
   * citation — the section below is omitted entirely in that case, never
   * rendered empty. */
  memoryLineage?: MemoryLineageEntry | null;
  /** Present only for a node this panel CAN refresh (a `memory_record` node
   * with a parsed `memoryLineage`) — omitted rather than passed as a no-op
   * so the button itself only ever appears where a refresh is meaningful. */
  onRefreshMemoryCitation?: () => void;
  refreshingMemoryCitation?: boolean;
  memoryCitationRefreshError?: string | null;
  /** Execution 10, Section F: every inbound edge into this node — answers
   * "why is this node here" / "why are these two connected" / "how certain"
   * directly, without the reader having to interpret the canvas. */
  relationships?: readonly NodeRelationship[];
  /** Execution 10, Section A: present only when the caller can actually
   * re-fetch with `focusNode` AND the current view is truncated — omitted
   * otherwise, so the button never appears when there is nothing more to
   * reveal. */
  onExpandNeighborhood?: () => void;
}

/**
 * Full click-through detail for one selected node (Section E's second
 * progressive-disclosure step): identity, claim strength, provenance, and
 * every safe evidence citation the node's inbound edges resolve to —
 * `EvidenceCitation.summary` only, never raw evidence content (that
 * boundary is enforced server-side in `evidence_citation.py`; this panel
 * just renders what it's given).
 */
export function GraphInspector({
  node,
  citations,
  hasUnresolvedCitation,
  onClose,
  memoryLineage,
  onRefreshMemoryCitation,
  refreshingMemoryCitation,
  memoryCitationRefreshError,
  relationships,
  onExpandNeighborhood,
}: GraphInspectorProps) {
  return (
    <div
      className="graph-inspector"
      role="dialog"
      aria-label={`${node.label} details`}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div className="graph-inspector__header">
        <h2 className="graph-inspector__title">{node.label}</h2>
        <button type="button" className="graph-inspector__close" onClick={onClose} aria-label="Close details">
          ×
        </button>
      </div>
      <dl className="graph-inspector__facts">
        <dt>Kind</dt>
        <dd>{node.kind}</dd>
        <dt>Layer</dt>
        <dd>{node.layer}</dd>
        <dt>Claim</dt>
        <dd>{node.claim_kind}</dd>
        {node.source_claim_kind && (
          <>
            <dt>Source claim</dt>
            <dd>{node.source_claim_kind}</dd>
          </>
        )}
        {node.observed_at && (
          <>
            <dt>Observed</dt>
            <dd>{node.observed_at}</dd>
          </>
        )}
      </dl>

      {node.gaps.length > 0 && (
        <div className="graph-inspector__section">
          <h3>Explicit gaps</h3>
          <ul className="graph-inspector__gaps">
            {node.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}

      {relationships && (
        <div className="graph-inspector__section">
          <h3>Relationships</h3>
          {relationships.length === 0 ? (
            <p className="graph-inspector__empty">No known inbound relationship for this node.</p>
          ) : (
            <ul className="graph-inspector__relationships">
              {relationships.map((relationship) => (
                <li key={`${relationship.sourceId}-${relationship.semanticRole ?? "reference"}`} className="graph-inspector__relationship">
                  <span>
                    connected from <strong>{relationship.sourceLabel}</strong>
                    {relationship.semanticRole ? ` via ${relationship.semanticRole}` : ""}
                  </span>
                  <span className="graph-inspector__relationship-detail">
                    claim: {relationship.claimKind}; certainty: {relationship.uncertainty}
                    {relationship.confidence !== null ? `; confidence ${relationship.confidence}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {onExpandNeighborhood && (
            <button type="button" className="graph-inspector__expand" onClick={onExpandNeighborhood}>
              Expand neighborhood around this node
            </button>
          )}
        </div>
      )}

      <div className="graph-inspector__section">
        <h3>Evidence</h3>
        {citations.length === 0 && !hasUnresolvedCitation && <p className="graph-inspector__empty">No evidence citations for this node.</p>}
        {hasUnresolvedCitation && <p className="panel__status" role="status">Evidence referenced, but not available in this response.</p>}
        {citations.length > 0 && (
          <ul className="graph-inspector__citations">
            {citations.map((citation) => (
              <li key={citation.reference_id} className="graph-inspector__citation">
                <span className="graph-inspector__citation-kind">{citation.evidence_kind}</span>
                {citation.summary && <span className="graph-inspector__citation-summary">{citation.summary}</span>}
                {citation.detail_available && (
                  <span className="graph-inspector__citation-note">more detail available (not shown here)</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {memoryLineage && (
        <div className="graph-inspector__section">
          <h3>Memory lineage</h3>
          <dl className="graph-inspector__facts">
            <dt>Pinned revision</dt>
            <dd>{memoryLineage.pinnedRevision}</dd>
            <dt>Current status</dt>
            <dd>
              {memoryLineage.currentStatusKnown
                ? `${memoryLineage.currentStatus} (rev ${memoryLineage.currentRevision})`
                : "unknown — not yet refreshed"}
            </dd>
            {memoryLineage.currentStatusKnown && (
              <>
                <dt>Newer revision available</dt>
                <dd>{memoryLineage.newerRevisionAvailable ? "yes" : "no"}</dd>
                <dt>Superseded</dt>
                <dd>
                  {memoryLineage.superseded === null
                    ? "unknown"
                    : memoryLineage.superseded
                      ? `yes, by ${memoryLineage.supersededByRecordId ?? "unknown record"}`
                      : "no"}
                </dd>
                {memoryLineage.contradictionGroupId && (
                  <>
                    <dt>Contradiction</dt>
                    <dd>
                      {memoryLineage.contradictionStatus ?? "unknown"} (group {memoryLineage.contradictionGroupId}
                      {memoryLineage.contradictionGroupSize ? `, ${memoryLineage.contradictionGroupSize} records` : ""})
                    </dd>
                  </>
                )}
              </>
            )}
            {memoryLineage.refreshedAt && (
              <>
                <dt>Last refreshed</dt>
                <dd>{memoryLineage.refreshedAt}</dd>
              </>
            )}
          </dl>
          {memoryLineage.gaps.length > 0 && (
            <ul className="graph-inspector__gaps">
              {memoryLineage.gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          )}
          {onRefreshMemoryCitation && (
            <button
              type="button"
              className="graph-inspector__refresh"
              onClick={onRefreshMemoryCitation}
              disabled={refreshingMemoryCitation === true}
            >
              {refreshingMemoryCitation ? "Refreshing…" : "Refresh current state"}
            </button>
          )}
          {memoryCitationRefreshError && (
            <p className="panel__status" role="alert">
              {memoryCitationRefreshError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
