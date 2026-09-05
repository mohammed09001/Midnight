import type { InsightFeedbackResult, InsightOutcome, ProjectInsight, TerminalCardDocument } from "./types";
import {
  DESKTOP_HOST_URL,
  HOST_CONTRACT_VERSION,
  PerformanceContractVersionError,
  PerformanceHostError,
  PerformanceInvalidResponseError,
  PerformanceUnavailableError,
  type PerformanceFetch,
} from "../activity/performanceSource";

/**
 * Transport + validation for the Desktop Host's `insights.getTerminalCard`
 * and `insights.recordInsightFeedback` operations — mirrors
 * `activity/performanceSource.ts`'s envelope handling and error-class
 * discipline exactly (same versioned `{contractVersion, operation, request}`
 * → `{contractVersion, operation, ok, result|error}` convention, same Host
 * error classes reused rather than duplicated) instead of inventing a
 * parallel transport layer.
 *
 * `decide_terminal_card` (Python) is deliberately single-candidate: this
 * client always resolves to at most ONE current insight, never a list —
 * `TerminalCardDocument.card`/`.insight` are null together exactly as often
 * as they carry a real single insight.
 */

export const GET_TERMINAL_CARD_OPERATION = "insights.getTerminalCard";
export const RECORD_INSIGHT_FEEDBACK_OPERATION = "insights.recordInsightFeedback";

function requireNonEmptyString(record: Record<string, unknown>, field: string, path: string): string {
  const value = record[field];
  if (typeof value !== "string" || !value.trim()) {
    throw new PerformanceInvalidResponseError(`${path}.${field} is missing or empty`);
  }
  return value;
}

function parseInsight(raw: unknown): ProjectInsight {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("insight response insight is not an object");
  }
  const i = raw as Record<string, unknown>;
  const path = "insight response insight";

  const identity = requireNonEmptyString(i, "identity", path);
  const exposureId = requireNonEmptyString(i, "exposureId", path);
  const statement = requireNonEmptyString(i, "statement", path);
  const claimKind = requireNonEmptyString(i, "claimKind", path);
  const uncertainty = requireNonEmptyString(i, "uncertainty", path);
  const whyNow = requireNonEmptyString(i, "whyNow", path);
  const projectConnection = requireNonEmptyString(i, "projectConnection", path);
  const nextLearningAction = requireNonEmptyString(i, "nextLearningAction", path);
  const evidenceBundle = requireNonEmptyString(i, "evidenceBundle", path);
  const channel = requireNonEmptyString(i, "channel", path);
  const outcome = requireNonEmptyString(i, "outcome", path);

  if (i.confidence !== null && typeof i.confidence !== "number") {
    throw new PerformanceInvalidResponseError(`${path}.confidence must be a number or null`);
  }
  if (i.externalConnection !== null && typeof i.externalConnection !== "string") {
    throw new PerformanceInvalidResponseError(`${path}.externalConnection must be a string or null`);
  }
  if (i.lineageReceipt !== null && typeof i.lineageReceipt !== "string") {
    throw new PerformanceInvalidResponseError(`${path}.lineageReceipt must be a string or null`);
  }

  return {
    identity,
    exposureId,
    statement,
    claimKind,
    confidence: (i.confidence as number | null | undefined) ?? null,
    uncertainty,
    whyNow,
    projectConnection,
    nextLearningAction,
    externalConnection: (i.externalConnection as string | null | undefined) ?? null,
    evidenceBundle,
    lineageReceipt: (i.lineageReceipt as string | null | undefined) ?? null,
    channel,
    outcome,
  };
}

/** Validate an already-decoded `insights.getTerminalCard` result. Throws on structural malformation. */
export function parseTerminalCardDocument(raw: unknown): TerminalCardDocument {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("insight response is not an object");
  }
  const document = raw as Record<string, unknown>;
  if (document.version !== 1) {
    throw new PerformanceInvalidResponseError(`unsupported insight contract version: ${String(document.version)}`);
  }
  if (typeof document.project !== "string" || !document.project.trim()) {
    throw new PerformanceInvalidResponseError("insight response is missing its project identity");
  }
  if (typeof document.generatedAt !== "string" || !document.generatedAt.trim()) {
    throw new PerformanceInvalidResponseError("insight response is missing generatedAt");
  }
  if (document.card !== null && typeof document.card !== "string") {
    throw new PerformanceInvalidResponseError("insight response card must be a string or null");
  }
  if (typeof document.reason !== "string" || !document.reason.trim()) {
    throw new PerformanceInvalidResponseError("insight response reason must be a non-empty string");
  }
  if (document.card === null && document.insight !== null) {
    throw new PerformanceInvalidResponseError("insight response insight must be null when card is null");
  }
  if (document.card !== null && document.insight === null) {
    throw new PerformanceInvalidResponseError("insight response insight must not be null when card is present");
  }

  return {
    version: 1,
    project: document.project,
    generatedAt: document.generatedAt,
    card: document.card as string | null,
    reason: document.reason,
    insight: document.insight === null ? null : parseInsight(document.insight),
  };
}

function parseInsightFeedbackResult(raw: unknown): InsightFeedbackResult {
  if (typeof raw !== "object" || raw === null) {
    throw new PerformanceInvalidResponseError("insight feedback response is not an object");
  }
  const document = raw as Record<string, unknown>;
  if (document.version !== 1) {
    throw new PerformanceInvalidResponseError(`unsupported insight feedback contract version: ${String(document.version)}`);
  }
  if (typeof document.project !== "string" || !document.project.trim()) {
    throw new PerformanceInvalidResponseError("insight feedback response is missing its project identity");
  }
  if (document.recorded !== true) {
    throw new PerformanceInvalidResponseError("insight feedback response recorded must be true");
  }
  if (typeof document.outcome !== "string" || !document.outcome.trim()) {
    throw new PerformanceInvalidResponseError("insight feedback response outcome is missing");
  }
  return { version: 1, project: document.project, recorded: true, outcome: document.outcome };
}

/** Map a Host-reported error code to the exception class its message deserves. */
function toInsightHostError(code: unknown, message: unknown): Error {
  const safeCode = typeof code === "string" ? code : "UNKNOWN";
  const safeMessage = typeof message === "string" && message.trim() ? message : "Desktop Host reported an error";
  if (safeCode === "BRIDGE_UNAVAILABLE" || safeCode === "BRIDGE_TIMEOUT") {
    return new PerformanceUnavailableError(safeMessage);
  }
  return new PerformanceHostError(safeCode, safeMessage);
}

function parseHostEnvelope<T>(raw: unknown, parseResult: (result: unknown) => T): T {
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
    throw toInsightHostError(error?.code, error?.message);
  }
  if (envelope.ok !== true) {
    throw new PerformanceInvalidResponseError("Desktop Host response envelope is missing 'ok'");
  }
  return parseResult(envelope.result);
}

async function postToHost(
  operation: string,
  request: Record<string, unknown>,
  fetchImpl: PerformanceFetch,
  url: string,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contractVersion: HOST_CONTRACT_VERSION, operation, request }),
    });
  } catch (cause) {
    throw new PerformanceUnavailableError(cause instanceof Error ? cause.message : String(cause));
  }
  try {
    return await response.json();
  } catch {
    throw new PerformanceInvalidResponseError("Desktop Host response is not valid JSON");
  }
}

/**
 * `userPull: true` maps to the Host's `--user-pull` bridge flag, which in
 * turn maps to `ExposureChannel.USER_PULL` in the Python pipeline — "user
 * pull always outranks proactive push." The desktop surface only ever calls
 * this from a deliberate visit to the Insights view (never a background
 * poll), so this is always a real user pull, not a caller-supplied option.
 */
export async function fetchTerminalCard(
  fetchImpl: PerformanceFetch = fetch,
  url: string = DESKTOP_HOST_URL,
): Promise<TerminalCardDocument> {
  const raw = await postToHost(GET_TERMINAL_CARD_OPERATION, { userPull: true }, fetchImpl, url);
  return parseHostEnvelope(raw, parseTerminalCardDocument);
}

export async function recordInsightFeedback(
  exposureId: string,
  outcome: InsightOutcome,
  fetchImpl: PerformanceFetch = fetch,
  url: string = DESKTOP_HOST_URL,
): Promise<InsightFeedbackResult> {
  const raw = await postToHost(RECORD_INSIGHT_FEEDBACK_OPERATION, { exposureId, outcome }, fetchImpl, url);
  return parseHostEnvelope(raw, parseInsightFeedbackResult);
}
