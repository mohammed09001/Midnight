import type { ActivityBucket } from "./types";
import { parseDayKey, utcNoonDate } from "./calendar";

const longMonth = new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" });
const shortMonth = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });

export function formatDayLong(key: string): string {
  const date = utcNoonDate(key);
  return `${longMonth.format(date)} ${date.getUTCDate()}, ${date.getUTCFullYear()}`;
}

export function formatMonthLong(key: string): string {
  const date = utcNoonDate(key);
  return `${longMonth.format(date)} ${date.getUTCFullYear()}`;
}

export function formatMonthShort(key: string): string {
  return shortMonth.format(utcNoonDate(key));
}

export function formatYearShort(key: string): string {
  return String(parseDayKey(key).year);
}

/**
 * Compact period label for tooltips and the selection confirmation.
 * Examples: "August 22, 2026" · "Aug 17–23, 2026" · "Jul 28 – Aug 3, 2026" · "August 2026".
 */
export function formatBucketPeriod(bucket: ActivityBucket): string {
  if (bucket.granularity === "day") return formatDayLong(bucket.start);
  if (bucket.granularity === "month") return formatMonthLong(bucket.start);

  const start = parseDayKey(bucket.start);
  const end = parseDayKey(bucket.end);
  const startDate = utcNoonDate(bucket.start);
  const endDate = utcNoonDate(bucket.end);
  if (start.year !== end.year) {
    return `${shortMonth.format(startDate)} ${startDate.getUTCDate()}, ${start.year} – ${shortMonth.format(endDate)} ${endDate.getUTCDate()}, ${end.year}`;
  }
  if (start.month !== end.month) {
    return `${shortMonth.format(startDate)} ${startDate.getUTCDate()} – ${shortMonth.format(endDate)} ${endDate.getUTCDate()}, ${end.year}`;
  }
  return `${shortMonth.format(startDate)} ${startDate.getUTCDate()}–${endDate.getUTCDate()}, ${end.year}`;
}

export function formatPrompts(count: number): string {
  return `${count} ${count === 1 ? "prompt" : "prompts"}`;
}
