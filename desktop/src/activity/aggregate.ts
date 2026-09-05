import type { ActivityBucket, ActivityEvent, Granularity } from "./types";
import {
  addDays,
  addMonths,
  compareDayKeys,
  endOfMonth,
  iterateDayKeys,
  startOfMonth,
  startOfWeek,
} from "./calendar";
import { localDayKey, machineTimeZone } from "./localDate";

/**
 * Activity aggregation: the same Prompt Run events reduced to daily, weekly,
 * or monthly calendar buckets over an inclusive day-key range.
 */

export function countEventsByDay(
  events: readonly ActivityEvent[],
  rangeStart: string,
  rangeEnd: string,
  timeZone: string = machineTimeZone(),
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const event of events) {
    const key = localDayKey(event.occurredAt, timeZone);
    if (compareDayKeys(key, rangeStart) < 0 || compareDayKeys(key, rangeEnd) > 0) continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

/**
 * Aggregate events into calendar buckets.
 *
 * Weeks are Monday-anchored (ISO). Edge buckets at the range boundary are
 * complete calendar periods (a week is always 7 days, a month always ends on
 * its last calendar day); events outside the requested range are never
 * counted, so boundary buckets may legitimately show partial volume.
 */
export function aggregateActivity(
  events: readonly ActivityEvent[],
  granularity: Granularity,
  rangeStart: string,
  rangeEnd: string,
  timeZone: string = machineTimeZone(),
): ActivityBucket[] {
  if (compareDayKeys(rangeStart, rangeEnd) > 0) {
    throw new Error("activity range start must not be after range end");
  }

  const perDay = countEventsByDay(events, rangeStart, rangeEnd, timeZone);
  const sumRange = (start: string, end: string): number => {
    let total = 0;
    for (const key of iterateDayKeys(start, end)) total += perDay.get(key) ?? 0;
    return total;
  };

  if (granularity === "day") {
    return iterateDayKeys(rangeStart, rangeEnd).map((key) => ({
      key,
      granularity,
      start: key,
      end: key,
      promptCount: perDay.get(key) ?? 0,
    }));
  }

  if (granularity === "week") {
    const lastWeekStart = startOfWeek(rangeEnd);
    const buckets: ActivityBucket[] = [];
    for (let start = startOfWeek(rangeStart); compareDayKeys(start, lastWeekStart) <= 0; start = addDays(start, 7)) {
      const end = addDays(start, 6);
      buckets.push({ key: start, granularity, start, end, promptCount: sumRange(start, end) });
    }
    return buckets;
  }

  const lastMonthStart = startOfMonth(rangeEnd);
  const buckets: ActivityBucket[] = [];
  for (let start = startOfMonth(rangeStart); compareDayKeys(start, lastMonthStart) <= 0; start = addMonths(start, 1)) {
    const end = endOfMonth(start);
    buckets.push({ key: start, granularity, start, end, promptCount: sumRange(start, end) });
  }
  return buckets;
}

/**
 * The individual Prompt Run events falling within one bucket's inclusive
 * local calendar day range, newest first — the source list for the
 * run-selector step between selecting an Activity Map period and opening
 * one real Prompt Run's graph. Mirrors `countEventsByDay`'s own day-key
 * reduction so a bucket's selector list always matches what its own count
 * was computed from.
 */
export function eventsInBucket(
  events: readonly ActivityEvent[],
  bucket: ActivityBucket,
  timeZone: string = machineTimeZone(),
): ActivityEvent[] {
  return events
    .filter((event) => {
      const key = localDayKey(event.occurredAt, timeZone);
      return compareDayKeys(key, bucket.start) >= 0 && compareDayKeys(key, bucket.end) <= 0;
    })
    .sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime());
}

/** Default Activity Map window: the 52 Monday-anchored weeks ending on `todayKey`. */
export function defaultActivityRange(todayKey: string): { rangeStart: string; rangeEnd: string } {
  return {
    rangeStart: addDays(startOfWeek(todayKey), -51 * 7),
    rangeEnd: todayKey,
  };
}

/**
 * Activity Map range for real evidence: the visible end is always the current
 * local calendar day (`todayKey`, injected for deterministic tests), while
 * historical Prompt Run evidence decides how far back the map reaches — the
 * default 52-week window is extended left, week-aligned, when real events are
 * older. Evidence beyond the bounded loaded page is a coverage fact reported
 * by the source, not something the range may silently fabricate.
 */
export function activityRangeForEvents(
  events: readonly ActivityEvent[],
  todayKey: string,
  timeZone: string = machineTimeZone(),
): { rangeStart: string; rangeEnd: string } {
  const range = defaultActivityRange(todayKey);
  let rangeStart = range.rangeStart;
  for (const event of events) {
    const key = localDayKey(event.occurredAt, timeZone);
    if (compareDayKeys(key, rangeStart) < 0) rangeStart = startOfWeek(key);
  }
  return { rangeStart, rangeEnd: range.rangeEnd };
}
