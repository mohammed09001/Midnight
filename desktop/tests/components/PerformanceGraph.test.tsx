import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PerformanceGraph } from "../../src/components/PerformanceGraph";
import type { MemoryCitationRefreshDocument, PromptRunGraphDocument } from "../../src/graph/types";

const { fetchRefreshMemoryCitationMock } = vi.hoisted(() => ({ fetchRefreshMemoryCitationMock: vi.fn() }));
vi.mock("../../src/graph/graphSource", () => ({ fetchRefreshMemoryCitation: fetchRefreshMemoryCitationMock }));

const layoutGraphSpy = vi.hoisted(() => ({ calls: 0 }));
vi.mock("../../src/graph/layout", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/graph/layout")>();
  return {
    ...actual,
    layoutGraph: (...args: Parameters<typeof actual.layoutGraph>) => {
      layoutGraphSpy.calls += 1;
      return actual.layoutGraph(...args);
    },
  };
});

const ROOT = "mp:v1:prompt_run:root";
const VERIFICATION_NODE = "mp:v1:verification_run:ver-1";
const MEMORY_NODE = "mp:v1:memory_record:mem-1";

function document(): PromptRunGraphDocument {
  return {
    version: 1,
    project: "mp:v1:project:p",
    root: ROOT,
    nodes: [
      {
        id: ROOT, kind: "prompt_run", layer: "prompt", priority_tier: "primary", label: "Prompt Run", claim_kind: "derived", provenance: [],
        observed_at: "2026-01-01T00:00:00Z", project_context: "mp:v1:project:p", externally_referenced: false,
        gaps: [], source_claim_kind: "observed", source_layer: "normalized",
      },
      {
        id: VERIFICATION_NODE, kind: "verification_run", layer: "verification", priority_tier: "primary", label: "Verification Run",
        claim_kind: "derived", provenance: [], observed_at: null, project_context: null,
        externally_referenced: false, gaps: [], source_claim_kind: null, source_layer: null,
      },
      {
        id: MEMORY_NODE, kind: "memory_record", layer: "memory", priority_tier: "on_demand", label: "memory:rec-1#rev1",
        claim_kind: "derived", provenance: ["memory:record:rec-1#rev1"], observed_at: null, project_context: null,
        externally_referenced: false, gaps: [], source_claim_kind: null, source_layer: null,
      },
    ],
    edges: [
      {
        source: ROOT, target: VERIFICATION_NODE, kind: "reference", claim_kind: "derived", evidence: ["ver-1"],
        confidence: null, method: "relationship-graph", method_version: "1", uncertainty: "direct reification",
        semantic_role: "verified_by",
      },
      {
        source: ROOT, target: MEMORY_NODE, kind: "reference", claim_kind: "derived", evidence: ["memory:record:rec-1#rev1"],
        confidence: null, method: "relationship-graph", method_version: "1", uncertainty: "direct reification",
        semantic_role: "cites_memory",
      },
    ],
    citations: [
      {
        reference_id: "ver-1", evidence_kind: "verification_run", project: "mp:v1:project:p", observed_at: null,
        source: "executed", detail_available: false, summary: "status=passed",
      },
    ],
    memoryLineage: [
      {
        nodeId: MEMORY_NODE, provider: "memory", recordId: "rec-1", pinnedRevision: 1, currentStatusKnown: false,
        currentRevision: null, currentStatus: null, superseded: null, supersededByRecordId: null,
        contradictionGroupId: null, contradictionStatus: null, contradictionGroupSize: null,
        newerRevisionAvailable: null, refreshedAt: null, gaps: [],
      },
    ],
    gaps: [],
    truncated: false,
    truncationReasons: [],
    cursor: null,
    nextCursor: null,
    bounds: { maxDepth: null, maxNodes: 200, maxEdges: 400, allowedLayers: null, focusNode: null },
    projectionIdentity: {
      project: "mp:v1:project:p", root: ROOT, graphSchemaVersion: 1,
      graphAlgorithmMethod: "relationship-graph", graphAlgorithmVersion: "1", evidenceCheckpoint: "checkpoint-1",
    },
    integrity: { qualifies: true, findings: [] },
  };
}

describe("PerformanceGraph", () => {
  afterEach(() => {
    fetchRefreshMemoryCitationMock.mockReset();
    layoutGraphSpy.calls = 0;
  });


  it("renders every node once layout completes", async () => {
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
    expect(screen.getByText("Verification Run")).toBeInTheDocument();
  });

  // Node interactions below use `fireEvent` rather than `userEvent`: React
  // Flow attaches a d3-drag listener to each node's mousedown for real
  // dragging, and d3-drag reads `event.view.document` — a field jsdom's
  // synthetic pointer sequence (as `userEvent` produces it) leaves unset,
  // crashing unrelated to anything this test is actually verifying.
  // `fireEvent` dispatches exactly the one event each interaction needs
  // (`focus`/`blur`/`click`) without that pointer choreography.

  it("shows the hover panel on node focus, and hides it on blur", async () => {
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
    const promptRunNode = screen.getByText("Prompt Run").closest(".performance-node")!;
    fireEvent.focus(promptRunNode);
    expect(await screen.findAllByText("Prompt Run")).toHaveLength(2); // the node itself + the hover panel
    fireEvent.blur(promptRunNode);
    await waitFor(() => expect(screen.getAllByText("Prompt Run")).toHaveLength(1));
  });

  it("opens the inspector with the node's citation on click, and closes on the close button", async () => {
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Verification Run")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Verification Run").closest(".performance-node")!);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("status=passed")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Close details"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the truncated notice only when the document is truncated", async () => {
    const truncatedDocument = { ...document(), truncated: true };
    render(<PerformanceGraph document={truncatedDocument} />);
    await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
    expect(screen.getByText(/This graph is truncated/)).toBeInTheDocument();
  });

  it("hides on_demand-tier nodes (Memory) by default, and reveals them via the toggle", async () => {
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
    expect(screen.queryByText("memory:rec-1#rev1")).toBeNull();
    await userEvent.click(screen.getByLabelText(/Show on-demand evidence/));
    await waitFor(() => expect(screen.getByText("memory:rec-1#rev1")).toBeInTheDocument());
  });

  it("shows inbound relationships and offers to expand the neighborhood when the graph is truncated", async () => {
    const onExpandNode = vi.fn();
    const truncatedDocument = { ...document(), truncated: true };
    render(<PerformanceGraph document={truncatedDocument} onExpandNode={onExpandNode} />);
    await waitFor(() => expect(screen.getByText("Verification Run")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Verification Run").closest(".performance-node")!);
    expect(await screen.findByText("Relationships")).toBeInTheDocument();
    expect(screen.getByText(/connected from/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Expand neighborhood around this node" }));
    expect(onExpandNode).toHaveBeenCalledWith(VERIFICATION_NODE);
  });

  it("omits the expand-neighborhood button when the graph is not truncated", async () => {
    const onExpandNode = vi.fn();
    render(<PerformanceGraph document={document()} onExpandNode={onExpandNode} />);
    await waitFor(() => expect(screen.getByText("Verification Run")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Verification Run").closest(".performance-node")!);
    await screen.findByText("Relationships");
    expect(screen.queryByRole("button", { name: "Expand neighborhood around this node" })).toBeNull();
  });

  it("exposes keyboard zoom controls on the canvas without throwing", async () => {
    // Forces reduced motion so the zoom/fitView calls below use a
    // zero-duration (non-animated) transition -- jsdom has no real paint
    // loop, and an animated d3-zoom transition's requestAnimationFrame
    // chain can otherwise keep firing into later tests.
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: true, media: query, onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    try {
      render(<PerformanceGraph document={document()} />);
      await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
      const canvas = screen.getByRole("application", { name: /Graph canvas/ });
      expect(canvas).toHaveAttribute("tabindex", "0");
      fireEvent.keyDown(canvas, { key: "+" });
      fireEvent.keyDown(canvas, { key: "-" });
      fireEvent.keyDown(canvas, { key: "0" });
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });

  it("lists relationships for screen readers via a visually-hidden summary", async () => {
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
    const list = screen.getByRole("list", { name: "Relationships in this graph" });
    expect(list).toHaveTextContent("Prompt Run is connected to Verification Run via verified_by");
  });

  it("filtering out a layer removes its nodes from the canvas", async () => {
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Verification Run")).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText("verification"));
    await waitFor(() => expect(screen.queryByText("Verification Run")).toBeNull());
    expect(screen.getByText("Prompt Run")).toBeInTheDocument();
  });

  it("reuses a cached layout for a previously-seen exact node/edge set instead of recomputing it (Section C)", async () => {
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Verification Run")).toBeInTheDocument());
    const callsAfterInitialLayout = layoutGraphSpy.calls;
    expect(callsAfterInitialLayout).toBeGreaterThan(0);

    await userEvent.click(screen.getByLabelText("verification"));
    await waitFor(() => expect(screen.queryByText("Verification Run")).toBeNull());
    const callsAfterHiding = layoutGraphSpy.calls;
    expect(callsAfterHiding).toBeGreaterThan(callsAfterInitialLayout); // a genuinely new node set -> real layout call

    await userEvent.click(screen.getByLabelText("verification")); // back to the exact original visible set
    await waitFor(() => expect(screen.getByText("Verification Run")).toBeInTheDocument());
    expect(layoutGraphSpy.calls).toBe(callsAfterHiding); // cache hit -- no additional layout() call
  });

  it("refreshing a Memory citation replaces its pinned-only state with the live result, and only for that node", async () => {
    const refreshResult: MemoryCitationRefreshDocument = {
      version: 1,
      project: "mp:v1:project:p",
      reference: { provider: "memory", kind: "record", value: "rec-1#rev1" },
      state: {
        provider: "memory", recordId: "rec-1", pinnedRevision: 1, currentStatusKnown: true,
        currentRevision: 1, currentStatus: "active", superseded: false, supersededByRecordId: null,
        contradictionGroupId: null, contradictionStatus: null, contradictionGroupSize: null,
        newerRevisionAvailable: false, refreshedAt: "2026-01-02T00:00:00Z", gaps: [],
      },
    };
    fetchRefreshMemoryCitationMock.mockResolvedValueOnce(refreshResult);

    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
    // The Memory node is "on_demand" tier, hidden by default (Section E) —
    // reveal it before interacting with it, exactly as a real user would.
    await userEvent.click(screen.getByLabelText(/Show on-demand evidence/));
    await waitFor(() => expect(screen.getByText("memory:rec-1#rev1")).toBeInTheDocument());
    fireEvent.click(screen.getByText("memory:rec-1#rev1").closest(".performance-node")!);
    expect(await screen.findByText("unknown — not yet refreshed")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Refresh current state" }));

    expect(await screen.findByText("active (rev 1)")).toBeInTheDocument();
    expect(fetchRefreshMemoryCitationMock).toHaveBeenCalledWith("rec-1#rev1");
    // The unrelated Verification Run node's own citation is untouched by
    // this Memory-only refresh.
    fireEvent.click(screen.getByLabelText("Close details"));
    fireEvent.click(screen.getByText("Verification Run").closest(".performance-node")!);
    expect(await screen.findByText("status=passed")).toBeInTheDocument();
  });

  it("shows a refresh error inline without crashing the inspector", async () => {
    fetchRefreshMemoryCitationMock.mockRejectedValueOnce(new Error("Desktop Host unreachable"));
    render(<PerformanceGraph document={document()} />);
    await waitFor(() => expect(screen.getByText("Prompt Run")).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText(/Show on-demand evidence/));
    await waitFor(() => expect(screen.getByText("memory:rec-1#rev1")).toBeInTheDocument());
    fireEvent.click(screen.getByText("memory:rec-1#rev1").closest(".performance-node")!);
    await userEvent.click(screen.getByRole("button", { name: "Refresh current state" }));
    expect(await screen.findByText("Desktop Host unreachable")).toBeInTheDocument();
  });
});
