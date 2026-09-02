import type { ActivityEvent } from "./types";
import { loadFixtureEvents } from "./fixture";

export const ACTIVITY_DATA_VERSION = 1;

/**
 * Data boundary between Midnight Desktop and its evidence sources.
 *
 * Execution 01 serves a deterministic local fixture (never presented as real
 * Performance data). A later execution binds this boundary to a Performance
 * read path (e.g. `performance.query_evidence` over PROMPT_RUNS) without the
 * Activity Map or its aggregation logic changing.
 */
export interface ActivityDataSource {
  readonly kind: "fixture" | "performance";
  loadEvents(): Promise<readonly ActivityEvent[]>;
}

export const fixtureSource: ActivityDataSource = {
  kind: "fixture",
  loadEvents: async () => loadFixtureEvents(),
};

/** Single swap point for the future Performance source. */
export function loadActivityEvents(
  source: ActivityDataSource = fixtureSource,
): Promise<readonly ActivityEvent[]> {
  return source.loadEvents();
}
