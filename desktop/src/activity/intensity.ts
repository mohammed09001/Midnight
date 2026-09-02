export type ActivityLevel = 0 | 1 | 2 | 3 | 4;

export interface IntensityScale {
  readonly levelOf: (promptCount: number) => ActivityLevel;
}

function percentile(sorted: readonly number[], p: number): number {
  if (sorted.length === 0) return 0;
  const position = (sorted.length - 1) * p;
  const low = Math.floor(position);
  const high = Math.ceil(position);
  if (low === high) return sorted[low];
  return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
}

/**
 * Relative activity intensity within one granularity view.
 *
 * Color communicates relative volume; the tooltip always shows the exact
 * count. Absolute thresholds differ per granularity by design — a busy month
 * is hundreds of prompts while a busy day is dozens — so intensity is scaled
 * against the nonzero counts actually visible in the current view, using
 * quartile thresholds.
 */
export function computeIntensityScale(promptCounts: readonly number[]): IntensityScale {
  const nonzero = promptCounts.filter((count) => count > 0).sort((a, b) => a - b);
  if (nonzero.length === 0) {
    return { levelOf: () => 0 };
  }
  const q1 = percentile(nonzero, 0.25);
  const q2 = percentile(nonzero, 0.5);
  const q3 = percentile(nonzero, 0.75);
  const uniform = q1 === q3;
  return {
    levelOf: (promptCount: number): ActivityLevel => {
      if (promptCount <= 0) return 0;
      if (uniform) return 2;
      if (promptCount <= q1) return 1;
      if (promptCount <= q2) return 2;
      if (promptCount <= q3) return 3;
      return 4;
    },
  };
}
