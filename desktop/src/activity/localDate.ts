/**
 * The single timezone-sensitive step of the Activity Map: reducing a
 * timezone-aware ISO instant to the calendar day key it falls on in a chosen
 * viewing timezone.
 *
 * Timezone assumption (documented per Execution 01): activity is bucketed by
 * the wall-clock calendar day of the viewing timezone, which defaults to the
 * machine's local timezone. `Intl.DateTimeFormat` performs the reduction, so
 * DST transitions are handled correctly and a Prompt Run can never drift into
 * the previous/next day due to manual millisecond arithmetic.
 */

const dayFormatterCache = new Map<string, Intl.DateTimeFormat>();

function dayFormatter(timeZone: string): Intl.DateTimeFormat {
  let formatter = dayFormatterCache.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    dayFormatterCache.set(timeZone, formatter);
  }
  return formatter;
}

export function machineTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** Reduce a timezone-aware ISO instant to its day key ("YYYY-MM-DD") in `timeZone`. */
export function localDayKey(isoInstant: string, timeZone: string = machineTimeZone()): string {
  return dayFormatter(timeZone).format(new Date(isoInstant));
}
