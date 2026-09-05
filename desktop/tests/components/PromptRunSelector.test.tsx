import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PromptRunSelector } from "../../src/components/PromptRunSelector";
import { formatTimeOfDay } from "../../src/activity/format";
import type { ActivityEvent } from "../../src/activity/types";

const EVENTS: ActivityEvent[] = [
  { promptRunId: "mp:v1:prompt_run:aaa", occurredAt: "2026-08-20T09:05:00Z" },
  { promptRunId: "mp:v1:prompt_run:bbb", occurredAt: "2026-08-20T17:30:00Z" },
];

describe("PromptRunSelector", () => {
  it("renders one radio option per event, labelled by time of day", () => {
    render(<PromptRunSelector events={EVENTS} onSelect={() => {}} onBack={() => {}} />);
    const options = screen.getAllByRole("radio");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent(formatTimeOfDay(EVENTS[0].occurredAt));
    expect(options[1]).toHaveTextContent(formatTimeOfDay(EVENTS[1].occurredAt));
  });

  it("shows an honest empty state when the bucket has no events", () => {
    render(<PromptRunSelector events={[]} onSelect={() => {}} onBack={() => {}} />);
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("No Prompt Runs in this period.");
  });

  it("calls onSelect with the clicked event", async () => {
    const onSelect = vi.fn();
    render(<PromptRunSelector events={EVENTS} onSelect={onSelect} onBack={() => {}} />);
    await userEvent.click(screen.getByText(formatTimeOfDay(EVENTS[0].occurredAt)));
    expect(onSelect).toHaveBeenCalledWith(EVENTS[0]);
  });

  it("calls onBack from the back button", async () => {
    const onBack = vi.fn();
    render(<PromptRunSelector events={EVENTS} onSelect={() => {}} onBack={onBack} />);
    await userEvent.click(screen.getByText(/Back to Activity Map/));
    expect(onBack).toHaveBeenCalled();
  });

  it("only the first option is in the tab order (roving tabindex)", () => {
    render(<PromptRunSelector events={EVENTS} onSelect={() => {}} onBack={() => {}} />);
    const options = screen.getAllByRole("radio");
    expect(options[0]).toHaveAttribute("tabIndex", "0");
    expect(options[1]).toHaveAttribute("tabIndex", "-1");
  });
});
