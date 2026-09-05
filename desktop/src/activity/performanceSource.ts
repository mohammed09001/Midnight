import type { ActivityEvent } from "./types";

/**
 * Transport + validation for the Midnight Desktop Host's
 * `activity.listPromptRuns` operation.
 *
 * The Desktop only learns WHEN Prompt Runs occurred: `promptRunId` and the
 * timezone-aware `occurredAt` instant. No prompt content, output, code,
 * commands, tokens, or model details are requested, accepted, or stored here.
 *
 * Execution 03: the Desktop Host (`desktop/host/`) — not Vite — is the
 * product authority. Requests go through a versioned envelope
 * (`{contractVersion, operation, request}` → `{contractVersion, operation,
 * ok, result|error}`, mirroring `Memory/docs/CONTRACTS.md`'s convention),
 * POSTed to the Host's single dispatch endpoint via the Vite dev/preview
 * proxy at `PROXY_PATH`.
 *
 * Contract tightening (Execution 03, requirement 13): a missing `project`, a
 * malformed `totalMatching`/`complete`, or an unsupported `contractVersion`
 * are all hard failures — never silently substituted with a fabricated
 * default. Per-event malformed rows still degrade to `warnings` (dropping
 * one bad row is honest; fabricating a whole-page default is not).
 *
 * Timezone discipline (Execution 02): `occurredAt` must carry an explicit
 * UTC offset (or `Z`). Naive timestamps are rejected as malformed evidence —
 * bucketing a naive instant against the viewer's local calendar would be a
 * silent fabrication, never a conversion.
 */

export const PERFORMANCE_ACTIVITY_VERSION = 1;
export const HOST_CONTRACT_VERSION = 1;
export const ACTIVITY_OPERATION = "activity.listPromptRuns";
export const DESKTOP_HOST_URL = "/api/desktop-host";

export type PerformanceFetch = (url: string, init?: RequestInit) => Promise<Response>;

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

/** The Host envelope's `contractVersion` did not match what this client speaks. */
export class PerformanceContractVersionError extends PerformanceInvalidResponseError {
  constructor(message: string) {
    super(message);
    this.name = "PerformanceContractVersionError";
  }
}

/** The Host returned a well-formed `ok:false` envelope with a typed error. */
export class PerformanceHostError extends PerformanceInvalidResponseError {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "PerformanceHostError";
    this.code = code;
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
  /** Opaque continuation token for the page after this one; null when `complete`. */
  readonly nextCursor: string | null;
}

const TIMEZONE_AWARE_INSTANT = /(?:Z|[+-]\d{2}:\d{2})$/i;

function isTimezoneAwareInstant(value: unknown): value is string {
  return (
    typeof value === "string" &&
    TIMEZONE_AWARE_INSTANT.test(value) &&
    Number.isFinite(new Date(value).getTime())
  );
}

/** Validate an already-decoded `activity.listPromptRuns` result. Throws on structural malformation. */
export function parseActivityDocument(raw: unknown): PerformanceActivityResult {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("activity response is not an object");
  }
  const document = raw as Record<string, unknown>;
  if (document.version !== PERFORMANCE_ACTIVITY_VERSION) {
    throw new PerformanceInvalidResponseError(`unsupported activity contract version: ${String(document.version)}`);
  }
  if (typeof document.project !== "string" || !document.project.trim()) {
    throw new PerformanceInvalidResponseError("activity response is missing its project identity");
  }
  if (!Array.isArray(document.events)) {
    throw new PerformanceInvalidResponseError("activity response events must be an array");
  }
  if (typeof document.totalMatching !== "number" || !Number.isFinite(document.totalMatching)) {
    throw new PerformanceInvalidResponseError("activity response totalMatching must be a finite number");
  }
  if (typeof document.complete !== "boolean") {
    throw new PerformanceInvalidResponseError("activity response complete must be a boolean");
  }
  if (document.cursor !== undefined && document.cursor !== null && typeof document.cursor !== "string") {
    throw new PerformanceInvalidResponseError("activity response cursor must be a string or null");
  }
  if (document.nextCursor !== undefined && document.nextCursor !== null && typeof document.nextCursor !== "string") {
    throw new PerformanceInvalidResponseError("activity response nextCursor must be a string or null");
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

  return {
    project: document.project,
    events,
    totalMatching: document.totalMatching,
    complete: document.complete,
    warnings,
    nextCursor: (document.nextCursor as string | null | undefined) ?? null,
  };
}

/** Map a Host-reported error code to the exception class its message deserves. */
function toHostError(code: unknown, message: unknown): Error {
  const safeCode = typeof code === "string" ? code : "UNKNOWN";
  const safeMessage = typeof message === "string" && message.trim() ? message : "Desktop Host reported an error";
  if (safeCode === "BRIDGE_UNAVAILABLE" || safeCode === "BRIDGE_TIMEOUT") {
    return new PerformanceUnavailableError(safeMessage);
  }
  return new PerformanceHostError(safeCode, safeMessage);
}

function parseHostEnvelope(raw: unknown): PerformanceActivityResult {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("Desktop Host response is not an object");
  }
  const envelope = raw as Record<string, unknown>;
  if (envelope.contractVersion !== HOST_CONTRACT_VERSION) {
    throw new PerformanceContractVersionError(
      `unsupported Desktop Host contractVersion: ${String(envelope.contractVersion)}`,
    );
  }
  if (envelope.ok === false) {
    const error = envelope.error as Record<string, unknown> | undefined;
    throw toHostError(error?.code, error?.message);
  }
  if (envelope.ok !== true) {
    throw new PerformanceInvalidResponseError("Desktop Host response envelope is missing 'ok'");
  }
  return parseActivityDocument(envelope.result);
}

export async function fetchPerformanceActivity(
  fetchImpl: PerformanceFetch = fetch,
  url: string = DESKTOP_HOST_URL,
): Promise<PerformanceActivityResult> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contractVersion: HOST_CONTRACT_VERSION, operation: ACTIVITY_OPERATION, request: {} }),
    });
  } catch (cause) {
    throw new PerformanceUnavailableError(cause instanceof Error ? cause.message : String(cause));
  }
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new PerformanceInvalidResponseError("Desktop Host response is not valid JSON");
  }
  return parseHostEnvelope(raw);
}
