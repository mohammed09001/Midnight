import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GraphControls } from "../../src/components/GraphControls";

const LAYERS = ["prompt", "execution", "verification"];

describe("GraphControls", () => {
  it("shows every layer checked when activeLayers is null (unfiltered)", () => {
    render(
      <GraphControls layers={LAYERS} activeLayers={null} onChange={() => {}} onResetView={() => {}} showOnDemand={false} onToggleOnDemand={() => {}} />,
    );
    for (const layer of LAYERS) {
      expect(screen.getByLabelText(layer)).toBeChecked();
    }
  });

  it("unchecking a layer calls onChange with every layer except it", async () => {
    const onChange = vi.fn();
    render(
      <GraphControls layers={LAYERS} activeLayers={null} onChange={onChange} onResetView={() => {}} showOnDemand={false} onToggleOnDemand={() => {}} />,
    );
    await userEvent.click(screen.getByLabelText("execution"));
    expect(onChange).toHaveBeenCalledWith(new Set(["prompt", "verification"]));
  });

  it("re-checking every layer collapses back to null (unfiltered)", async () => {
    const onChange = vi.fn();
    render(
      <GraphControls
        layers={LAYERS}
        activeLayers={new Set(["prompt", "verification"])}
        onChange={onChange}
        onResetView={() => {}}
        showOnDemand={false}
        onToggleOnDemand={() => {}}
      />,
    );
    await userEvent.click(screen.getByLabelText("execution"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("calls onResetView from the reset button", async () => {
    const onResetView = vi.fn();
    render(
      <GraphControls layers={LAYERS} activeLayers={null} onChange={() => {}} onResetView={onResetView} showOnDemand={false} onToggleOnDemand={() => {}} />,
    );
    await userEvent.click(screen.getByText("Reset view"));
    expect(onResetView).toHaveBeenCalled();
  });

  it("reflects showOnDemand and calls onToggleOnDemand when clicked", async () => {
    const onToggleOnDemand = vi.fn();
    render(
      <GraphControls layers={LAYERS} activeLayers={null} onChange={() => {}} onResetView={() => {}} showOnDemand={false} onToggleOnDemand={onToggleOnDemand} />,
    );
    const checkbox = screen.getByLabelText(/Show on-demand evidence/);
    expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    expect(onToggleOnDemand).toHaveBeenCalledTimes(1);
  });
});
