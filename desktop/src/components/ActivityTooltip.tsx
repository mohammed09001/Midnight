import type { ActivityBucket } from "../activity/types";
import { formatBucketPeriod, formatPrompts } from "../activity/format";

interface ActivityTooltipProps {
  bucket: ActivityBucket;
  /** Anchor point in the map viewport's coordinate space (cell center, cell top). */
  x: number;
  y: number;
  viewportWidth: number;
}

const EDGE_MARGIN = 8;
/** Keeps the tooltip roughly centered over narrow cells without measuring it. */
const HALF_WIDTH = 84;

/**
 * Minimal contextual tooltip: period + prompt count, nothing else.
 * Information is duplicated in each cell's accessible label, so the tooltip
 * itself is hidden from assistive technology.
 */
export function ActivityTooltip({ bucket, x, y, viewportWidth }: ActivityTooltipProps) {
  const clampedX = Math.min(
    Math.max(x, HALF_WIDTH + EDGE_MARGIN),
    Math.max(HALF_WIDTH + EDGE_MARGIN, viewportWidth - HALF_WIDTH - EDGE_MARGIN),
  );
  return (
    <div className="activity-tooltip" aria-hidden="true" style={{ left: clampedX, top: y }}>
      <span className="activity-tooltip__period">{formatBucketPeriod(bucket)}</span>
      <span className="activity-tooltip__count">{formatPrompts(bucket.promptCount)}</span>
    </div>
  );
}
