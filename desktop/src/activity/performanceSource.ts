import type { ActivityEvent } from "./types";

/**
 * Transport + validation for the Performance Prompt Run activity document.
 *
 * The Desktop only learns WHEN Prompt Runs occurred: `promptRunId` and the
 * timezone-aware `occurredAt` instant. No prompt content, output, code,
 * commands, tokens, or model details are requested, accepted, or stored here.
 *
 * Contract (Performance `desktop_bridge.py`):
 *   { version: 1, project, events: [{ promptRunId, occurredAt }],
 *     totalMatching, limit, complete }
 *
 * Timezone discipline (Execution 02): `occurredAt` must carry an explicit
 * UTC offset (or `Z`). Naive timestamps are rejected as malformed evidence —
 * bucketing a naive instant against the viewer's local calendar would be a
 * silent fabrication, never a conversion.
 */

export const PERFORMANCE_ACTIVITY_VERSION = 1;
export const PERFORMANCE_ACTIVITY_URL = "/api/activity/prompt-runs";

export type PerformanceFetch = (url: string) => Promise<Response>;

export class PerformanceUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PerformanceUnavailableError";
  }
}

export class PerformanceInvalidResponseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PerformanceInvalidResponseError";
  }
}

export interface PerformanceActivityResult {
  readonly project: string;
  readonly events: readonly ActivityEvent[];
  /** Total Prompt Runs matching in Performance, possibly beyond this bounded page. */
  readonly totalMatching: number;
  /** False when the bounded page does not cover the full matching history. */
  readonly complete: boolean;
  /** Explicitly reported evidence gaps — malformed records are dropped, never silently ignored. */
  readonly warnings: readonly string[];
}

const TIMEZONE_AWARE_INSTANT = /(?:Z|[+-]\d{2}:\d{2})$/i;

function isTimezoneAwareInstant(value: unknown): value is string {
  return (
    typeof value === "string" &&
    TIMEZONE_AWARE_INSTANT.test(value) &&
    Number.isFinite(new Date(value).getTime())
  );
}

/** Validate an already-decoded bridge document. Throws on structural malformation. */
export function parseActivityDocument(raw: unknown): PerformanceActivityResult {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("activity response is not an object");
  }
  const document = raw as Record<string, unknown>;
  if (document.version !== PERFORMANCE_ACTIVITY_VERSION) {
    throw new PerformanceInvalidResponseError(`unsupported activity contract version: ${String(document.version)}`);
  }
  if (!Array.isArray(document.events)) {
    throw new PerformanceInvalidResponseError("activity response events must be an array");
  }

  const warnings: string[] = [];
  const seen = new Set<string>();
  const events: ActivityEvent[] = [];
  document.events.forEach((entry, index) => {
    if (typeof entry !== "object" || entry === null) {
      warnings.push(`events[${index}]: not an object; dropped`);
      return;
    }
    const event = entry as Record<string, unknown>;
    const promptRunId = event.promptRunId;
    if (typeof promptRunId !== "string" || !promptRunId.trim()) {
      warnings.push(`events[${index}]: missing promptRunId; dropped`);
      return;
    }
    if (!isTimezoneAwareInstant(event.occurredAt)) {
      warnings.push(`events[${index}] (${promptRunId}): missing or non-timezone-aware timestamp; dropped`);
      return;
    }
    if (seen.has(promptRunId)) {
      warnings.push(`events[${index}] (${promptRunId}): duplicate Prompt Run identity; first occurrence kept`);
      return;
    }
    seen.add(promptRunId);
    events.push({ promptRunId, occurredAt: event.occurredAt });
  });

  const totalMatching =
    typeof document.totalMatching === "number" && Number.isFinite(document.totalMatching)
      ? document.totalMatching
      : events.length;
  const complete = document.complete === true ? true : events.length >= totalMatching;
  const project = typeof document.project === "string" ? document.project : "";

  return { project, events, totalMatching, complete, warnings };
}

export async function fetchPerformanceActivity(
  fetchImpl: PerformanceFetch = fetch,
  url: string = PERFORMANCE_ACTIVITY_URL,
): Promise<PerformanceActivityResult> {
  let response: Response;
  try {
    response = await fetchImpl(url);
  } catch (cause) {
    throw new PerformanceUnavailableError(cause instanceof Error ? cause.message : String(cause));
  }
  if (!response.ok) {
    throw new PerformanceUnavailableError(`Performance activity bridge responded ${response.status}`);
  }
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new PerformanceInvalidResponseError("activity response is not valid JSON");
  }
  return parseActivityDocument(raw);
}
