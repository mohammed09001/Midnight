import { describe, expect, it } from "vitest";
import {
  GET_TERMINAL_CARD_OPERATION,
  RECORD_INSIGHT_FEEDBACK_OPERATION,
  fetchTerminalCard,
  parseTerminalCardDocument,
  recordInsightFeedback,
} from "../../src/insights/insightSource";
import {
  DESKTOP_HOST_URL,
  PerformanceContractVersionError,
  PerformanceHostError,
  PerformanceInvalidResponseError,
  PerformanceUnavailableError,
  type PerformanceFetch,
} from "../../src/activity/performanceSource";

function baseInsight(overrides: Record<string, unknown> = {}) {
  return {
    identity: "mp:v1:project_insight:aaa",
    exposureId: "mp:v1:exposure:bbb",
    statement: "Three files changed together five times without a shared test.",
    claimKind: "pattern",
    confidence: 0.62,
    uncertainty: "medium — small sample size",
    whyNow: "This co-change pattern just recurred for the third time this week.",
    projectConnection: "Touches the same billing module you edited yesterday.",
    nextLearningAction: "Add a regression test covering the shared code path.",
    externalConnection: null,
    evidenceBundle: "mp:v1:evidence_bundle:ccc",
    lineageReceipt: "mp:v1:lineage_receipt:ddd",
    channel: "user_pull",
    outcome: "pending",
    ...overrides,
  };
}

function baseDocument(overrides: Record<string, unknown> = {}) {
  return {
    version: 1,
    project: "mp:v1:project:aaaaaaaa-0000-5000-8000-000000000000",
    generatedAt: "2026-09-05T10:00:00Z",
    card: "Recurring co-change without a shared test",
    reason: "a real signal cleared the relevance/novelty gate",
    insight: baseInsight(),
    ...overrides,
  };
}

function emptyDocument(overrides: Record<string, unknown> = {}) {
  return {
    version: 1,
    project: "mp:v1:project:aaaaaaaa-0000-5000-8000-000000000000",
    generatedAt: "2026-09-05T10:00:00Z",
    card: null,
    reason: "no signal cleared the relevance/novelty gate this pull",
    insight: null,
    ...overrides,
  };
}

function successEnvelope(operation: string, result: unknown) {
  return { contractVersion: 1, operation, ok: true, result };
}

function errorEnvelope(operation: string, code: string, message = "Desktop Host error") {
  return { contractVersion: 1, operation, ok: false, error: { code, message } };
}

function respond(body: unknown, status = 200): PerformanceFetch {
  return () => Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe("parseTerminalCardDocument", () => {
  it("accepts a well-formed populated card", () => {
    const document = parseTerminalCardDocument(baseDocument());
    expect(document.card).toBe("Recurring co-change without a shared test");
    expect(document.insight?.exposureId).toBe("mp:v1:exposure:bbb");
    expect(document.insight?.confidence).toBe(0.62);
  });

  it("accepts a well-formed empty state (card and insight both null)", () => {
    const document = parseTerminalCardDocument(emptyDocument());
    expect(document.card).toBeNull();
    expect(document.insight).toBeNull();
    expect(document.reason).toBe("no signal cleared the relevance/novelty gate this pull");
  });

  it("accepts a null confidence on the insight", () => {
    const document = parseTerminalCardDocument(baseDocument({ insight: baseInsight({ confidence: null }) }));
    expect(document.insight?.confidence).toBeNull();
  });

  it("throws when card is present but insight is null", () => {
    expect(() => parseTerminalCardDocument(baseDocument({ insight: null }))).toThrow(PerformanceInvalidResponseError);
  });

  it("throws when card is null but insight is present", () => {
    expect(() => parseTerminalCardDocument(emptyDocument({ insight: baseInsight() }))).toThrow(
      PerformanceInvalidResponseError,
    );
  });

  it("rejects an unsupported contract version", () => {
    expect(() => parseTerminalCardDocument(baseDocument({ version: 2 }))).toThrow(PerformanceInvalidResponseError);
  });

  it("rejects a missing reason", () => {
    const malformed = baseDocument();
    delete (malformed as Record<string, unknown>).reason;
    expect(() => parseTerminalCardDocument(malformed)).toThrow(PerformanceInvalidResponseError);
  });

  it("rejects a missing project identity", () => {
    const malformed = baseDocument();
    delete (malformed as Record<string, unknown>).project;
    expect(() => parseTerminalCardDocument(malformed)).toThrow(PerformanceInvalidResponseError);
  });

  it("rejects an insight missing a required field", () => {
    const insight = baseInsight() as Record<string, unknown>;
    delete insight.statement;
    expect(() => parseTerminalCardDocument(baseDocument({ insight }))).toThrow(PerformanceInvalidResponseError);
  });

  it("rejects a malformed confidence type on the insight", () => {
    expect(() => parseTerminalCardDocument(baseDocument({ insight: baseInsight({ confidence: "high" }) }))).toThrow(
      PerformanceInvalidResponseError,
    );
  });
});

describe("fetchTerminalCard", () => {
  it("sends the userPull flag in the request body", async () => {
    let capturedBody: unknown;
    const fetchImpl: PerformanceFetch = (url, init) => {
      expect(url).toBe(DESKTOP_HOST_URL);
      expect(init?.method).toBe("POST");
      capturedBody = JSON.parse(String(init?.body));
      return Promise.resolve(
        new Response(JSON.stringify(successEnvelope(GET_TERMINAL_CARD_OPERATION, baseDocument())), { status: 200 }),
      );
    };
    await fetchTerminalCard(fetchImpl);
    expect(capturedBody).toEqual({
      contractVersion: 1,
      operation: GET_TERMINAL_CARD_OPERATION,
      request: { userPull: true },
    });
  });

  it("resolves the parsed document on a successful envelope", async () => {
    const document = await fetchTerminalCard(respond(successEnvelope(GET_TERMINAL_CARD_OPERATION, baseDocument())));
    expect(document.insight?.statement).toContain("changed together");
  });

  it("resolves an empty document truthfully rather than throwing", async () => {
    const document = await fetchTerminalCard(respond(successEnvelope(GET_TERMINAL_CARD_OPERATION, emptyDocument())));
    expect(document.card).toBeNull();
  });

  it("maps a Host BRIDGE_UNAVAILABLE/BRIDGE_TIMEOUT envelope to PerformanceUnavailableError", async () => {
    await expect(
      fetchTerminalCard(respond(errorEnvelope(GET_TERMINAL_CARD_OPERATION, "BRIDGE_UNAVAILABLE"), 502)),
    ).rejects.toBeInstanceOf(PerformanceUnavailableError);
    await expect(
      fetchTerminalCard(respond(errorEnvelope(GET_TERMINAL_CARD_OPERATION, "BRIDGE_TIMEOUT"), 504)),
    ).rejects.toBeInstanceOf(PerformanceUnavailableError);
  });

  it("maps every other typed Host error code to PerformanceHostError", async () => {
    await expect(
      fetchTerminalCard(respond(errorEnvelope(GET_TERMINAL_CARD_OPERATION, "INVALID_REQUEST"), 400)),
    ).rejects.toBeInstanceOf(PerformanceHostError);
  });

  it("rejects an envelope contractVersion mismatch", async () => {
    await expect(
      fetchTerminalCard(
        respond({ contractVersion: 2, operation: GET_TERMINAL_CARD_OPERATION, ok: true, result: baseDocument() }),
      ),
    ).rejects.toBeInstanceOf(PerformanceContractVersionError);
  });

  it("maps a transport failure to PerformanceUnavailableError", async () => {
    await expect(fetchTerminalCard(() => Promise.reject(new Error("network down")))).rejects.toBeInstanceOf(
      PerformanceUnavailableError,
    );
  });

  it("rejects a non-JSON transport body with a typed error", async () => {
    await expect(fetchTerminalCard(respond("not json"))).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });
});

describe("recordInsightFeedback", () => {
  function feedbackResult(outcome: string) {
    return { version: 1, project: "mp:v1:project:aaa", recorded: true, outcome };
  }

  it("sends exposureId and outcome in the request body", async () => {
    let capturedBody: unknown;
    const fetchImpl: PerformanceFetch = (url, init) => {
      expect(url).toBe(DESKTOP_HOST_URL);
      capturedBody = JSON.parse(String(init?.body));
      return Promise.resolve(
        new Response(JSON.stringify(successEnvelope(RECORD_INSIGHT_FEEDBACK_OPERATION, feedbackResult("saved"))), {
          status: 200,
        }),
      );
    };
    await recordInsightFeedback("mp:v1:exposure:bbb", "saved", fetchImpl);
    expect(capturedBody).toEqual({
      contractVersion: 1,
      operation: RECORD_INSIGHT_FEEDBACK_OPERATION,
      request: { exposureId: "mp:v1:exposure:bbb", outcome: "saved" },
    });
  });

  it("resolves the recorded outcome on success", async () => {
    const result = await recordInsightFeedback(
      "mp:v1:exposure:bbb",
      "opened",
      respond(successEnvelope(RECORD_INSIGHT_FEEDBACK_OPERATION, feedbackResult("opened"))),
    );
    expect(result.recorded).toBe(true);
    expect(result.outcome).toBe("opened");
  });

  it("rejects a recorded:false response as malformed rather than accepting it", async () => {
    await expect(
      recordInsightFeedback(
        "mp:v1:exposure:bbb",
        "dismissed",
        respond(
          successEnvelope(RECORD_INSIGHT_FEEDBACK_OPERATION, { version: 1, project: "p", recorded: false, outcome: "dismissed" }),
        ),
      ),
    ).rejects.toBeInstanceOf(PerformanceInvalidResponseError);
  });

  it("maps a Host INVALID_REQUEST error to PerformanceHostError", async () => {
    await expect(
      recordInsightFeedback(
        "unknown",
        "dismissed",
        respond(errorEnvelope(RECORD_INSIGHT_FEEDBACK_OPERATION, "INVALID_REQUEST"), 400),
      ),
    ).rejects.toBeInstanceOf(PerformanceHostError);
  });

  it("maps a Host BRIDGE_UNAVAILABLE error to PerformanceUnavailableError", async () => {
    await expect(
      recordInsightFeedback(
        "mp:v1:exposure:bbb",
        "opened",
        respond(errorEnvelope(RECORD_INSIGHT_FEEDBACK_OPERATION, "BRIDGE_UNAVAILABLE"), 502),
      ),
    ).rejects.toBeInstanceOf(PerformanceUnavailableError);
  });
});
