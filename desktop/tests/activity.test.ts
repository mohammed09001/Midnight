import { describe, expect, it } from "vitest";
import {
  addDays,
  compareDayKeys,
  endOfMonth,
  iterateDayKeys,
  startOfMonth,
  startOfWeek,
} from "../src/activity/calendar";
import { localDayKey } from "../src/activity/localDate";
import { aggregateActivity, countEventsByDay, defaultActivityRange } from "../src/activity/aggregate";
import { computeIntensityScale } from "../src/activity/intensity";
import { formatBucketPeriod, formatPrompts } from "../src/activity/format";
import { loadFixtureEvents } from "../src/activity/fixture";
import type { ActivityEvent } from "../src/activity/types";

const UTC = "UTC";

function event(promptRunId: string, occurredAt: string): ActivityEvent {
  return { promptRunId, occurredAt };
}

describe("calendar primitives", () => {
  it("anchors weeks on Monday (ISO)", () => {
    expect(startOfWeek("2026-08-17")).toBe("2026-08-17"); // Monday
    expect(startOfWeek("2026-08-22")).toBe("2026-08-17"); // Saturday
    expect(startOfWeek("2026-08-23")).toBe("2026-08-17"); // Sunday
  });

  it("computes month ends including leap-feel edge months", () => {
    expect(endOfMonth("2026-08-09")).toBe("2026-08-31");
    expect(endOfMonth("2026-12-01")).toBe("2026-12-31");
    expect(startOfMonth("2026-08-22")).toBe("2026-08-01");
  });

  it("iterates inclusive day ranges and compares keys", () => {
    expect(iterateDayKeys("2026-08-30", "2026-09-02")).toEqual([
      "2026-08-30",
      "2026-08-31",
      "2026-09-01",
      "2026-09-02",
    ]);
    expect(compareDayKeys("2026-08-31", "2026-09-01")).toBe(-1);
    expect(addDays("2026-08-31", 1)).toBe("2026-09-01");
    expect(addDays("2026-09-01", -1)).toBe("2026-08-31");
  });
});

describe("timezone reduction", () => {
  it("keeps late-evening and midnight instants on their correct local day", () => {
    expect(localDayKey("2026-08-22T23:59:59Z", UTC)).toBe("2026-08-22");
    expect(localDayKey("2026-08-23T00:00:00Z", UTC)).toBe("2026-08-23");
  });

  it("shifts days when the viewing timezone crosses midnight", () => {
    // 20:00 in UTC-5 is already 01:00 UTC / 06:30 next day in UTC+5:30.
    expect(localDayKey("2026-08-22T20:00:00-05:00", "Asia/Kolkata")).toBe("2026-08-23");
    expect(localDayKey("2026-08-22T20:00:00-05:00", UTC)).toBe("2026-08-23");
    expect(localDayKey("2026-08-22T20:00:00-05:00", "America/New_York")).toBe("2026-08-22");
  });
});

describe("daily aggregation", () => {
  it("counts events per day and includes zero-activity days", () => {
    const events = [
      event("a", "2026-08-20T09:00:00Z"),
      event("b", "2026-08-20T17:30:00Z"),
      event("c", "2026-08-22T11:00:00Z"),
    ];
    const buckets = aggregateActivity(events, "day", "2026-08-19", "2026-08-23", UTC);
    expect(buckets.map((bucket) => bucket.promptCount)).toEqual([0, 2, 0, 1, 0]);
    expect(buckets[0].start).toBe("2026-08-19");
    expect(buckets[4].end).toBe("2026-08-23");
  });

  it("ignores events outside the requested range", () => {
    const events = [
      event("early", "2026-08-01T09:00:00Z"),
      event("inside", "2026-08-20T09:00:00Z"),
      event("late", "2026-09-30T09:00:00Z"),
    ];
    const counts = countEventsByDay(events, "2026-08-15", "2026-08-25", UTC);
    expect(counts.size).toBe(1);
    expect(counts.get("2026-08-20")).toBe(1);
  });
});

describe("weekly aggregation", () => {
  it("merges a whole calendar week into one Monday-anchored bucket", () => {
    const events = [
      event("wed", "2026-08-19T09:00:00Z"),
      event("sun", "2026-08-23T23:00:00Z"),
    ];
    const buckets = aggregateActivity(events, "week", "2026-08-17", "2026-08-23", UTC);
    expect(buckets).toHaveLength(1);
    expect(buckets[0].key).toBe("2026-08-17");
    expect(buckets[0].start).toBe("2026-08-17");
    expect(buckets[0].end).toBe("2026-08-23");
    expect(buckets[0].promptCount).toBe(2);
  });

  it("keeps weeks that cross a month boundary intact", () => {
    const events = [
      event("jul", "2026-07-30T09:00:00Z"),
      event("aug", "2026-08-01T09:00:00Z"),
      event("next-week", "2026-08-03T09:00:00Z"),
    ];
    const buckets = aggregateActivity(events, "week", "2026-07-27", "2026-08-09", UTC);
    expect(buckets[0].start).toBe("2026-07-27");
    expect(buckets[0].end).toBe("2026-08-02");
    expect(buckets[0].promptCount).toBe(2);
    expect(buckets[1].promptCount).toBe(1);
  });

  it("never counts events outside the range even inside edge weeks", () => {
    const events = [
      event("before-range", "2026-08-16T09:00:00Z"), // Sunday before the Monday start
      event("inside", "2026-08-19T09:00:00Z"),
    ];
    const buckets = aggregateActivity(events, "week", "2026-08-17", "2026-08-23", UTC);
    expect(buckets[0].promptCount).toBe(1);
  });
});

describe("monthly aggregation", () => {
  it("produces complete calendar months", () => {
    const events = [
      event("a", "2026-07-31T09:00:00Z"),
      event("b", "2026-08-01T09:00:00Z"),
      event("c", "2026-08-31T09:00:00Z"),
    ];
    const buckets = aggregateActivity(events, "month", "2026-07-15", "2026-08-31", UTC);
    expect(buckets).toHaveLength(2);
    expect(buckets[0].start).toBe("2026-07-01");
    expect(buckets[0].end).toBe("2026-07-31");
    expect(buckets[0].promptCount).toBe(1);
    expect(buckets[1].start).toBe("2026-08-01");
    expect(buckets[1].end).toBe("2026-08-31");
    expect(buckets[1].promptCount).toBe(2);
  });
});

describe("aggregation consistency", () => {
  const events = Array.from({ length: 40 }, (_, index) => {
    const day = 1 + ((index * 7) % 31);
    const month = index % 3 === 0 ? "06" : index % 3 === 1 ? "07" : "08";
    return event(`e${index}`, `2026-${month}-${String(day).padStart(2, "0")}T12:00:00Z`);
  });

  it("preserves prompt totals across day, week, and month granularity", () => {
    const daily = aggregateActivity(events, "day", "2026-06-01", "2026-08-31", UTC);
    const weekly = aggregateActivity(events, "week", "2026-06-01", "2026-08-31", UTC);
    const monthly = aggregateActivity(events, "month", "2026-06-01", "2026-08-31", UTC);
    const sum = (buckets: { promptCount: number }[]) =>
      buckets.reduce((total, bucket) => total + bucket.promptCount, 0);
    expect(sum(daily)).toBe(events.length);
    expect(sum(weekly)).toBe(events.length);
    expect(sum(monthly)).toBe(events.length);
  });

  it("exposes zero-activity periods explicitly", () => {
    const daily = aggregateActivity([], "day", "2026-08-01", "2026-08-07", UTC);
    expect(daily).toHaveLength(7);
    expect(daily.every((bucket) => bucket.promptCount === 0)).toBe(true);
    const weekly = aggregateActivity([], "week", "2026-08-01", "2026-08-07", UTC);
    expect(weekly).toHaveLength(2); // Jul 27–Aug 2 and Aug 3–9 edge weeks
    expect(weekly.every((bucket) => bucket.promptCount === 0)).toBe(true);
  });

  it("rejects inverted ranges", () => {
    expect(() => aggregateActivity([], "day", "2026-08-10", "2026-08-01", UTC)).toThrow();
  });
});

describe("intensity scale", () => {
  it("ranks nonzero counts into four relative levels", () => {
    const scale = computeIntensityScale([0, 0, 2, 4, 6, 8, 100]);
    expect(scale.levelOf(0)).toBe(0);
    expect(scale.levelOf(2)).toBe(1);
    expect(scale.levelOf(6)).toBe(2);
    expect(scale.levelOf(8)).toBe(3);
    expect(scale.levelOf(100)).toBe(4);
  });

  it("handles all-zero and uniform views without singularities", () => {
    const zeros = computeIntensityScale([0, 0, 0]);
    expect(zeros.levelOf(0)).toBe(0);
    const uniform = computeIntensityScale([5, 5, 5]);
    expect(uniform.levelOf(5)).toBe(2);
  });
});

describe("period formatting", () => {
  it("formats day, month, and week periods for tooltips", () => {
    expect(
      formatBucketPeriod({ key: "2026-08-22", granularity: "day", start: "2026-08-22", end: "2026-08-22", promptCount: 14 }),
    ).toBe("August 22, 2026");
    expect(
      formatBucketPeriod({ key: "2026-08-17", granularity: "week", start: "2026-08-17", end: "2026-08-23", promptCount: 61 }),
    ).toBe("Aug 17–23, 2026");
    expect(
      formatBucketPeriod({ key: "2026-07-27", granularity: "week", start: "2026-07-27", end: "2026-08-02", promptCount: 10 }),
    ).toBe("Jul 27 – Aug 2, 2026");
    expect(
      formatBucketPeriod({ key: "2025-12-29", granularity: "week", start: "2025-12-29", end: "2026-01-04", promptCount: 3 }),
    ).toBe("Dec 29, 2025 – Jan 4, 2026");
    expect(
      formatBucketPeriod({ key: "2026-08-01", granularity: "month", start: "2026-08-01", end: "2026-08-31", promptCount: 238 }),
    ).toBe("August 2026");
  });

  it("formats exact prompt counts", () => {
    expect(formatPrompts(1)).toBe("1 prompt");
    expect(formatPrompts(14)).toBe("14 prompts");
  });
});

describe("default range", () => {
  it("spans exactly 52 Monday-anchored weeks ending today", () => {
    const { rangeStart, rangeEnd } = defaultActivityRange("2026-09-02");
    expect(rangeEnd).toBe("2026-09-02");
    expect(startOfWeek(rangeStart)).toBe(rangeStart);
    const weeks = aggregateActivity([], "week", rangeStart, rangeEnd, UTC);
    expect(weeks).toHaveLength(52);
    // 51 full weeks plus the partial current week (ends on the anchor, a Wednesday).
    expect(iterateDayKeys(rangeStart, rangeEnd)).toHaveLength(360);
    expect(rangeEnd).toBe(addDays(rangeStart, 359));
  });
});

describe("development fixture", () => {
  it("is deterministic for a given anchor day", () => {
    const anchor = new Date(2026, 8, 2, 12, 0, 0);
    expect(JSON.stringify(loadFixtureEvents(anchor))).toBe(JSON.stringify(loadFixtureEvents(anchor)));
  });

  it("emits timezone-aware timestamps covering quiet and busy periods", () => {
    const events = loadFixtureEvents(new Date(2026, 8, 2, 12, 0, 0));
    expect(events.length).toBeGreaterThan(500);
    for (const single of events) {
      expect(single.occurredAt).toMatch(/T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/);
    }
    const { rangeStart, rangeEnd } = defaultActivityRange("2026-09-02");
    const daily = aggregateActivity(events, "day", rangeStart, rangeEnd, UTC);
    const zeroDays = daily.filter((bucket) => bucket.promptCount === 0);
    const maxDay = Math.max(...daily.map((bucket) => bucket.promptCount));
    expect(zeroDays.length).toBeGreaterThan(20);
    expect(maxDay).toBeGreaterThan(20);
    const monthly = aggregateActivity(events, "month", rangeStart, rangeEnd, UTC);
    expect(monthly.length).toBeGreaterThanOrEqual(13);
    expect(monthly[0].promptCount).toBeGreaterThanOrEqual(0);
  });
});
