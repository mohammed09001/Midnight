import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InsightCard } from "../../src/components/InsightCard";
import type { ProjectInsight, TerminalCardDocument } from "../../src/insights/types";

function insight(overrides: Partial<ProjectInsight> = {}): ProjectInsight {
  return {
    identity: "mp:v1:project_insight:aaa",
    exposureId: "mp:v1:exposure:bbb",
    statement: "Three files changed together five times without a shared test.",
    claimKind: "pattern",
    confidence: 0.62,
    uncertainty: "medium",
    whyNow: "Recurred a third time this week.",
    projectConnection: "Touches the billing module.",
    nextLearningAction: "Add a regression test.",
    externalConnection: null,
    evidenceBundle: "mp:v1:evidence_bundle:ccc",
    lineageReceipt: "mp:v1:lineage_receipt:ddd",
    channel: "user_pull",
    outcome: "pending",
    ...overrides,
  };
}

function document(overrides: Partial<TerminalCardDocument> = {}): TerminalCardDocument {
  return {
    version: 1,
    project: "mp:v1:project:aaa",
    generatedAt: "2026-09-05T10:00:00Z",
    card: "Recurring co-change without a shared test",
    reason: "a real signal cleared the relevance/novelty gate",
    insight: insight(),
    ...overrides,
  };
}

describe("InsightCard", () => {
  it("shows the statement and supporting facts when there is a card", () => {
    render(<InsightCard document={document()} onFeedback={() => {}} />);
    expect(screen.getByText(/Three files changed together/)).toBeInTheDocument();
    expect(screen.getByText("Recurred a third time this week.")).toBeInTheDocument();
    expect(screen.getByText("Add a regression test.")).toBeInTheDocument();
  });

  it("shows the honest reason and no actions when there is no card", () => {
    render(
      <InsightCard
        document={document({ card: null, insight: null, reason: "nothing cleared the gate" })}
        onFeedback={() => {}}
      />,
    );
    expect(screen.getByText("nothing cleared the gate")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("calls onFeedback with the exposureId and 'saved' when Accept is clicked", async () => {
    const onFeedback = vi.fn();
    render(<InsightCard document={document()} onFeedback={onFeedback} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(onFeedback).toHaveBeenCalledWith("mp:v1:exposure:bbb", "saved");
  });

  it("calls onFeedback with 'opened' and 'dismissed' for the other two actions", async () => {
    const onFeedback = vi.fn();
    render(<InsightCard document={document()} onFeedback={onFeedback} />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onFeedback).toHaveBeenNthCalledWith(1, "mp:v1:exposure:bbb", "opened");
    expect(onFeedback).toHaveBeenNthCalledWith(2, "mp:v1:exposure:bbb", "dismissed");
  });

  it("disables the action buttons while feedback is pending", () => {
    render(<InsightCard document={document()} onFeedback={() => {}} feedbackPending />);
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeDisabled();
  });

  it("shows a feedback error when present", () => {
    render(<InsightCard document={document()} onFeedback={() => {}} feedbackError="Desktop Host unavailable" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Desktop Host unavailable");
  });
});
