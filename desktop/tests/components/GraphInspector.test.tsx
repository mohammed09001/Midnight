import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GraphInspector } from "../../src/components/GraphInspector";
import type { EvidenceCitation, GraphNode, MemoryLineageEntry } from "../../src/graph/types";

function node(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "mp:v1:verification_run:ver-1", kind: "verification_run", layer: "verification", priority_tier: "primary", label: "Verification Run",
    claim_kind: "derived", provenance: [], observed_at: null, project_context: null, externally_referenced: false,
    gaps: [], source_claim_kind: null, source_layer: null,
    ...overrides,
  };
}

function citation(overrides: Partial<EvidenceCitation> = {}): EvidenceCitation {
  return {
    reference_id: "ver-1", evidence_kind: "verification_run", project: "mp:v1:project:p", observed_at: null,
    source: null, detail_available: false, summary: "status=passed",
    ...overrides,
  };
}

function lineage(overrides: Partial<MemoryLineageEntry> = {}): MemoryLineageEntry {
  return {
    nodeId: "mp:v1:memory_record:aaa", provider: "memory", recordId: "rec-1", pinnedRevision: 1,
    currentStatusKnown: false, currentRevision: null, currentStatus: null, superseded: null,
    supersededByRecordId: null, contradictionGroupId: null, contradictionStatus: null,
    contradictionGroupSize: null, newerRevisionAvailable: null, refreshedAt: null, gaps: [],
    ...overrides,
  };
}

describe("GraphInspector", () => {
  it("renders identity facts and evidence citations, never raw content", () => {
    render(
      <GraphInspector node={node()} citations={[citation()]} hasUnresolvedCitation={false} onClose={() => {}} />,
    );
    expect(screen.getByRole("heading", { name: "Verification Run" })).toBeInTheDocument();
    // "verification_run" legitimately appears twice: once as the node's own
    // Kind fact, once as the citation's evidence_kind label.
    expect(screen.getAllByText("verification_run")).toHaveLength(2);
    expect(screen.getByText("status=passed")).toBeInTheDocument();
  });

  it("shows explicit gaps when present", () => {
    render(
      <GraphInspector
        node={node({ gaps: ["unavailable:prompt_version"] })}
        citations={[]}
        hasUnresolvedCitation={false}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("unavailable:prompt_version")).toBeInTheDocument();
  });

  it("shows an honest 'referenced but unavailable' message rather than fabricating a citation", () => {
    render(<GraphInspector node={node()} citations={[]} hasUnresolvedCitation={true} onClose={() => {}} />);
    expect(screen.getByText("Evidence referenced, but not available in this response.")).toBeInTheDocument();
  });

  it("shows a plain empty state when there is genuinely no evidence", () => {
    render(<GraphInspector node={node()} citations={[]} hasUnresolvedCitation={false} onClose={() => {}} />);
    expect(screen.getByText("No evidence citations for this node.")).toBeInTheDocument();
  });

  it("calls onClose from the close button", async () => {
    const onClose = vi.fn();
    render(<GraphInspector node={node()} citations={[]} hasUnresolvedCitation={false} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText("Close details"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose on Escape while focus is inside the dialog", async () => {
    const onClose = vi.fn();
    render(<GraphInspector node={node()} citations={[]} hasUnresolvedCitation={false} onClose={onClose} />);
    // Clicking the close button both focuses it (inside the dialog) and
    // fires onClose once via click — press Escape from that same focus to
    // exercise the dialog's own keydown handler, then assert the total.
    await userEvent.click(screen.getByLabelText("Close details"));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("omits the Memory lineage section entirely for a non-Memory node", () => {
    render(<GraphInspector node={node()} citations={[]} hasUnresolvedCitation={false} onClose={() => {}} />);
    expect(screen.queryByText("Memory lineage")).toBeNull();
  });

  it("shows the pinned revision and an honest 'unknown' current status before any refresh", () => {
    render(
      <GraphInspector
        node={node({ kind: "memory_record" })}
        citations={[]}
        hasUnresolvedCitation={false}
        onClose={() => {}}
        memoryLineage={lineage()}
      />,
    );
    expect(screen.getByText("Memory lineage")).toBeInTheDocument();
    expect(screen.getByText("unknown — not yet refreshed")).toBeInTheDocument();
    // Section-only fields (newer revision / superseded / contradiction) are
    // never shown before currentStatusKnown -- nothing to honestly report yet.
    expect(screen.queryByText("Newer revision available")).toBeNull();
  });

  it("shows superseded and contradiction detail once refreshed", () => {
    render(
      <GraphInspector
        node={node({ kind: "memory_record" })}
        citations={[]}
        hasUnresolvedCitation={false}
        onClose={() => {}}
        memoryLineage={lineage({
          currentStatusKnown: true, currentStatus: "superseded", currentRevision: 2,
          superseded: true, supersededByRecordId: "rec-2", newerRevisionAvailable: true,
          contradictionGroupId: "grp-1", contradictionStatus: "resolved", contradictionGroupSize: 2,
        })}
      />,
    );
    expect(screen.getByText("yes, by rec-2")).toBeInTheDocument();
    expect(screen.getByText("resolved (group grp-1, 2 records)")).toBeInTheDocument();
  });

  it("shows the refresh button only when a refresh handler is supplied, and disables it mid-refresh", async () => {
    const onRefresh = vi.fn();
    render(
      <GraphInspector
        node={node({ kind: "memory_record" })}
        citations={[]}
        hasUnresolvedCitation={false}
        onClose={() => {}}
        memoryLineage={lineage()}
        onRefreshMemoryCitation={onRefresh}
        refreshingMemoryCitation={true}
      />,
    );
    const button = screen.getByRole("button", { name: "Refreshing…" });
    expect(button).toBeDisabled();
  });

  it("invokes the refresh handler on click", async () => {
    const onRefresh = vi.fn();
    render(
      <GraphInspector
        node={node({ kind: "memory_record" })}
        citations={[]}
        hasUnresolvedCitation={false}
        onClose={() => {}}
        memoryLineage={lineage()}
        onRefreshMemoryCitation={onRefresh}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Refresh current state" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
