import type { Granularity } from "../activity/types";

const OPTIONS: readonly { value: Granularity; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

interface GranularityControlProps {
  value: Granularity;
  onChange: (granularity: Granularity) => void;
}

/**
 * Day / Week / Month control — a radiogroup with roving tabindex and
 * arrow-key navigation (APG radio pattern). Selection follows focus.
 */
export function GranularityControl({ value, onChange }: GranularityControlProps) {
  const move = (delta: number) => {
    const index = OPTIONS.findIndex((option) => option.value === value);
    const next = OPTIONS[(index + delta + OPTIONS.length) % OPTIONS.length];
    onChange(next.value);
    document.getElementById(`granularity-option-${next.value}`)?.focus();
  };

  return (
    <div
      className="granularity"
      role="radiogroup"
      aria-label="Activity granularity"
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
          event.preventDefault();
          move(-1);
        } else if (event.key === "ArrowRight" || event.key === "ArrowUp") {
          event.preventDefault();
          move(1);
        }
      }}
    >
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          id={`granularity-option-${option.value}`}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          tabIndex={option.value === value ? 0 : -1}
          className="granularity__option"
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
