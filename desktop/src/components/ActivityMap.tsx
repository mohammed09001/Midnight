import { useMemo, useRef, useState } from "react";
import type { ActivityBucket, ActivityMapData } from "../activity/types";
import { computeIntensityScale } from "../activity/intensity";
import { formatMonthShort, formatYearShort } from "../activity/format";
import { startOfMonth, startOfWeek } from "../activity/calendar";
import { ActivityCell } from "./ActivityCell";
import { ActivityTooltip } from "./ActivityTooltip";

interface ActivityMapProps {
  data: ActivityMapData;
  /** Key of the selected bucket, or null when no period is selected. */
  selectedKey: string | null;
  onPeriodSelect: (bucket: ActivityBucket | null) => void;
}

interface TooltipState {
  bucket: ActivityBucket;
  x: number;
  y: number;
  viewportWidth: number;
}

interface AxisSpan {
  label: string;
  colStart: number;
  colSpan: number;
}

const WEEKDAYS_SHOWN = [1, 3, 5]; // Mon, Wed, Fri
const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Month labels for the day/week-mode axis: consecutive columns whose anchor
 * day falls in the same month are grouped into one labelled span.
 */
function monthAxisSpans(anchorKeys: readonly string[]): AxisSpan[] {
  const spans: AxisSpan[] = [];
  for (let index = 0; index < anchorKeys.length; ) {
    const monthStart = startOfMonth(anchorKeys[index]);
    let span = 1;
    while (
      index + span < anchorKeys.length &&
      startOfMonth(anchorKeys[index + span]) === monthStart
    ) {
      span += 1;
    }
    spans.push({ label: formatMonthShort(monthStart), colStart: index + 1, colSpan: span });
    index += span;
  }
  return spans;
}

export function ActivityMap({ data, selectedKey, onPeriodSelect }: ActivityMapProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const { granularity, buckets } = data;

  const levels = useMemo(
    () => computeIntensityScale(buckets.map((bucket) => bucket.promptCount)),
    [buckets],
  );

  const isDayMode = granularity === "day";
  const weekColumns = isDayMode ? Math.ceil(buckets.length / 7) : 0;
  const singleRow = granularity !== "day";

  const axisSpans = useMemo<AxisSpan[] | null>(() => {
    if (granularity === "month") return null;
    const anchors =
      granularity === "week"
        ? buckets.map((bucket) => bucket.start)
        : Array.from({ length: weekColumns }, (_, column) => {
            const firstOfDayColumn = buckets[column * 7];
            return firstOfDayColumn ? startOfWeek(firstOfDayColumn.start) : "";
          }).filter(Boolean);
    return monthAxisSpans(anchors);
  }, [granularity, buckets, weekColumns]);

  const inspect = (bucket: ActivityBucket, cell: HTMLButtonElement | null) => {
    if (!cell || !viewportRef.current) {
      setTooltip(null);
      return;
    }
    const viewportRect = viewportRef.current.getBoundingClientRect();
    const cellRect = cell.getBoundingClientRect();
    setTooltip({
      bucket,
      x: cellRect.left - viewportRect.left + cellRect.width / 2,
      y: cellRect.top - viewportRect.top,
      viewportWidth: viewportRef.current.clientWidth,
    });
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    const index = Number(target.dataset.index ?? "-1");
    if (index < 0 || !buckets.length) return;
    const rowStride = isDayMode ? 7 : 1;
    const delta =
      event.key === "ArrowRight" ? rowStride
      : event.key === "ArrowLeft" ? -rowStride
      : singleRow ? 0
      : event.key === "ArrowDown" ? 1
      : event.key === "ArrowUp" ? -1
      : 0;
    if (delta === 0) return;
    event.preventDefault();
    const next = Math.min(buckets.length - 1, Math.max(0, index + delta));
    viewportRef.current
      ?.querySelector<HTMLButtonElement>(`[data-index="${next}"]`)
      ?.focus();
  };

  const gridTemplateColumns =
    granularity === "day"
      ? undefined
      : `repeat(${buckets.length}, minmax(0, 1fr))`;

  return (
    <div className={`activity-map activity-map--${granularity}`}>
      <div
        ref={viewportRef}
        className="activity-map__viewport"
        role="group"
        aria-label={`Activity map, ${granularity} view`}
        onKeyDown={handleKeyDown}
        onMouseLeave={() => setTooltip(null)}
      >
        <div className="activity-map__stack">
          {isDayMode && (
            <div className="activity-map__weekdays" aria-hidden="true">
              {WEEKDAYS_SHOWN.map((weekday) => (
                <span key={weekday} style={{ gridRow: weekday + 1 }}>
                  {WEEKDAY_LABELS[weekday]}
                </span>
              ))}
            </div>
          )}
          <div className="activity-map__mapcol">
            {axisSpans && (
              <div
                className="activity-map__axis"
                aria-hidden="true"
                style={{
                  gridTemplateColumns:
                    granularity === "day"
                      ? `repeat(${weekColumns}, var(--cell))`
                      : gridTemplateColumns,
                }}
              >
                {axisSpans.map((span) => (
                  <span key={`${span.label}-${span.colStart}`} style={{ gridColumn: `${span.colStart} / span ${span.colSpan}` }}>
                    {span.label}
                  </span>
                ))}
              </div>
            )}
            <div
              className={`activity-map__grid activity-map__grid--${granularity}`}
              style={gridTemplateColumns ? { gridTemplateColumns } : undefined}
            >
              {buckets.map((bucket, index) => (
                <ActivityCell
                  key={bucket.key}
                  bucket={bucket}
                  level={levels.levelOf(bucket.promptCount)}
                  selected={bucket.key === selectedKey}
                  index={index}
                  innerLabel={
                    granularity === "month"
                      ? { title: formatMonthShort(bucket.start), sub: formatYearShort(bucket.start) }
                      : undefined
                  }
                  onInspect={inspect}
                  onSelect={(clicked) =>
                    onPeriodSelect(clicked.key === selectedKey ? null : clicked)
                  }
                />
              ))}
            </div>
          </div>
        </div>
        {tooltip && (
          <ActivityTooltip
            bucket={tooltip.bucket}
            x={tooltip.x}
            y={tooltip.y}
            viewportWidth={tooltip.viewportWidth}
          />
        )}
      </div>
    </div>
  );
}
