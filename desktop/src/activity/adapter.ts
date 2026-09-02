import type { ActivityEvent } from "./types";
import { loadFixtureEvents } from "./fixture";
import {
  fetchPerformanceActivity,
  type PerformanceFetch,
} from "./performanceSource";

export const ACTIVITY_DATA_VERSION = 1;

/**
 * Data boundary between Midnight Desktop and its evidence sources.
 *
 * Execution 02 binds this boundary to real Performance Prompt Run evidence
 * through `performanceSource`; the deterministic fixture remains available
 * exclusively for tests, isolated development, and visual QA via an explicit
 * opt-in (`?source=fixture`) — never as a silent stand-in for real history.
 */
export interface ActivityDataSource {
  readonly kind: "fixture" | "performance";
  loadEvents(): Promise<readonly ActivityEvent[]>;
}

export const fixtureSource: ActivityDataSource = {
  kind: "fixture",
  loadEvents: async () => loadFixtureEvents(),
};

export const performanceSource: ActivityDataSource = {
  kind: "performance",
  loadEvents: async () => (await fetchPerformanceActivity()).events,
};

/** Production default: real Performance evidence. */
export function defaultActivitySource(): ActivityDataSource {
  return performanceSource;
}

/**
 * Fixture mode is an explicit development/QA choice, never a fallback:
 * only a literal `?source=fixture` selects it; anything else reads
 * Performance and may truthfully fail or be empty.
 */
export function resolveActivitySource(search: string): ActivityDataSource {
  return new URLSearchParams(search).get("source") === "fixture" ? fixtureSource : defaultActivitySource();
}

export interface ActivityCoverage {
  readonly totalMatching: number;
  readonly complete: boolean;
}

export interface ActivityLoadResult {
  readonly kind: ActivityDataSource["kind"];
  readonly events: readonly ActivityEvent[];
  /** Performance-only bounded-history truth; null for local sources. */
  readonly coverage: ActivityCoverage | null;
  /** Reported evidence gaps (malformed/duplicate records dropped upstream). */
  readonly warnings: readonly string[];
}

export async function loadActivity(
  source: ActivityDataSource,
  fetchImpl: PerformanceFetch = fetch,
): Promise<ActivityLoadResult> {
  if (source.kind !== "performance") {
    return { kind: source.kind, events: await source.loadEvents(), coverage: null, warnings: [] };
  }
  // Unavailable and invalid-contract failures both propagate as typed errors;
  // the caller must render a truthful state, never a fixture fallback.
  const result = await fetchPerformanceActivity(fetchImpl);
  return {
    kind: "performance",
    events: result.events,
    coverage: { totalMatching: result.totalMatching, complete: result.complete },
    warnings: result.warnings,
  };
}

/** Single swap point (Execution 01 signature, now defaulting to real data). */
export function loadActivityEvents(
  source: ActivityDataSource = defaultActivitySource(),
): Promise<readonly ActivityEvent[]> {
  return source.loadEvents();
}
