import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  Background,
  Controls as FlowControls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphNode, MemoryLineageEntry, PromptRunGraphDocument } from "../graph/types";
import { layoutGraph, type GraphLayout } from "../graph/layout";
import { buildGraphCacheKey, GraphCache, sliceFromBounds } from "../graph/graphCache";
import { citationsForNode, hasUnresolvedCitation } from "../graph/citations";
import { fetchRefreshMemoryCitation } from "../graph/graphSource";
import { memoryLineageForNode } from "../graph/memoryLineage";
import { relationshipsForNode } from "../graph/relationships";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { GraphControls } from "./GraphControls";
import { GraphHoverPanel } from "./GraphHoverPanel";
import { GraphInspector } from "./GraphInspector";

interface PerformanceGraphProps {
  document: PromptRunGraphDocument;
  /** Execution 10, Section A (neighborhood expansion): present only when the
   * caller (`App.tsx`) can actually re-fetch with a `focusNode` — omitted in
   * contexts (e.g. the dev `?fixtureUrl=` preview) where there is no live
   * Host to ask. Called with the node's id the user wants expanded. */
  onExpandNode?: (nodeId: string) => void;
}

interface FlowNodeData extends Record<string, unknown> {
  graphNode: GraphNode;
  isRoot: boolean;
  isSelected: boolean;
  onHover: (node: GraphNode | null) => void;
  onSelect: (node: GraphNode) => void;
}

/**
 * One graph node. Owns its own hover/focus/click wiring directly (mirroring
 * `ActivityCell.tsx`'s established `onMouseEnter`/`onFocus` →
 * `onMouseLeave`/`onBlur` hover-equals-focus idiom) rather than relying on
 * React Flow's own `onNodeMouseEnter`/`onNodeClick` props, which have no
 * keyboard-focus equivalent — every interaction here is keyboard-reachable
 * by construction, the same guarantee `ActivityCell` makes.
 */
function PerformanceNode({ data }: NodeProps<Node<FlowNodeData>>) {
  const { graphNode, isRoot, isSelected, onHover, onSelect } = data;
  return (
    <div
      className="performance-node"
      data-layer={graphNode.layer}
      data-root={isRoot || undefined}
      data-selected={isSelected || undefined}
      tabIndex={0}
      role="button"
      aria-label={`${graphNode.label}, ${graphNode.kind}${graphNode.gaps.length ? `, ${graphNode.gaps.length} gap${graphNode.gaps.length === 1 ? "" : "s"}` : ""}`}
      onMouseEnter={() => onHover(graphNode)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(graphNode)}
      onBlur={() => onHover(null)}
      onClick={() => onSelect(graphNode)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(graphNode);
        }
      }}
    >
      <Handle type="target" position={Position.Top} />
      <span className="performance-node__label">{graphNode.label}</span>
      <span className="performance-node__kind">{graphNode.kind}</span>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const NODE_TYPES = { performanceNode: PerformanceNode };

export function PerformanceGraph({ document, onExpandNode }: PerformanceGraphProps) {
  return (
    <ReactFlowProvider>
      <PerformanceGraphInner document={document} onExpandNode={onExpandNode} />
    </ReactFlowProvider>
  );
}

function PerformanceGraphInner({ document, onExpandNode }: PerformanceGraphProps) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const [activeLayers, setActiveLayers] = useState<Set<string> | null>(null);
  // Execution 10, Section E: on-demand-tier nodes (Session/Turn, Tool,
  // Command, Symbols, Analysis, Memory, similarity/history) start hidden —
  // a display policy only; `document` itself is untouched, so revealing
  // them is instant, no re-fetch.
  const [showOnDemand, setShowOnDemand] = useState(false);
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }> | null>(null);
  // Execution 09: refreshed Memory lineage overrides the build-time pinned
  // entry from `document.memoryLineage` per node, and ONLY per node — a
  // refresh never touches any other node's state, and never mutates
  // `document` itself (Section D: "old graph remains unchanged").
  const [refreshedLineage, setRefreshedLineage] = useState<Map<string, MemoryLineageEntry>>(new Map());
  const [refreshingNodeId, setRefreshingNodeId] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const resolveLineage = (nodeId: string): MemoryLineageEntry | null =>
    refreshedLineage.get(nodeId) ?? memoryLineageForNode(document, nodeId);

  async function handleRefreshMemoryCitation(targetNode: GraphNode) {
    const pinned = resolveLineage(targetNode.id);
    if (!pinned) return;
    setRefreshingNodeId(targetNode.id);
    setRefreshError(null);
    try {
      const referenceValue = `${pinned.recordId}#rev${pinned.pinnedRevision}`;
      const result = await fetchRefreshMemoryCitation(referenceValue);
      setRefreshedLineage((previous) => new Map(previous).set(targetNode.id, { nodeId: targetNode.id, ...result.state }));
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : "Failed to refresh Memory citation");
    } finally {
      setRefreshingNodeId(null);
    }
  }

  const allLayers = useMemo(() => {
    const seen = new Set<string>();
    const ordered: string[] = [];
    for (const node of document.nodes) {
      if (!seen.has(node.layer)) {
        seen.add(node.layer);
        ordered.push(node.layer);
      }
    }
    return ordered;
  }, [document]);

  const visibleNodes = useMemo(() => {
    const byLayer = activeLayers === null ? document.nodes : document.nodes.filter((node) => activeLayers.has(node.layer));
    return showOnDemand ? byLayer : byLayer.filter((node) => node.priority_tier === "primary");
  }, [document, activeLayers, showOnDemand]);
  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => document.edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)),
    [document, visibleNodeIds],
  );

  useEffect(() => {
    setSelected(null);
    setHovered(null);
    setRefreshedLineage(new Map());
    setRefreshingNodeId(null);
    setRefreshError(null);
  }, [document]);

  // Execution 10, Section C: layout coordinates are rebuildable, so a
  // previously-computed layout for the EXACT SAME visible node/edge set is
  // reused instead of re-running elk — toggling a layer filter (or the
  // on-demand tier) back and forth is then instant on the second pass.
  // Never persisted beyond this component instance; a fresh graph document
  // (a real evidence change, reflected in a different `evidenceCheckpoint`)
  // naturally produces a different key, never a stale hit.
  const layoutCacheRef = useRef(new GraphCache<GraphLayout>(20));
  const layoutCacheKey =
    buildGraphCacheKey(document.projectionIdentity, sliceFromBounds(document.bounds, document.cursor)) +
    "|" +
    visibleNodes.map((node) => node.id).sort().join(",");

  useEffect(() => {
    let alive = true;
    const cached = layoutCacheRef.current.get(layoutCacheKey);
    if (cached) {
      setPositions(new Map(cached.nodes.map((node) => [node.id, { x: node.x, y: node.y }])));
      return;
    }
    setPositions(null);
    layoutGraph(visibleNodes, visibleEdges).then((layout) => {
      if (!alive) return;
      layoutCacheRef.current.set(layoutCacheKey, layout);
      setPositions(new Map(layout.nodes.map((node) => [node.id, { x: node.x, y: node.y }])));
    });
    return () => {
      alive = false;
    };
  }, [visibleNodes, visibleEdges, layoutCacheKey]);

  useEffect(() => {
    if (!positions) return;
    fitView({ duration: prefersReducedMotion ? 0 : 250, padding: 0.2 });
  }, [positions, fitView, prefersReducedMotion]);

  const flowNodes: Node<FlowNodeData>[] = useMemo(() => {
    if (!positions) return [];
    return visibleNodes.map((node) => ({
      id: node.id,
      type: "performanceNode",
      position: positions.get(node.id) ?? { x: 0, y: 0 },
      data: {
        graphNode: node,
        isRoot: node.id === document.root,
        isSelected: selected?.id === node.id,
        onHover: setHovered,
        onSelect: setSelected,
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    }));
  }, [visibleNodes, positions, document.root, selected]);

  const flowEdges: Edge[] = useMemo(
    () =>
      visibleEdges.map((edge, index) => ({
        id: `${edge.source}->${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        label: edge.semantic_role ?? undefined,
      })),
    [visibleEdges],
  );

  const nodeLabelById = useMemo(() => new Map(visibleNodes.map((node) => [node.id, node.label])), [visibleNodes]);

  const zoomStep = prefersReducedMotion ? 0 : 200;
  const handleCanvasKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    // Section G: keyboard zoom controls, independent of React Flow's own
    // mouse-driven zoom buttons -- a keyboard-only user must never be
    // limited to panning/selecting alone.
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomIn({ duration: zoomStep });
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      zoomOut({ duration: zoomStep });
    } else if (event.key === "0") {
      event.preventDefault();
      fitView({ duration: zoomStep, padding: 0.2 });
    }
  };

  return (
    <div className="performance-graph">
      <GraphControls
        layers={allLayers}
        activeLayers={activeLayers}
        onChange={setActiveLayers}
        onResetView={() => fitView({ duration: prefersReducedMotion ? 0 : 250, padding: 0.2 })}
        showOnDemand={showOnDemand}
        onToggleOnDemand={() => setShowOnDemand((current) => !current)}
      />
      <div
        className="performance-graph__canvas"
        tabIndex={0}
        role="application"
        aria-label="Graph canvas — arrow keys pan, + and - zoom, 0 resets the view"
        onKeyDown={handleCanvasKeyDown}
      >
        {!positions ? (
          <p className="panel__status" role="status">
            Laying out graph…
          </p>
        ) : (
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={NODE_TYPES}
            onPaneClick={() => setSelected(null)}
            fitView
          >
            <Background />
            <FlowControls showInteractive={false} />
          </ReactFlow>
        )}
      </div>
      {/* Section F/G: a screen-reader-only relationship explanation —
          React Flow's edges are SVG paths with no inherent accessible
          text, so "why are these two connected, and how" must exist
          somewhere a screen reader can actually read it. Never hover-only:
          this list is always present once the graph has rendered. */}
      <ul className="visually-hidden" aria-label="Relationships in this graph">
        {visibleEdges.map((edge, index) => (
          <li key={`${edge.source}->${edge.target}-${index}`}>
            {(nodeLabelById.get(edge.source) ?? edge.source)} is connected to {(nodeLabelById.get(edge.target) ?? edge.target)}
            {edge.semantic_role ? ` via ${edge.semantic_role}` : ""}; claim: {edge.claim_kind}; certainty: {edge.uncertainty}
            {edge.confidence !== null ? `; confidence ${edge.confidence}` : ""}.
          </li>
        ))}
      </ul>
      {hovered && !selected && <GraphHoverPanel node={hovered} memoryLineage={resolveLineage(hovered.id)} />}
      {selected && (
        <GraphInspector
          node={selected}
          citations={citationsForNode(document, selected.id)}
          hasUnresolvedCitation={hasUnresolvedCitation(document, selected.id)}
          onClose={() => setSelected(null)}
          memoryLineage={resolveLineage(selected.id)}
          onRefreshMemoryCitation={resolveLineage(selected.id) ? () => handleRefreshMemoryCitation(selected) : undefined}
          refreshingMemoryCitation={refreshingNodeId === selected.id}
          memoryCitationRefreshError={refreshingNodeId === null ? refreshError : null}
          relationships={relationshipsForNode(document, selected.id)}
          onExpandNeighborhood={onExpandNode && document.truncated ? () => onExpandNode(selected.id) : undefined}
        />
      )}
      {document.truncated && (
        <p className="performance-graph__truncated" role="status">
          This graph is truncated — not all evidence for this Prompt Run is shown.
        </p>
      )}
    </div>
  );
}
