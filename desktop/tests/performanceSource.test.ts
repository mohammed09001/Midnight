import { describe, expect, it } from "vitest";
import {
  fetchPerformanceActivity,
  PerformanceContractVersionError,
  PerformanceHostError,
  PerformanceInvalidResponseError,
  PerformanceUnavailableError,
  DESKTOP_HOST_URL,
  type PerformanceFetch,
} from "../src/activity/performanceSource";
import {
  defaultActivitySource,
  fixtureSource,
  loadActivity,
  loadActivityEvents,
  performanceSource,
  resolveActivitySource,
} from "../src/activity/adapter";
import { activityRangeForEvents, aggregateActivity } from "../src/activity/aggregate";
import { localDayKey } from "../src/activity/localDate";
import { loadFixtureEvents } from "../src/activity/fixture";
import { startOfWeek, addDays } from "../src/activity/calendar";
import type { ActivityEvent } from "../src/activity/types";

const UTC = "UTC";

/** Simulates the Desktop Host's HTTP surface: asserts the exact request shape it expects. */
function respond(body: unknown, status = 200): PerformanceFetch {
  return (url, init) => {
    expect(url).toBe(DESKTOP_HOST_URL);
    expect(init?.method).toBe("POST");
    expect(() => JSON.parse(String(init?.body))).not.toThrow();
    const request = JSON.parse(String(init?.body));
    expect(request).toEqual({ contractVersion: 1, operation: "activity.listPromptRuns", request: {} });
    return Promise.resolve(
      new Response(typeof body === "string" ? body : JSON.stringify(body), { status }),
    );
  };
}

function bridgeDocument(events: unknown[], extra: Record<string, unknown> = {}) {
  return {
    version: 1,
    project: "mp:v1:project:3b24a17f-0c8e-5a10-9d1c-2f4e6a8b0c1d",
    events,
    totalMatching: events.length,
    limit: 100,
    complete: true,
    cursor: null,
    nextCursor: null,
    ...extra,
  };
}

/** Wraps an `activity.listPromptRuns` result in the real Host success envelope. */
function successEnvelope(result: unknown) {
  return { contractVersion: 1, operation: "activity.listPromptRuns", ok: true, result };
}

/** Wraps a typed error in the real Host error envelope. */
function errorEnvelope(code: string, message = "Desktop Host error") {
  return { contractVersion: 1, operation: "activity.listPromptRuns", ok: false, error: { code, message } };
}

function respondOk(document: unknown, status = 200): PerformanceFetch {
  return respond(successEnvelope(document), status);
}

async function eventsFrom(document: unknown): Promise<readonly ActivityEvent[]> {
  return (await fetchPerformanceActivity(respondOk(document))).events;
}

describe("performance activity boundary", () => {
  it("converts valid Prompt Run evidence into valid ActivityEvents", async () => {
    const events = await eventsFrom(
      bridgeDocument([
        { promptRunId: "mp:v1:prompt_run:aaa", occurredAt: "2026-09-02T10:31:22+04:00" },
        { promptRunId: "mp:v1:prompt_run:bbb", occurredAt: "2026-09-01T18:00:00Z" },
      ]),
    );
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ promptRunId: "mp:v1:prompt_run:aaa", occurredAt: "2026-09-02T10:31:22+04:00" });
  });

  it("preserves the Prompt Run identity exactly", async () => {
    const canonical = "mp:v1:prompt_run:9f8c1d2e-4a5b-6c7d-8e9f-0a1b2c3d4e5f";
    const events = await eventsFrom(bridgeDocument([{ promptRunId: canonical, occurredAt: "2026-09-02T06:00:00Z" }]));
    expect(events[0].promptRunId).toBe(canonical);
  });

  it("preserves timezone-aware instants and buckets them in the viewer's calendar", async () => {
    const occurredAt = "2026-09-02T23:30:00+04:00";
    const events = await eventsFrom(bridgeDocument([{ promptRunId: "run", occurredAt }]));
    expect(events[0].occurredAt).toBe(occurredAt);
    // Same instant lands on different local calendar days per viewing zone.
    expect(localDayKey(occurredAt, "Asia/Dubai")).toBe("2026-09-02");
    expect(localDayKey(occurredAt, "Pacific/Kiritimati")).toBe("2026-09-03");
    // A midnight-crossing instant must not be reduced by string slicing.
    const earlyMorning = "2026-09-02T01:30:00+04:00";
    expect(localDayKey(earlyMorning, "America/New_York")).toBe("2026-09-01");
  });

  it("drops malformed timestamps with an explicit warning instead of crashing", async () => {
    const result = await fetchPerformanceActivity(
      respondOk(
        bridgeDocument([
          { promptRunId: "naive", occurredAt: "2026-09-02T10:31:22" },
          { promptRunId: "garbage", occurredAt: "not-a-timestamp" },
          { promptRunId: "missing" },
          { promptRunId: "valid", occurredAt: "2026-09-02T10:31:22Z" },
        ]),
      ),
    );
    expect(result.events.map((event) => event.promptRunId)).toEqual(["valid"]);
    expect(result.warnings).toHaveLength(3);
    expect(result.warnings[0]).toContain("naive");
  });

  it("treats an empty Performance result as empty real data, not fixture fallback", async () => {
    const outcome = await loadActivity(performanceSource, respondOk(bridgeDocument([])));
    expect(outcome.kind).toBe("performance");
    expect(outcome.events).toEqual([]);
    expect(outcome.coverage).toEqual({ totalMatching: 0, complete: true });
    // Definitely not the >500-event development fixture.
    expect(outcome.events).not.toHaveLength(loadFixtureEvents(new Date(2026, 8, 2, 12)).length);
  });

  it("rejects a non-JSON transport body with a typed error", async () => {
    await expect(fetchPerformanceActivity(respond("not json"))).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });

  it("rejects an unsupported inner activity contract version", async () => {
    await expect(
      fetchPerformanceActivity(respondOk({ ...bridgeDocument([]), version: 2 })),
    ).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });

  it("rejects a malformed events field instead of substituting an empty page", async () => {
    await expect(
      fetchPerformanceActivity(respondOk({ ...bridgeDocument([]), events: "nope" })),
    ).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });

  it("keeps the first occurrence of duplicate Prompt Run identities and reports the gap", async () => {
    const result = await fetchPerformanceActivity(
      respondOk(
        bridgeDocument([
          { promptRunId: "dup", occurredAt: "2026-09-02T08:00:00Z" },
          { promptRunId: "dup", occurredAt: "2026-09-02T09:00:00Z" },
        ]),
      ),
    );
    expect(result.events).toHaveLength(1);
    expect(result.events[0].occurredAt).toBe("2026-09-02T08:00:00Z");
    expect(result.warnings).toHaveLength(1);
  });

  it("surfaces partial bounded history truthfully, including the continuation cursor", async () => {
    const result = await fetchPerformanceActivity(
      respondOk(
        bridgeDocument([{ promptRunId: "a", occurredAt: "2026-09-02T08:00:00Z" }], {
          totalMatching: 250,
          complete: false,
          nextCursor: "opaque-token",
        }),
      ),
    );
    expect(result.complete).toBe(false);
    expect(result.totalMatching).toBe(250);
    expect(result.nextCursor).toBe("opaque-token");
  });
});

describe("contract tightening (Execution 03, requirement 13)", () => {
  it("rejects a missing project identity instead of substituting an empty string", async () => {
    const { project: _drop, ...withoutProject } = bridgeDocument([]);
    await expect(fetchPerformanceActivity(respondOk(withoutProject))).rejects.toBeInstanceOf(
      PerformanceInvalidResponseError,
    );
  });

  it("rejects a malformed totalMatching instead of substituting events.length", async () => {
    await expect(
      fetchPerformanceActivity(respondOk({ ...bridgeDocument([]), totalMatching: "many" })),
    ).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });

  it("rejects a malformed complete flag instead of deriving one", async () => {
    await expect(
      fetchPerformanceActivity(respondOk({ ...bridgeDocument([]), complete: "yes" })),
    ).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });

  it("rejects an envelope contractVersion mismatch clearly", async () => {
    await expect(
      fetchPerformanceActivity(respond({ contractVersion: 2, operation: "activity.listPromptRuns", ok: true, result: bridgeDocument([]) })),
    ).rejects.toBeInstanceOf(PerformanceContractVersionError);
  });

  it("rejects an envelope missing 'ok' instead of guessing success", async () => {
    await expect(
      fetchPerformanceActivity(respond({ contractVersion: 1, operation: "activity.listPromptRuns", result: bridgeDocument([]) })),
    ).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });
});

describe("unavailable source", () => {
  it("maps transport failure to PerformanceUnavailableError", async () => {
    await expect(
      fetchPerformanceActivity(() => Promise.reject(new Error("network down"))),
    ).rejects.toBeInstanceOf(PerformanceUnavailableError);
  });

  it("maps a Host BRIDGE_UNAVAILABLE/BRIDGE_TIMEOUT envelope to PerformanceUnavailableError", async () => {
    await expect(
      fetchPerformanceActivity(respond(errorEnvelope("BRIDGE_UNAVAILABLE", "no ledger"), 502)),
    ).rejects.toBeInstanceOf(PerformanceUnavailableError);
    await expect(
      fetchPerformanceActivity(respond(errorEnvelope("BRIDGE_TIMEOUT", "bridge timed out"), 504)),
    ).rejects.toBeInstanceOf(PerformanceUnavailableError);
    await expect(loadActivity(performanceSource, respond(errorEnvelope("BRIDGE_UNAVAILABLE"), 502))).rejects.toBeInstanceOf(
      PerformanceUnavailableError,
    );
  });

  it("maps every other typed Host error code to PerformanceHostError, never a silent success", async () => {
    for (const code of ["INVALID_REQUEST", "UNKNOWN_OPERATION", "BRIDGE_MALFORMED_OUTPUT", "INVALID_CURSOR"]) {
      await expect(fetchPerformanceActivity(respond(errorEnvelope(code), 400))).rejects.toBeInstanceOf(PerformanceHostError);
    }
  });

  it("rejects a non-envelope error body as invalid rather than guessing it means unavailable", async () => {
    // A raw, non-contract 500 (no `ok`/`error` shape) is honestly reported as
    // malformed, not silently mapped onto the "unavailable" UI state — this
    // Host never produces such a body, but defensive parsing must not guess.
    await expect(fetchPerformanceActivity(respond({}, 500))).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });
});

describe("real-source aggregation", () => {
  const realEvents: readonly ActivityEvent[] = [
    { promptRunId: "mon-1", occurredAt: "2026-08-31T09:00:00Z" },
    { promptRunId: "mon-2", occurredAt: "2026-08-31T14:00:00Z" },
    { promptRunId: "mon-3", occurredAt: "2026-08-31T20:00:00Z" },
    { promptRunId: "tue-1", occurredAt: "2026-09-01T10:00:00Z" },
    { promptRunId: "tue-2", occurredAt: "2026-09-01T17:30:00Z" },
    { promptRunId: "tue-3", occurredAt: "2026-09-01T21:00:00Z" },
    { promptRunId: "tue-4", occurredAt: "2026-09-01T23:59:00Z" },
    { promptRunId: "tue-5", occurredAt: "2026-09-01T12:00:00Z" },
    // Wednesday: zero Prompt Runs — must remain a visible empty period.
  ];

  it("aggregates the same real events per day", () => {
    const buckets = aggregateActivity(realEvents, "day", "2026-08-31", "2026-09-02", UTC);
    expect(buckets.map((bucket) => bucket.promptCount)).toEqual([3, 5, 0]);
  });

  it("aggregates the same real events per week", () => {
    const buckets = aggregateActivity(realEvents, "week", "2026-08-31", "2026-09-02", UTC);
    expect(buckets).toHaveLength(1);
    expect(buckets[0].key).toBe("2026-08-31");
    expect(buckets[0].promptCount).toBe(8);
  });

  it("aggregates the same real events per month", () => {
    const buckets = aggregateActivity(realEvents, "month", "2026-08-31", "2026-09-02", UTC);
    expect(buckets).toHaveLength(2);
    expect(buckets[0].promptCount).toBe(3);
    expect(buckets[1].promptCount).toBe(5);
  });

  it("keeps the prompt total invariant across granularity", () => {
    const sum = (buckets: { promptCount: number }[]) =>
      buckets.reduce((total, bucket) => total + bucket.promptCount, 0);
    const range = activityRangeForEvents(realEvents, "2026-09-02", UTC);
    expect(sum(aggregateActivity(realEvents, "day", range.rangeStart, range.rangeEnd, UTC))).toBe(8);
    expect(sum(aggregateActivity(realEvents, "week", range.rangeStart, range.rangeEnd, UTC))).toBe(8);
    expect(sum(aggregateActivity(realEvents, "month", range.rangeStart, range.rangeEnd, UTC))).toBe(8);
  });
});

describe("real time-range behavior", () => {
  it("ends on the injected current day and covers evidence only as far back as it goes", () => {
    const recent: readonly ActivityEvent[] = [
      { promptRunId: "today", occurredAt: "2026-09-02T10:00:00Z" },
    ];
    const range = activityRangeForEvents(recent, "2026-09-02", UTC);
    expect(range.rangeEnd).toBe("2026-09-02");
    expect(range).toEqual(activityRangeForEvents([], "2026-09-02", UTC)); // no fixture-derived bounds

    const older: readonly ActivityEvent[] = [
      ...recent,
      { promptRunId: "old", occurredAt: "2025-02-10T10:00:00Z" },
    ];
    const extended = activityRangeForEvents(older, "2026-09-02", UTC);
    expect(extended.rangeEnd).toBe("2026-09-02");
    expect(extended.rangeStart).toBe("2025-02-10"); // week-aligned left edge (a Monday)
    expect(startOfWeek(extended.rangeStart)).toBe(extended.rangeStart);
    expect(addDays(extended.rangeStart, 7)).toBe("2025-02-17");
  });
});

describe("fixture stays an explicit development mode", () => {
  it("is deterministic and timezone-aware when explicitly used", () => {
    const anchor = new Date(2026, 8, 2, 12, 0, 0);
    expect(loadFixtureEvents(anchor)).toEqual(loadFixtureEvents(anchor));
    expect(fixtureSource.kind).toBe("fixture");
  });

  it("is only selected via an explicit opt-in parameter", () => {
    expect(resolveActivitySource("")).toBe(performanceSource);
    expect(resolveActivitySource("?g=week&sel=2026-08-31")).toBe(performanceSource);
    expect(resolveActivitySource("?source=fixture")).toBe(fixtureSource);
  });

  it("loads deterministically through the unchanged boundary", async () => {
    const outcome = await loadActivity(fixtureSource);
    expect(outcome.kind).toBe("fixture");
    expect(outcome.coverage).toBeNull();
    expect(outcome.warnings).toEqual([]);
    expect(outcome.events.length).toBeGreaterThan(500);
  });

  it("keeps loadActivityEvents as the single swap point, defaulting to real data", async () => {
    expect(defaultActivitySource()).toBe(performanceSource);
    const events = await loadActivityEvents({
      kind: "performance",
      loadEvents: async () =>
        (await fetchPerformanceActivity(respondOk(bridgeDocument([{ promptRunId: "a", occurredAt: "2026-09-02T08:00:00Z" }])))).events,
    });
    expect(events).toEqual([{ promptRunId: "a", occurredAt: "2026-09-02T08:00:00Z" }]);
  });
});
