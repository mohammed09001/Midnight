import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { GraphHoverPanel } from "../../src/components/GraphHoverPanel";
import type { GraphNode, MemoryLineageEntry } from "../../src/graph/types";

function lineage(overrides: Partial<MemoryLineageEntry> = {}): MemoryLineageEntry {
  return {
    nodeId: "mp:v1:memory_record:aaa", provider: "memory", recordId: "rec-1", pinnedRevision: 1,
    currentStatusKnown: false, currentRevision: null, currentStatus: null, superseded: null,
    supersededByRecordId: null, contradictionGroupId: null, contradictionStatus: null,
    contradictionGroupSize: null, newerRevisionAvailable: null, refreshedAt: null, gaps: [],
    ...overrides,
  };
}

function node(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "mp:v1:prompt_run:aaa", kind: "prompt_run", layer: "prompt", priority_tier: "primary", label: "Prompt Run", claim_kind: "derived",
    provenance: [], observed_at: null, project_context: null, externally_referenced: false, gaps: [],
    source_claim_kind: null, source_layer: null,
    ...overrides,
  };
}

describe("GraphHoverPanel", () => {
  it("shows the node's label and kind", () => {
    render(<GraphHoverPanel node={node({ label: "Verification Run", kind: "verification_run" })} />);
    expect(screen.getByText("Verification Run")).toBeInTheDocument();
    expect(screen.getByText("verification_run")).toBeInTheDocument();
  });

  it("shows a gap count when the node has explicit gaps", () => {
    render(<GraphHoverPanel node={node({ gaps: ["unavailable:prompt_version"] })} />);
    expect(screen.getByText("1 gap")).toBeInTheDocument();
  });

  it("shows nothing gap-related when there are no gaps", () => {
    render(<GraphHoverPanel node={node({ gaps: [] })} />);
    expect(screen.queryByText(/gap/)).toBeNull();
  });

  it("shows the pinned revision and an honest 'unknown' current status before any refresh", () => {
    render(<GraphHoverPanel node={node({ kind: "memory_record" })} memoryLineage={lineage()} />);
    expect(screen.getByText("pinned rev 1, current: unknown")).toBeInTheDocument();
  });

  it("shows the refreshed current status once known", () => {
    render(
      <GraphHoverPanel
        node={node({ kind: "memory_record" })}
        memoryLineage={lineage({ currentStatusKnown: true, currentStatus: "active", currentRevision: 1 })}
      />,
    );
    expect(screen.getByText("pinned rev 1, current: active")).toBeInTheDocument();
  });

  it("shows nothing lineage-related for a non-Memory node", () => {
    render(<GraphHoverPanel node={node()} memoryLineage={null} />);
    expect(screen.queryByText(/pinned rev/)).toBeNull();
  });
});
