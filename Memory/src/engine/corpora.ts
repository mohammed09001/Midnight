/**
 * Frozen Memory qualification corpora (Task 42, Phase VIII).
 *
 * A DETERMINISTIC, VERSIONED corpus of Memory records that exercises every
 * qualification area — current facts, historical facts (expired windows,
 * archives, supersession chains), contradictions, duplicates, privacy
 * restrictions, and provenance variety — together with a verifier that
 * freezes the engine's EXPECTED outcomes into a stable, subject-keyed report.
 *
 * Determinism contract:
 * - The corpus content (subjects, contents, windows, evidence, actors,
 *   confidences) is frozen in code at `QUALIFICATION_CORPUS_VERSION`.
 * - Materialization goes ONLY through the public MemoryEngine API (canonical
 *   owners; no direct store writes — the store reference is used solely for
 *   the engine's own event-append plumbing), is replay-safe via Task-7
 *   idempotency keys and a corpus marker record, and pins every temporal
 *   filter to corpus constants (`CORPUS_AT`) or to instants READ BACK from
 *   the store (as-of checks) — never to wall-clock build time.
 * - The verification report contains NO volatile fields (no record ids, no
 *   build timestamps): two independent builds of the same corpus version
 *   produce identical reports, so qualification results are comparable
 *   across runs, machines, and restarts.
 *
 * Failure behavior: the builder refuses to materialize on a non-conforming
 * engine (one that accepts secret-class material); the verifier is read-only
 * and reports failed checks with stable names instead of throwing.
 *
 * Backend/terminal-first, agent-neutral, game-independent: the whole corpus
 * works from the CLI (`corpus build|verify`) without any external provider,
 * MCP host, sibling engine, or game. The embedding area is optional and uses
 * only the built-in deterministic provider when enabled.
 */
import type { MemoryEngine } from "./memoryEngine.ts";
import type { MemoryStore } from "./store.ts";
import { localHashProvider } from "./embeddings.ts";
import { PrivacyViolationError } from "../contracts/errors.ts";
import type { MemoryRecord } from "../contracts/types.ts";

export const QUALIFICATION_CORPUS_VERSION = "1.0.0" as const;

/** Stable project key — the corpus identity contract. */
export const QUALIFICATION_CORPUS_SCOPE_KEY = "qualification-v1" as const;

/** Pinned "now" for current-view checks: after every closed window. */
export const CORPUS_AT = "2026-07-01T00:00:00.000Z" as const;

const MARKER_SUBJECT = "Qualification corpus marker";
const AUTH_CONTENT_V1 = "Auth provider is Auth0 with RS256";
const AUTH_CONTENT_V2 = "Auth provider is Clerk with RS256";

const HUMAN = { kind: "human" as const, name: "kim" };
const TOOL = { kind: "tool" as const, name: "sync-bot" };

/**
 * Strictly advance wall-clock past `fromMs` (bounded spin of a few ms) so the
 * supersession chain's capture times strictly increase — the frozen as-of
 * expectation needs v2.createdAt > v1.createdAt even within one millisecond
 * of ULID monotonicity.
 */
function advancePast(fromMs: number): void {
  const deadline = fromMs + 2;
  while (Date.now() <= deadline) {
    /* bounded spin */
  }
}

export interface QualificationCheck {
  /** Stable check name — the frozen expectation identity. */
  name: string;
  pass: boolean;
  /** Deterministic detail: subjects and counts only (never ids/timestamps). */
  detail: string;
}

export interface QualificationReport {
  corpusVersion: typeof QUALIFICATION_CORPUS_VERSION;
  contractVersion: string;
  scopeKey: typeof QUALIFICATION_CORPUS_SCOPE_KEY;
  embeddingsChecked: boolean;
  checks: QualificationCheck[];
  passed: boolean;
}

export interface CorpusBuildResult {
  corpusVersion: typeof QUALIFICATION_CORPUS_VERSION;
  scopeKey: typeof QUALIFICATION_CORPUS_SCOPE_KEY;
  /** False when the corpus was already materialized (replay-safe no-op). */
  built: boolean;
  recordCount: number;
  embeddings: { recordCount: number; skippedPrivacy: number } | null;
}

export interface CorpusOptions {
  /** Build/verify the optional embedding area with the built-in deterministic provider. Default true. */
  includeEmbeddings?: boolean;
}

function check(name: string, pass: boolean, detail: string): QualificationCheck {
  return { name, pass, detail };
}

function subjectsOf(records: MemoryRecord[]): string[] {
  return records.map((r) => r.subject).sort();
}

// ---- frozen corpus content ---------------------------------------------------

const CONTENT = {
  rateLimit: "API gateway allows 120 requests per minute per project",
  backoff: "Retry policy uses exponential backoff with jitter",
  deployRunbook: "Deploy window is Tuesday 06:00-08:00 UTC",
  deployChange: "Deploy window moved to Thursday 06:00-08:00 UTC since change 42",
  deployNear: "Deploy window is Tuesday 06:00-07:30 UTC",
  sessions100: "Maximum 100 concurrent sessions per project",
  sessions250: "Maximum 250 concurrent sessions per project",
  onboarding: "Onboarding flow completes in four guided steps",
  cacheStrategy: "Read-through cache with 60 second TTL is sufficient",
  hotPath: "The ranking hot path is bounded by the lexical index probe",
  maintenance: "Maintenance window was 2026-06-28 02:00-04:00 UTC",
  regionA: "Primary deployment region is eu-central-1",
  regionB: "Primary deployment region is eu-west-1",
  legacyCache: "Legacy memcached cluster remains read-only",
  rotation: "API key rotation runs on the first Monday of each quarter",
} as const;

function recordInput(
  subject: string,
  content: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    scope: QUALIFICATION_CORPUS_SCOPE_KEY,
    kind: "fact" as const,
    subject,
    content,
    actor: HUMAN,
    method: "asserted",
    epistemicClass: "observed" as const,
    confidence: 0.9,
    sourceKind: "user_note" as const,
    evidenceRefs: [{ engine: "external" as const, ref: `note:${subject.toLowerCase().replace(/\s+/g, "-")}` }],
    ...overrides,
  };
}

function idempotencyKeyFor(subject: string): string {
  return `${QUALIFICATION_CORPUS_SCOPE_KEY}:${subject.toLowerCase().replace(/\s+/g, "-")}`;
}

// ---- builder -------------------------------------------------------------------

/**
 * Materialize the frozen corpus through the public engine API. Replay-safe:
 * every direct record write carries a deterministic idempotency key, the
 * marker record gates re-entry, and non-idempotent lifecycle steps
 * (supersede/resolve/archive) check current state before acting.
 */
export function buildQualificationCorpusImpl(
  engine: MemoryEngine,
  store: MemoryStore,
  options: CorpusOptions = {},
): CorpusBuildResult {
  engine.createScope(QUALIFICATION_CORPUS_SCOPE_KEY, "Qualification Corpus v1");

  const marker = engine
    .searchRecords({ scope: QUALIFICATION_CORPUS_SCOPE_KEY, exactSubject: MARKER_SUBJECT })
    .find((r) => r.status !== "deleted");
  if (marker !== undefined) {
    const records = engine.searchRecords({ scope: QUALIFICATION_CORPUS_SCOPE_KEY, status: "all" });
    return {
      corpusVersion: QUALIFICATION_CORPUS_VERSION,
      scopeKey: QUALIFICATION_CORPUS_SCOPE_KEY,
      built: false,
      recordCount: records.length,
      embeddings: null,
    };
  }

  // ---- current facts ----
  engine.addRecord(recordInput("Rate limit", CONTENT.rateLimit, {
    sourceKind: "user_decision",
    privacyClass: "internal",
    idempotencyKey: idempotencyKeyFor("Rate limit"),
  }));
  engine.addRecord(recordInput("Retry backoff", CONTENT.backoff, {
    confidence: 0.85,
    privacyClass: "public",
    relationHints: [{ type: "applies_to" as const, target: "entity:component:api-gateway" }],
    idempotencyKey: idempotencyKeyFor("Retry backoff"),
  }));

  // ---- duplicates: exact pair + one distinct corroborating record ----
  const deployRecord = (idSuffix: string, content: string, ref: string): MemoryRecord =>
    engine.addRecord(recordInput("Deploy window", content, {
      actor: TOOL,
      method: "synced",
      sourceKind: "repository_evidence",
      confidence: 0.8,
      privacyClass: "internal",
      evidenceRefs: [{ engine: "repository_sync" as const, ref }],
      idempotencyKey: idempotencyKeyFor(`Deploy window ${idSuffix}`),
    }));
  deployRecord("a", CONTENT.deployRunbook, "deploy:runbook");
  deployRecord("b", CONTENT.deployRunbook, "deploy:runbook");
  deployRecord("c", CONTENT.deployChange, "deploy:change-42");

  // ---- contradictions: detected pair -> registered -> resolved (supersede) ----
  const sessionsA = engine.addRecord(recordInput("Max concurrent sessions", CONTENT.sessions100, {
    kind: "decision" as const,
    method: "decided",
    sourceKind: "user_decision",
    idempotencyKey: idempotencyKeyFor("Max concurrent sessions a"),
  }));
  const sessionsB = engine.addRecord(recordInput("Max concurrent sessions", CONTENT.sessions250, {
    kind: "decision" as const,
    method: "decided",
    sourceKind: "user_decision",
    idempotencyKey: idempotencyKeyFor("Max concurrent sessions b"),
  }));
  const detected = engine.detectContradictions(QUALIFICATION_CORPUS_SCOPE_KEY);
  const sessionsPair = detected.find(
    (p) =>
      (p.recordIdA === sessionsA.recordId && p.recordIdB === sessionsB.recordId) ||
      (p.recordIdA === sessionsB.recordId && p.recordIdB === sessionsA.recordId),
  );
  const openSessionsGroup = engine
    .listOpenContradictions(QUALIFICATION_CORPUS_SCOPE_KEY)
    .find((g) => g.subject === "Max concurrent sessions");
  if (openSessionsGroup !== undefined) {
    engine.resolveContradiction(openSessionsGroup.groupId, {
      action: "supersede",
      winnerRecordId: sessionsB.recordId,
      actor: HUMAN,
      reason: "corpus: 250 is the ratified limit",
      origin: "corpus",
    });
  } else if (sessionsPair !== undefined) {
    const group = engine.registerContradiction(
      QUALIFICATION_CORPUS_SCOPE_KEY,
      "Max concurrent sessions",
      [sessionsA.recordId, sessionsB.recordId],
    );
    engine.resolveContradiction(group.groupId, {
      action: "supersede",
      winnerRecordId: sessionsB.recordId,
      actor: HUMAN,
      reason: "corpus: 250 is the ratified limit",
      origin: "corpus",
    });
  }

  // ---- historical: expired window, adjacent region windows, archived record ----
  engine.addRecord(recordInput("Maintenance window", CONTENT.maintenance, {
    sourceKind: "user_decision",
    validFrom: "2026-06-01T00:00:00.000Z",
    validUntil: "2026-06-30T23:59:59.999Z",
    observedAt: "2026-06-01T00:00:00.000Z",
    idempotencyKey: idempotencyKeyFor("Maintenance window"),
  }));
  engine.addRecord(recordInput("Deployment region", CONTENT.regionA, {
    actor: TOOL,
    method: "synced",
    sourceKind: "repository_evidence",
    confidence: 0.8,
    evidenceRefs: [{ engine: "repository_sync" as const, ref: "region:2026H1" }],
    validFrom: "2026-01-01T00:00:00.000Z",
    validUntil: "2026-03-01T00:00:00.000Z",
    observedAt: "2026-01-01T00:00:00.000Z",
    idempotencyKey: idempotencyKeyFor("Deployment region a"),
  }));
  engine.addRecord(recordInput("Deployment region", CONTENT.regionB, {
    actor: TOOL,
    method: "synced",
    sourceKind: "repository_evidence",
    confidence: 0.8,
    evidenceRefs: [{ engine: "repository_sync" as const, ref: "region:2026H2" }],
    validFrom: "2026-03-01T00:00:00.000Z",
    validUntil: "2026-06-30T23:59:59.999Z",
    observedAt: "2026-03-01T00:00:00.000Z",
    idempotencyKey: idempotencyKeyFor("Deployment region b"),
  }));
  const legacyCache = engine.addRecord(recordInput("Legacy cache", CONTENT.legacyCache, {
    confidence: 0.7,
    idempotencyKey: idempotencyKeyFor("Legacy cache"),
  }));
  if (legacyCache.status === "active") {
    engine.archiveRecord(legacyCache.recordId, { actor: HUMAN, reason: "corpus: archived historical fact", origin: "corpus" });
  }

  // ---- supersession chain (v1 -> v2, capture times strictly ordered) ----
  const authV1 = engine.addRecord(recordInput("Auth provider", AUTH_CONTENT_V1, {
    kind: "decision" as const,
    method: "decided",
    sourceKind: "user_decision",
    confidence: 0.95,
    observedAt: "2026-01-10T00:00:00.000Z",
    idempotencyKey: idempotencyKeyFor("Auth provider v1"),
  }));
  if (authV1.status === "active") {
    advancePast(Date.parse(authV1.createdAt));
    engine.supersedeRecord(authV1.recordId, {
      content: AUTH_CONTENT_V2,
      actor: HUMAN,
      method: "decided",
      reason: "migrated auth providers",
      origin: "corpus",
    });
  }

  // ---- provenance variety ----
  engine.addRecord(recordInput("Onboarding flow", CONTENT.onboarding, {
    epistemicClass: "derived" as const,
    sourceKind: "study_finding",
    actor: { kind: "engine" as const, name: "study-engine" },
    confidence: 0.95,
    evidenceRefs: [{ engine: "study_document" as const, ref: "study:42" }],
    idempotencyKey: idempotencyKeyFor("Onboarding flow"),
  }));
  engine.addRecord(recordInput("Cache strategy", CONTENT.cacheStrategy, {
    kind: "observation" as const,
    epistemicClass: "inferred" as const,
    sourceKind: "agent_inference",
    actor: { kind: "agent" as const, name: "worker-a", agentType: "worker-a" },
    confidence: 0.6,
    idempotencyKey: idempotencyKeyFor("Cache strategy"),
  }));
  engine.addRecord(recordInput("Ranking hot path", CONTENT.hotPath, {
    kind: "observation" as const,
    sourceKind: "performance_evidence",
    actor: { kind: "engine" as const, name: "performance-engine" },
    confidence: 0.75,
    evidenceRefs: [{ engine: "performance" as const, ref: "perf:77" }],
    idempotencyKey: idempotencyKeyFor("Ranking hot path"),
  }));

  // ---- privacy restriction (sensitive material stays queryable, never exported) ----
  engine.addRecord(recordInput("API key rotation", CONTENT.rotation, {
    sourceKind: "user_decision",
    privacyClass: "sensitive",
    idempotencyKey: idempotencyKeyFor("API key rotation"),
  }));

  // ---- boundary guard: the engine must refuse secret-class material ----
  let rejectedSecret = false;
  try {
    engine.addRecord(recordInput("Secret probe", "attempted secret-class material", {
      privacyClass: "secret" as never,
      idempotencyKey: idempotencyKeyFor("Secret probe"),
    }));
  } catch (err) {
    rejectedSecret = err instanceof PrivacyViolationError;
  }
  if (!rejectedSecret) {
    throw new Error("corpus invariant violated: engine accepted secret-class material");
  }

  engine.addRecord(recordInput(MARKER_SUBJECT, `Materialized by qualification corpus ${QUALIFICATION_CORPUS_VERSION}`, {
    kind: "note" as const,
    confidence: 1,
    idempotencyKey: `${QUALIFICATION_CORPUS_SCOPE_KEY}:marker`,
  }));

  // ---- optional embedding area (built-in deterministic provider) ----
  let embeddings: CorpusBuildResult["embeddings"] = null;
  if (options.includeEmbeddings !== false) {
    engine.setEmbeddingProvider(localHashProvider);
    const projection = engine.buildEmbeddingProjection(QUALIFICATION_CORPUS_SCOPE_KEY);
    embeddings = { recordCount: projection.recordCount ?? 0, skippedPrivacy: projection.skippedPrivacy ?? 0 };
  }

  const records = engine.searchRecords({ scope: QUALIFICATION_CORPUS_SCOPE_KEY, status: "all" });
  store.appendEvent("memory.corpus.built", {
    corpusVersion: QUALIFICATION_CORPUS_VERSION,
    scopeKey: QUALIFICATION_CORPUS_SCOPE_KEY,
    recordCount: records.length,
  });

  return {
    corpusVersion: QUALIFICATION_CORPUS_VERSION,
    scopeKey: QUALIFICATION_CORPUS_SCOPE_KEY,
    built: true,
    recordCount: records.length,
    embeddings,
  };
}

// ---- verifier ------------------------------------------------------------------

/**
 * Verify the frozen expectations against a materialized corpus. Read-only:
 * every check inspects state through public read surfaces with pinned or
 * store-derived instants; the resulting report is stable across builds.
 */
export function verifyQualificationCorpusImpl(
  engine: MemoryEngine,
  options: CorpusOptions = {},
): QualificationReport {
  const scopeKey = QUALIFICATION_CORPUS_SCOPE_KEY;
  const checks: QualificationCheck[] = [];

  try {
    const scope = engine.getScope(scopeKey);
    checks.push(check("scope-exists", scope.projectKey === scopeKey, `projectKey ${scope.projectKey}`));
  } catch {
    checks.push(check("scope-exists", false, `no scope '${scopeKey}' — corpus not materialized`));
    return finish(engine, checks, options);
  }

  const allRecords = (): MemoryRecord[] => engine.searchRecords({ scope: scopeKey, status: "all" });
  const activeBySubject = (subject: string): MemoryRecord[] =>
    allRecords().filter((r) => r.subject === subject && r.status === "active");

  // record-counts (by status)
  {
    const records = allRecords();
    const byStatus = (status: string): number => records.filter((r) => r.status === status).length;
    const exact =
      records.length === 18 &&
      byStatus("active") === 15 &&
      byStatus("superseded") === 2 &&
      byStatus("archived") === 1 &&
      byStatus("deleted") === 0;
    checks.push(
      check(
        "record-counts",
        exact,
        `total ${records.length}, active ${byStatus("active")}, superseded ${byStatus("superseded")}, archived ${byStatus("archived")}`,
      ),
    );
  }

  // lexical retrieval over current facts
  {
    const hits = subjectsOf(engine.lexicalSearch("requests per minute", { scope: scopeKey }).hits.map((h) => h.record));
    checks.push(check("lexical-current-facts", hits.length === 1 && hits[0] === "Rate limit", `${hits.length} hit(s)`));
  }

  // current view at the pinned instant (multiset of subjects)
  {
    const expected = [
      "API key rotation",
      "Auth provider",
      "Cache strategy",
      "Deploy window",
      "Deploy window",
      "Deploy window",
      "Max concurrent sessions",
      "Onboarding flow",
      "Qualification corpus marker",
      "Ranking hot path",
      "Rate limit",
      "Retry backoff",
    ].sort();
    const actual = subjectsOf(engine.currentRecords({ scope: scopeKey, at: CORPUS_AT }));
    checks.push(check("current-view", JSON.stringify(actual) === JSON.stringify(expected), `${actual.length} current record(s)`));
  }

  // historical records absent from the current view
  {
    const current = subjectsOf(engine.currentRecords({ scope: scopeKey, at: CORPUS_AT }));
    const absent = ["Deployment region", "Deployment region", "Legacy cache", "Maintenance window"]
      .every((s) => !current.includes(s));
    checks.push(
      check("historical-absent-from-current", absent, absent ? "expired/archived absent" : "historical record leaked into current view"),
    );
  }

  // as-of time travel over the supersession chain (instants read from the store)
  {
    const authAll = engine.searchRecords({ scope: scopeKey, exactSubject: "Auth provider", status: "all" });
    const v1 = authAll.find((r) => r.status === "superseded");
    const v2 = authAll.find((r) => r.status === "active");
    if (v1 === undefined || v2 === undefined) {
      checks.push(check("as-of-supersession", false, "supersession chain incomplete"));
    } else {
      const atV1 = v1.createdAt;
      const authAtV1 = engine
        .queryRecordsAsOf({ scope: scopeKey, asOf: atV1 })
        .filter((r) => r.subject === "Auth provider");
      const v1Visible = authAtV1.length === 1 && authAtV1[0]!.content === AUTH_CONTENT_V1;
      const v2StrictlyLater = Date.parse(v2.createdAt) > Date.parse(atV1);
      const authAtV2 = engine
        .queryRecordsAsOf({ scope: scopeKey, asOf: v2.createdAt })
        .filter((r) => r.subject === "Auth provider");
      const v2Only = authAtV2.length === 1 && authAtV2[0]!.content === AUTH_CONTENT_V2;
      checks.push(
        check(
          "as-of-supersession",
          v1Visible && v2StrictlyLater && v2Only,
          v1Visible && v2StrictlyLater && v2Only
            ? "v1 believed at its capture; v2 only after succession"
            : "as-of belief state diverges from the frozen chain",
        ),
      );
    }
  }

  // supersession lineage + recorded reason
  {
    const v2 = activeBySubject("Auth provider")[0];
    if (v2 === undefined) {
      checks.push(check("supersession-lineage", false, "no active Auth provider record"));
    } else {
      const history = engine.getRecordHistory(v2.recordId);
      const chainOk =
        history.chain.length === 2 &&
        history.chain[0]!.content === AUTH_CONTENT_V1 &&
        history.chain[1]!.content === AUTH_CONTENT_V2 &&
        history.chain[0]!.supersededReason === "migrated auth providers";
      checks.push(check("supersession-lineage", chainOk, `chain length ${history.chain.length}`));
    }
  }

  // contradictions: only the two ungrouped Deploy-window pairs remain detected
  {
    const pairs = engine.detectContradictions(scopeKey);
    const allDeploy = pairs.every((p) => p.subject === "Deploy window");
    const openGroups = engine.listOpenContradictions(scopeKey);
    const sessionsActive = activeBySubject("Max concurrent sessions").length;
    checks.push(
      check(
        "contradiction-pairs",
        pairs.length === 2 && allDeploy && openGroups.length === 0 && sessionsActive === 1,
        `${pairs.length} detected pair(s), ${openGroups.length} open group(s), ${sessionsActive} active session record(s)`,
      ),
    );
  }

  // duplicates: exact / near / corroborating classifications
  {
    const exact = engine.analyzeDuplicates(scopeKey, {
      subject: "Deploy window",
      content: CONTENT.deployRunbook,
      evidenceRefs: [{ engine: "repository_sync", ref: "deploy:runbook" }],
    });
    const exactMatches = exact.matches.filter((m) => m.kind === "exact").length;
    const near = engine.analyzeDuplicates(scopeKey, {
      subject: "Deploy window",
      content: CONTENT.deployNear,
      evidenceRefs: [{ engine: "repository_sync", ref: "deploy:proposal" }],
    });
    const nearMatches = near.matches.filter((m) => m.kind === "near" || m.kind === "normalized").length;
    const corroboration = engine.analyzeDuplicates(scopeKey, {
      subject: "Deploy window",
      content: CONTENT.deployRunbook,
      evidenceRefs: [{ engine: "repository_sync", ref: "deploy:other-source" }],
    });
    checks.push(
      check(
        "duplicates",
        exact.isDuplicate && exactMatches === 2 && near.isDuplicate && nearMatches === 2 && corroboration.corroborating.length === 1,
        `exact ${exactMatches}, near ${nearMatches}, corroborators ${corroboration.corroborating.length}`,
      ),
    );
  }

  // privacy: sensitive record excluded from default excerpts, present on opt-in
  {
    const pack = engine.contextExcerpts({ scope: scopeKey, at: CORPUS_AT });
    const leak = pack.excerpts.some((e) => e.subject === "API key rotation" || e.privacyClass === "sensitive");
    const optIn = engine.contextExcerpts({ scope: scopeKey, at: CORPUS_AT, includeSensitive: true });
    const optInPresent = optIn.excerpts.some((e) => e.subject === "API key rotation");
    checks.push(
      check(
        "privacy-excerpts",
        pack.skippedSensitive === 1 && !leak && optInPresent,
        `skippedSensitive ${pack.skippedSensitive}, opt-in present ${optInPresent}`,
      ),
    );
  }

  // provenance: structured filters over source engine, actor, confidence
  {
    const byEngine = subjectsOf(engine.searchRecords({ scope: scopeKey, sourceEngine: "study_document" }));
    const byActor = subjectsOf(engine.searchRecords({ scope: scopeKey, actor: "agent:worker-a" }));
    const highConfidence = subjectsOf(engine.searchRecords({ scope: scopeKey, confidenceMin: 0.95 }));
    const ok =
      byEngine.length === 1 && byEngine[0] === "Onboarding flow" &&
      byActor.length === 1 && byActor[0] === "Cache strategy" &&
      highConfidence.includes("Auth provider") && highConfidence.includes("Onboarding flow");
    checks.push(check("provenance-filters", ok, `engine ${byEngine.length}, actor ${byActor.length}, confidence>=0.95 ${highConfidence.length}`));
  }

  // boundary: secret-class material is still rejected at verification time
  {
    let rejected = false;
    try {
      engine.addRecord(recordInput("Secret probe", "attempted secret-class material", {
        privacyClass: "secret" as never,
        idempotencyKey: `${scopeKey}:verify-secret-probe`,
      }));
    } catch (err) {
      rejected = err instanceof PrivacyViolationError;
    }
    checks.push(check("secret-rejected", rejected, rejected ? "PrivacyViolationError" : "secret-class material accepted"));
  }

  // optional embedding area
  if (options.includeEmbeddings !== false) {
    // The built-in deterministic provider is part of the corpus contract: a
    // stored projection must be reported through the same provider identity.
    engine.setEmbeddingProvider(localHashProvider);
    const status = engine.embeddingProjectionStatus(scopeKey);
    if (status.status !== "built") {
      checks.push(check("embeddings", false, `projection status ${status.status}`));
    } else {
      const semantic = engine.semanticSearch("requests per minute", { scope: scopeKey });
      const top = semantic.hits[0]?.record.subject ?? "none";
      const corrupted = semantic.diagnostics.skippedCorrupt ?? 0;
      checks.push(
        check(
          "embeddings",
          status.skippedPrivacy === 1 && top === "Rate limit" && corrupted === 0,
          `skippedPrivacy ${status.skippedPrivacy}, top hit '${top}', skippedCorrupt ${corrupted}`,
        ),
      );
    }
  }

  // corpus build observability
  {
    const event = engine.listEvents(200).find((e) => e.type === "memory.corpus.built");
    checks.push(check("corpus-event", event !== undefined, event !== undefined ? "memory.corpus.built present" : "missing memory.corpus.built"));
  }

  return finish(engine, checks, options);
}

function finish(engine: MemoryEngine, checks: QualificationCheck[], options: CorpusOptions): QualificationReport {
  return {
    corpusVersion: QUALIFICATION_CORPUS_VERSION,
    contractVersion: engine.contractVersion,
    scopeKey: QUALIFICATION_CORPUS_SCOPE_KEY,
    embeddingsChecked: options.includeEmbeddings !== false,
    checks,
    passed: checks.every((c) => c.pass),
  };
}
