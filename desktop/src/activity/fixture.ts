import type { ActivityEvent } from "./types";
import { addDays, dayOfWeek, iterateDayKeys, daysBetween, parseDayKey, startOfWeek, toDayKey } from "./calendar";

const FIXTURE_SEED = 0x4d49_444e; // "MIDN"
const WINDOW_WEEKS = 52;
/** A multi-week stretch with zero Prompt Runs so the map always shows quiet periods. */
const DEAD_ZONE_START_DAYS_AGO = 96;
const DEAD_ZONE_END_DAYS_AGO = 107;

/** Deterministic PRNG (mulberry32) so the fixture is stable for a given anchor day. */
function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state |= 0;
    state = (state + 0x6d2b_79f5) | 0;
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function localDateFromDayKey(key: string): Date {
  const { year, month, day } = parseDayKey(key);
  return new Date(year, month - 1, day);
}

/** Format a Date as ISO 8601 with the machine's local UTC offset attached. */
function toIsoWithLocalOffset(date: Date): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `${sign}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`
  );
}

export function fixtureRangeEnd(now: Date = new Date()): string {
  return toDayKey(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

/**
 * Deterministic local development fixture — NOT Performance evidence.
 *
 * Shape: a weekday work rhythm, quiet Saturdays, silent Sundays, one
 * multi-week dead zone, and occasional burst days. Anchored to "today" so the
 * map always shows a recent year; for a given anchor day the output is fully
 * reproducible.
 */
export function loadFixtureEvents(now: Date = new Date()): ActivityEvent[] {
  const rangeEnd = fixtureRangeEnd(now);
  const rangeStart = addDays(startOfWeek(rangeEnd), -(WINDOW_WEEKS - 1) * 7);
  const random = mulberry32(FIXTURE_SEED);
  const events: ActivityEvent[] = [];

  for (const key of iterateDayKeys(rangeStart, rangeEnd)) {
    const daysAgo = daysBetween(key, rangeEnd);
    let count: number;
    if (daysAgo > DEAD_ZONE_START_DAYS_AGO && daysAgo < DEAD_ZONE_END_DAYS_AGO) {
      count = 0;
    } else {
      const weekday = dayOfWeek(key);
      if (weekday === 0) {
        count = 0;
      } else if (weekday === 6) {
        count = random() < 0.55 ? 0 : 1 + Math.floor(random() * 3);
      } else {
        count = 1 + Math.floor(random() * 10);
        if (daysAgo % 23 === 5) count += 14 + Math.floor(random() * 13);
      }
    }

    for (let index = 0; index < count; index += 1) {
      const at = localDateFromDayKey(key);
      at.setHours(8 + Math.floor(random() * 15), Math.floor(random() * 60), Math.floor(random() * 60), 0);
      events.push({
        promptRunId: `pr-${key.replaceAll("-", "")}-${String(index + 1).padStart(3, "0")}`,
        occurredAt: toIsoWithLocalOffset(at),
      });
    }
  }
  return events;
}
