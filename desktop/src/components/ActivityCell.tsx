import type { ActivityBucket } from "../activity/types";
import { formatBucketPeriod, formatPrompts } from "../activity/format";

interface ActivityCellProps {
  bucket: ActivityBucket;
  level: number;
  selected: boolean;
  index: number;
  /** Month-mode interior label; day/week cells carry no interior text. */
  innerLabel?: { title: string; sub?: string };
  onInspect: (bucket: ActivityBucket, cell: HTMLButtonElement | null) => void;
  onSelect: (bucket: ActivityBucket) => void;
}

/**
 * One interactive activity period. The accessible label carries period +
 * exact prompt count, so hover, focus, and screen readers all receive
 * equivalent information.
 */
export function ActivityCell({ bucket, level, selected, index, innerLabel, onInspect, onSelect }: ActivityCellProps) {
  return (
    <button
      type="button"
      className="activity-cell"
      data-level={level}
      data-selected={selected || undefined}
      data-index={index}
      aria-pressed={selected}
      aria-label={`${formatBucketPeriod(bucket)}, ${formatPrompts(bucket.promptCount)}`}
      onMouseEnter={(event) => onInspect(bucket, event.currentTarget)}
      onMouseLeave={() => onInspect(bucket, null)}
      onFocus={(event) => onInspect(bucket, event.currentTarget)}
      onBlur={() => onInspect(bucket, null)}
      onClick={() => onSelect(bucket)}
    >
      {innerLabel && (
        <span className="activity-cell__meta">
          <span className="activity-cell__title">{innerLabel.title}</span>
          {innerLabel.sub && <span className="activity-cell__sub">{innerLabel.sub}</span>}
        </span>
      )}
    </button>
  );
}
