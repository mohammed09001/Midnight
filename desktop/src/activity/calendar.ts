const DAY_MS = 86_400_000;
const DAY_KEY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Calendar primitives for Activity Map bucketing.
 *
 * All arithmetic operates on plain day keys ("YYYY-MM-DD") anchored to
 * UTC-noon Date objects, so calendar math never crosses a timezone or DST
 * boundary. The only timezone-sensitive step — reducing an observed instant
 * to a viewer-local day key — lives in `localDate.ts`.
 */

export function parseDayKey(key: string): { year: number; month: number; day: number } {
  const match = DAY_KEY_PATTERN.exec(key);
  if (!match) throw new Error(`invalid day key: ${key}`);
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

export function toDayKey(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function utcNoonDate(key: string): Date {
  const { year, month, day } = parseDayKey(key);
  return new Date(Date.UTC(year, month - 1, day, 12));
}

export function addDays(key: string, days: number): string {
  return new Date(utcNoonDate(key).getTime() + days * DAY_MS).toISOString().slice(0, 10);
}

/** 0 = Sunday … 6 = Saturday */
export function dayOfWeek(key: string): number {
  return utcNoonDate(key).getUTCDay();
}

/** ISO week start: Monday. */
export function startOfWeek(key: string): string {
  return addDays(key, -((dayOfWeek(key) + 6) % 7));
}

export function startOfMonth(key: string): string {
  const { year, month } = parseDayKey(key);
  return toDayKey(year, month, 1);
}

export function endOfMonth(key: string): string {
  const { year, month } = parseDayKey(key);
  const nextMonthStart = month === 12 ? toDayKey(year + 1, 1, 1) : toDayKey(year, month + 1, 1);
  return addDays(nextMonthStart, -1);
}

/** Only meaningful on month-start keys (used to iterate calendar months). */
export function addMonths(key: string, months: number): string {
  const { year, month, day } = parseDayKey(key);
  const total = year * 12 + (month - 1) + months;
  const nextYear = Math.floor(total / 12);
  const nextMonth = (total % 12) + 1;
  const lastDay = new Date(Date.UTC(nextYear, nextMonth, 0)).getUTCDate();
  return toDayKey(nextYear, nextMonth, Math.min(day, lastDay));
}

export function compareDayKeys(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function iterateDayKeys(start: string, end: string): string[] {
  if (compareDayKeys(start, end) > 0) return [];
  const keys: string[] = [];
  for (let key = start; compareDayKeys(key, end) <= 0; key = addDays(key, 1)) {
    keys.push(key);
  }
  return keys;
}

export function iterateMonthKeys(start: string, end: string): string[] {
  const first = startOfMonth(start);
  const last = startOfMonth(end);
  if (compareDayKeys(first, last) > 0) return [];
  const keys: string[] = [];
  for (let key = first; compareDayKeys(key, last) <= 0; key = addMonths(key, 1)) {
    keys.push(key);
  }
  return keys;
}

export function daysBetween(a: string, b: string): number {
  return Math.round((utcNoonDate(b).getTime() - utcNoonDate(a).getTime()) / DAY_MS);
}
