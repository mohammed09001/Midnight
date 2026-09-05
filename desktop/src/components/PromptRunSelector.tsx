import type { ActivityEvent } from "../activity/types";
import { formatTimeOfDay } from "../activity/format";

interface PromptRunSelectorProps {
  events: readonly ActivityEvent[];
  onSelect: (event: ActivityEvent) => void;
  onBack: () => void;
}

/**
 * The step between an Activity Map period and one Prompt Run's graph: a
 * radiogroup with roving tabindex and arrow-key navigation, mirroring
 * `GranularityControl.tsx`'s established accessibility pattern (APG radio
 * group) rather than inventing a second list-selection idiom.
 */
export function PromptRunSelector({ events, onSelect, onBack }: PromptRunSelectorProps) {
  const move = (delta: number, currentId: string) => {
    if (events.length === 0) return;
    const index = events.findIndex((event) => event.promptRunId === currentId);
    const next = events[(index + delta + events.length) % events.length];
    document.getElementById(promptRunOptionId(next.promptRunId))?.focus();
  };

  return (
    <div className="prompt-run-selector">
      <div className="prompt-run-selector__header">
        <button type="button" className="prompt-run-selector__back" onClick={onBack}>
          ← Back to Activity Map
        </button>
        <span className="prompt-run-selector__count">{events.length === 1 ? "1 Prompt Run" : `${events.length} Prompt Runs`}</span>
      </div>
      {events.length === 0 ? (
        <p className="panel__status" role="status">
          No Prompt Runs in this period.
        </p>
      ) : (
        <div
          className="prompt-run-selector__list"
          role="radiogroup"
          aria-label="Select a Prompt Run"
          onKeyDown={(keyEvent) => {
            const currentId = (keyEvent.target as HTMLElement).dataset.promptRunId;
            if (!currentId) return;
            if (keyEvent.key === "ArrowUp" || keyEvent.key === "ArrowLeft") {
              keyEvent.preventDefault();
              move(-1, currentId);
            } else if (keyEvent.key === "ArrowDown" || keyEvent.key === "ArrowRight") {
              keyEvent.preventDefault();
              move(1, currentId);
            }
          }}
        >
          {events.map((event, index) => (
            <button
              key={event.promptRunId}
              id={promptRunOptionId(event.promptRunId)}
              type="button"
              role="radio"
              aria-checked={false}
              tabIndex={index === 0 ? 0 : -1}
              data-prompt-run-id={event.promptRunId}
              className="prompt-run-selector__option"
              onClick={() => onSelect(event)}
            >
              {formatTimeOfDay(event.occurredAt)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function promptRunOptionId(promptRunId: string): string {
  return `prompt-run-option-${encodeURIComponent(promptRunId)}`;
}
