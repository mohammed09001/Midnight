import type { GraphNode, MemoryLineageEntry } from "../graph/types";

interface GraphHoverPanelProps {
  node: GraphNode;
  /** Execution 09: the pinned (or, once refreshed, the last-refreshed)
   * lineage state for this node — `null` for every non-`memory_record`
   * node, and for a `memory_record` node whose citation didn't parse as a
   * recognizable pinned reference (an honest absence, never fabricated). */
  memoryLineage?: MemoryLineageEntry | null;
}

/**
 * Lightweight preview shown while a node has hover/focus but hasn't been
 * clicked — the first step of progressive disclosure (Section E), before
 * `GraphInspector`'s full citation detail. Unlike `ActivityTooltip.tsx`
 * (a floating tooltip anchored to a dense grid cell's exact pixel position),
 * this renders as a fixed side panel: computing a node's on-screen position
 * would require reading React Flow's live pan/zoom viewport transform, and
 * a docked panel serves the same "glance without committing to a click"
 * purpose without that extra coupling. Information here is also always
 * available via `GraphInspector` on click, so nothing is hover-only.
 */
export function GraphHoverPanel({ node, memoryLineage }: GraphHoverPanelProps) {
  return (
    <div className="graph-hover-panel" role="status" aria-live="polite">
      <span className="graph-hover-panel__label">{node.label}</span>
      <span className="graph-hover-panel__kind">{node.kind}</span>
      {node.gaps.length > 0 && (
        <span className="graph-hover-panel__gap">{node.gaps.length === 1 ? "1 gap" : `${node.gaps.length} gaps`}</span>
      )}
      {memoryLineage && (
        <span className="graph-hover-panel__lineage">
          pinned rev {memoryLineage.pinnedRevision}
          {memoryLineage.currentStatusKnown ? `, current: ${memoryLineage.currentStatus}` : ", current: unknown"}
        </span>
      )}
    </div>
  );
}
