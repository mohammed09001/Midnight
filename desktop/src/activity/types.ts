export type Granularity = "day" | "week" | "month";

/**
 * One observed Prompt Run.
 *
 * `occurredAt` is a timezone-aware ISO 8601 instant, matching the Midnight
 * Performance convention that evidence timestamps must never be naive.
 */
export interface ActivityEvent {
  readonly promptRunId: string;
  readonly occurredAt: string;
}

/**
 * One Activity Map period. `start`/`end` are inclusive local calendar day
 * keys ("YYYY-MM-DD"); `key` is the stable identity of the period within its
 * granularity (for day it equals `start`, for week the week's Monday, for
 * month the month's first day).
 */
export interface ActivityBucket {
  readonly key: string;
  readonly granularity: Granularity;
  readonly start: string;
  readonly end: string;
  readonly promptCount: number;
}

export interface ActivityMapData {
  readonly granularity: Granularity;
  readonly rangeStart: string;
  readonly rangeEnd: string;
  readonly buckets: readonly ActivityBucket[];
}
