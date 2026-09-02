/**
 * Canonical Memory record lifecycle (Task 3).
 *
 * The canonical schema per record: kind, subject, normalized content,
 * provenance (actor/method/capture time), source engine + evidence links
 * (BY REFERENCE), scope, epistemic class, confidence, temporal validity,
 * privacy class, tags, relation hints, created/revised timestamps, status,
 * revision counter, supersession links, contradiction group.
 *
 * Revisions are immutable rows (memory_record_revisions); the record row
 * points at the current revision. Supersession forms explicit chains via
 * supersedes_id / superseded_by_id.
 */
import {
  ConflictError,
  CorrectionForbiddenError,
  IntakeUnauthorizedError,
  NotFoundError,
  PromotionForbiddenError,
  ValidationError,
} from "../contracts/errors.ts";
import type {
  EpistemicClass,
  EvidenceRef,
  MemoryCandidate,
  MemoryRecord,
  Provenance,
  PromotionPolicyName,
  RecordKind,
  RecordStatus,
  RelationHint,
  ScopeInfo,
  SourceKind,
} from "../contracts/types.ts";
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import { actorKey, contentHashOf, newId } from "./ids.ts";
import { normalizeText } from "./normalize.ts";
import { LIMITS, validateRecordCore } from "./validation.ts";
import { assertMutationAuthorized, withOrigin } from "./authorization.ts";
import { getScopeImpl, assertScopeNotDeleted } from "./scopes.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import { evaluatePromotionImpl, resolvePolicy } from "./policies.ts";
import type { MemoryStore } from "./store.ts";

export interface ActorInput {
  kind: "human" | "agent" | "engine" | "tool";
  name: string;
  agentType?: string;
}

export interface RecordInput {
  /** Scope id or project key. */
  scope: string;
  kind: RecordKind;
  subject: string;
  content: string;
  actor: ActorInput;
  method: string;
  epistemicClass: EpistemicClass;
  confidence: number;
  evidenceRefs?: EvidenceRef[];
  relationHints?: RelationHint[];
  tags?: string[];
  privacyClass?: "public" | "internal" | "sensitive";
  validFrom?: string | null;
  validUntil?: string | null;
  /** Bi-temporal valid time: when the claim held in the source reality. */
  observedAt?: string;
  /** Task 4 authority: what kind of source this claim traces to. */
  sourceKind?: SourceKind;
  /** Required for agent_summary: the summarized source, by reference. */
  derivedFrom?: EvidenceRef;
  supersedesId?: string;
  /** Task 11: explicit reason required when superseding. */
  reason?: string;
  contradictionGroupId?: string;
  /** Task 7: replay-safe writes. Same key ⇒ same record, no duplicate. */
  idempotencyKey?: string;
}

export interface RecordSearchFilter {
  scope?: string;
  kind?: RecordKind;
  status?: RecordStatus | "all";
  subjectContains?: string;
  contentContains?: string;
  tag?: string;
  limit?: number;
  // ---- Task 14: structured-filter retrieval ----
  /** Exact (case-sensitive, normalized) subject match. */
  exactSubject?: string;
  /** Evidence references must include this engine name. */
  sourceEngine?: string;
  /** Provenance actor canonical key ("human:kim", "agent:worker-1"). */
  actor?: string;
  confidenceMin?: number;
  confidenceMax?: number;
  /** Validity window must contain this instant (validFrom ≤ t < validUntil). */
  validAt?: string;
  createdAfter?: string;
  createdBefore?: string;
  observedAfter?: string;
  observedBefore?: string;
}

export function addRecordImpl(store: MemoryStore, input: RecordInput): MemoryRecord {
  // Task 7 idempotent write: replaying a key returns the original record.
  if (input.idempotencyKey !== undefined) {
    const existing = findByIdempotencyKey(store, input.idempotencyKey);
    if (existing !== null) return existing;
  }
  const core = validateRecordCore({
    kind: input.kind,
    subject: normalizeText(asNonEmpty(input.subject, "subject")),
    content: normalizeText(asNonEmpty(input.content, "content")),
    epistemicClass: input.epistemicClass,
    confidence: input.confidence,
    evidenceRefs: input.evidenceRefs,
    relationHints: input.relationHints,
    tags: input.tags,
    privacyClass: input.privacyClass,
    validFrom: input.validFrom,
    validUntil: input.validUntil,
    observedAt: input.observedAt,
    sourceKind: input.sourceKind,
    derivedFrom: input.derivedFrom,
    actor: input.actor,
    method: input.method,
  });
  const scope = getScopeImpl(store, input.scope);
  assertScopeNotDeleted(scope);
  const db = store.ensureOpen();
  const recordId = newId("mem");
  const now = new Date().toISOString();
  const observedAt = core.observedAt ?? now;
  const provenance: Provenance = {
    actor: core.actor,
    method: core.method,
    capturedAt: now,
    sourceKind: core.sourceKind,
    ...(core.derivedFrom !== undefined ? { derivedFrom: core.derivedFrom } : {}),
  };
  const contentHash = contentHashOf(core.content);
  let supersededTarget: MemoryRecord | undefined;

  db.exec("BEGIN IMMEDIATE;");
  try {
    if (input.supersedesId !== undefined) {
      // Task 11: supersession requires an explicit reason.
      if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
        throw new ValidationError(
          "reason is required: supersession must record why the older record is superseded",
        );
      }
      supersededTarget = getRecordImpl(store, input.supersedesId);
      if (supersededTarget.status !== "active") {
        throw new ConflictError(
          `Record '${input.supersedesId}' is '${supersededTarget.status}', only active records can be superseded`,
        );
      }
    }
    if (input.contradictionGroupId !== undefined) {
      const group = db
        .prepare("SELECT group_id FROM contradiction_groups WHERE group_id = ?")
        .get(input.contradictionGroupId);
      if (group === undefined) {
        throw new NotFoundError(
          `Contradiction group '${input.contradictionGroupId}' not found`,
        );
      }
    }
    db.prepare(
      `INSERT INTO memory_records (
         record_id, contract_version, kind, subject, content, content_hash,
         scope_id, provenance_json, epistemic_class, confidence,
         evidence_json, relation_hints_json, tags_json, privacy_class,
         valid_from, valid_until, observed_at, status, revision,
         created_at, revised_at, supersedes_id, contradiction_group_id,
         idempotency_key
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?, ?)`,
    ).run(
      recordId,
      MEMORY_ENGINE_CONTRACT_VERSION,
      core.kind,
      core.subject,
      core.content,
      contentHash,
      scope.scopeId,
      JSON.stringify(provenance),
      core.epistemicClass,
      core.confidence,
      JSON.stringify(core.evidenceRefs),
      JSON.stringify(core.relationHints),
      JSON.stringify(core.tags),
      core.privacyClass,
      core.validFrom,
      core.validUntil,
      observedAt,
      now,
      now,
      input.supersedesId ?? null,
      input.contradictionGroupId ?? null,
      input.idempotencyKey ?? null,
    );
    insertRevision(
      db,
      recordId,
      1,
      core,
      provenance,
      now,
      input.supersedesId !== undefined
        ? `supersedes ${input.supersedesId}: ${input.reason!.trim()}`
        : "initial",
    );
    if (supersededTarget !== undefined) {
      db.prepare(
        "UPDATE memory_records SET status = 'superseded', superseded_by_id = ?, superseded_at = ?, supersede_reason = ?, revised_at = ? WHERE record_id = ?",
      ).run(recordId, now, input.reason!.trim(), now, input.supersedesId!);
    }
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }

  store.appendEvent("memory.record.created", {
    recordId,
    scopeId: scope.scopeId,
    kind: core.kind,
    subject: core.subject,
    revision: 1,
    actor: actorKey(core.actor),
    privacyClass: core.privacyClass,
    supersedesId: input.supersedesId ?? null,
  });
  if (supersededTarget !== undefined) {
    store.appendEvent("memory.record.superseded", {
      recordId: input.supersedesId!,
      supersededById: recordId,
      scopeId: scope.scopeId,
      actor: actorKey(core.actor),
      reason: input.reason!.trim(),
    });
  }

  const record = getRecordImpl(store, recordId);
  return record;
}

function asNonEmpty(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ValidationError(`${field} is required`);
  }
  return value;
}

type Db = MemoryStore extends { ensureOpen(): infer T } ? T : never;

function insertRevision(
  db: Db,
  recordId: string,
  revision: number,
  core: { content: string },
  provenance: Provenance,
  revisedAt: string,
  reason: string | null,
): void {
  db.prepare(
    `INSERT INTO memory_record_revisions (record_id, revision, content, content_hash, provenance_json, revised_at, reason)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    recordId,
    revision,
    core.content,
    contentHashOf(core.content),
    JSON.stringify(provenance),
    revisedAt,
    reason,
  );
}

export function rowToRecord(row: Record<string, unknown>): MemoryRecord {
  return {
    recordId: String(row["record_id"]),
    contractVersion: String(row["contract_version"]),
    kind: String(row["kind"]) as RecordKind,
    subject: String(row["subject"]),
    content: String(row["content"]),
    contentHash: String(row["content_hash"]),
    scopeId: String(row["scope_id"]),
    provenance: normalizeProvenance(JSON.parse(String(row["provenance_json"]))),
    epistemicClass: String(row["epistemic_class"]) as EpistemicClass,
    confidence: Number(row["confidence"]),
    evidenceRefs: JSON.parse(String(row["evidence_json"])) as EvidenceRef[],
    relationHints: JSON.parse(String(row["relation_hints_json"])) as RelationHint[],
    tags: JSON.parse(String(row["tags_json"])) as string[],
    privacyClass: String(row["privacy_class"]) as MemoryRecord["privacyClass"],
    validFrom: row["valid_from"] === null ? null : String(row["valid_from"]),
    validUntil: row["valid_until"] === null ? null : String(row["valid_until"]),
    observedAt: String(row["observed_at"] ?? row["created_at"]),
    status: String(row["status"]) as RecordStatus,
    revision: Number(row["revision"]),
    createdAt: String(row["created_at"]),
    revisedAt: String(row["revised_at"]),
    supersededAt: row["superseded_at"] === null || row["superseded_at"] === undefined
      ? null
      : String(row["superseded_at"]),
    supersededReason:
      row["supersede_reason"] === null || row["supersede_reason"] === undefined
        ? null
        : String(row["supersede_reason"]),
    supersedesId: row["supersedes_id"] === null ? null : String(row["supersedes_id"]),
    supersededById:
      row["superseded_by_id"] === null ? null : String(row["superseded_by_id"]),
    contradictionGroupId:
      row["contradiction_group_id"] === null
        ? null
        : String(row["contradiction_group_id"]),
    idempotencyKey:
      row["idempotency_key"] === null || row["idempotency_key"] === undefined
        ? null
        : String(row["idempotency_key"]),
    archivedAt:
      row["archived_at"] === null || row["archived_at"] === undefined
        ? null
        : String(row["archived_at"]),
    deletedAt:
      row["deleted_at"] === null || row["deleted_at"] === undefined
        ? null
        : String(row["deleted_at"]),
    deletedBy:
      row["deleted_by"] === null || row["deleted_by"] === undefined
        ? null
        : String(row["deleted_by"]),
    deleteReason:
      row["delete_reason"] === null || row["delete_reason"] === undefined
        ? null
        : String(row["delete_reason"]),
  };
}

/**
 * Task 8 intake authorization: under an allowlist policy, the caller key
 * must be listed. Caller key is the canonical actor string.
 */
export function assertIntakeAuthorized(scope: ScopeInfo, caller: ActorInput | undefined): void {
  if (scope.intakePolicy.mode === "open") return;
  if (caller === undefined) {
    throw new IntakeUnauthorizedError(
      `scope '${scope.projectKey}' requires an authorized caller (intake policy: allowlist)`,
    );
  }
  const key = actorKey(caller);
  if (!scope.intakePolicy.allow.includes(key)) {
    throw new IntakeUnauthorizedError(
      `caller '${key}' is not authorized to propose candidates to scope '${scope.projectKey}' (intake policy: allowlist)`,
    );
  }
}

function normalizeProvenance(raw: unknown): Provenance {
  const p = (raw ?? {}) as Partial<Provenance>;
  return {
    actor: p.actor ?? { kind: "unknown" as never, name: "unknown" },
    method: p.method ?? "unknown",
    capturedAt: p.capturedAt ?? "",
    sourceKind: p.sourceKind ?? "unknown",
    ...(p.derivedFrom !== undefined ? { derivedFrom: p.derivedFrom } : {}),
  } as Provenance;
}

export function getRecordImpl(store: MemoryStore, recordId: string): MemoryRecord {
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT * FROM memory_records WHERE record_id = ?")
    .get(recordId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new NotFoundError(`Record '${recordId}' not found`);
  }
  return rowToRecord(row);
}

export function reviseRecordImpl(
  store: MemoryStore,
  recordId: string,
  input: {
    content: string;
    actor: ActorInput;
    method: string;
    /** Task 12: corrections must say why (required). */
    reason: string;
    sourceKind?: SourceKind;
    derivedFrom?: EvidenceRef;
    /** Task 35: surface that initiated the mutation (cli/contract/mcp/host). */
    origin?: string;
  },
): MemoryRecord {
  if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
    throw new ValidationError(
      "reason is required: corrections are attributed revisions, never silent mutations",
    );
  }
  const current = getRecordImpl(store, recordId);
  if (current.status !== "active") {
    throw new ConflictError(
      `Record '${recordId}' is '${current.status}'; only active records can be revised`,
    );
  }
  // Task 35: an explicit restricted policy may authorize a specific agent;
  // otherwise agents are structurally refused (they use the candidate intake).
  const authorized = assertMutationAuthorized(store, current.scopeId, input.actor, "revise");
  if (!authorized && input.actor.kind === "agent") {
    throw new CorrectionForbiddenError(
      "actors of kind 'agent' cannot correct records directly: propose a candidate via the intake pipeline instead",
    );
  }
  const core = validateRecordCore({
    kind: current.kind,
    subject: current.subject,
    content: normalizeText(asNonEmpty(input.content, "content")),
    epistemicClass: current.epistemicClass,
    confidence: current.confidence,
    evidenceRefs: current.evidenceRefs,
    tags: current.tags,
    privacyClass: current.privacyClass,
    validFrom: current.validFrom,
    validUntil: current.validUntil,
    observedAt: current.observedAt,
    sourceKind: input.sourceKind ?? current.provenance.sourceKind,
    derivedFrom: input.derivedFrom ?? current.provenance.derivedFrom,
    actor: input.actor,
    method: input.method,
  });
  const db = store.ensureOpen();
  const now = new Date().toISOString();
  const newRevision = current.revision + 1;
  const provenance: Provenance = {
    actor: core.actor,
    method: core.method,
    capturedAt: now,
    sourceKind: core.sourceKind,
    ...(core.derivedFrom !== undefined ? { derivedFrom: core.derivedFrom } : {}),
  };
  db.exec("BEGIN IMMEDIATE;");
  try {
    db.prepare(
      `UPDATE memory_records
       SET content = ?, content_hash = ?, provenance_json = ?, revision = ?, revised_at = ?
       WHERE record_id = ? AND status = 'active'`,
    ).run(
      core.content,
      contentHashOf(core.content),
      JSON.stringify(provenance),
      newRevision,
      now,
      recordId,
    );
    insertRevision(
      db,
      recordId,
      newRevision,
      core,
      provenance,
      now,
      input.reason ?? null,
    );
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }
  store.appendEvent("memory.record.revised", withOrigin({
    recordId,
    revision: newRevision,
    actor: actorKey(core.actor),
    reason: input.reason ?? null,
  }, input.origin));
  return getRecordImpl(store, recordId);
}

export function supersedeRecordImpl(
  store: MemoryStore,
  recordId: string,
  input: {
    content: string;
    actor: ActorInput;
    method: string;
    /** Task 11: explicit reason for superseding (required). */
    reason: string;
    sourceKind?: SourceKind;
    derivedFrom?: EvidenceRef;
    /** Task 35: surface that initiated the mutation (cli/contract/mcp/host). */
    origin?: string;
  },
): MemoryRecord {
  if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
    throw new ValidationError(
      "reason is required: supersession must record why the older record is superseded",
    );
  }
  const current = getRecordImpl(store, recordId);
  if (current.status !== "active") {
    throw new ConflictError(
      `Record '${recordId}' is '${current.status}'; only active records can be superseded`,
    );
  }
  // Task 35: an explicit restricted policy may authorize a specific agent.
  const authorized = assertMutationAuthorized(store, current.scopeId, input.actor, "supersede");
  if (!authorized && input.actor.kind === "agent") {
    throw new CorrectionForbiddenError(
      "actors of kind 'agent' cannot supersede records directly: propose a candidate via the intake pipeline instead",
    );
  }
  const record = addRecordImpl(store, {
    scope: current.scopeId,
    kind: current.kind,
    subject: current.subject,
    content: input.content,
    actor: input.actor,
    method: input.method,
    epistemicClass: current.epistemicClass,
    confidence: current.confidence,
    evidenceRefs: current.evidenceRefs,
    relationHints: current.relationHints,
    tags: current.tags,
    privacyClass: current.privacyClass,
    validFrom: current.validFrom,
    validUntil: current.validUntil,
    observedAt: current.observedAt,
    sourceKind: input.sourceKind ?? current.provenance.sourceKind,
    derivedFrom: input.derivedFrom ?? current.provenance.derivedFrom,
    contradictionGroupId: current.contradictionGroupId ?? undefined,
    supersedesId: recordId,
    reason: input.reason,
  });
  return record;
}

export function retractRecordImpl(
  store: MemoryStore,
  recordId: string,
  input: { actor: ActorInput; reason: string; origin?: string },
): MemoryRecord {
  const current = getRecordImpl(store, recordId);
  // Task 35: an explicit restricted policy may authorize a specific agent.
  const authorized = assertMutationAuthorized(store, current.scopeId, input.actor, "retract");
  if (!authorized && input.actor.kind === "agent") {
    throw new CorrectionForbiddenError(
      "actors of kind 'agent' cannot retract records: lifecycle decisions belong to users or authorized engines",
    );
  }
  if (current.status === "retracted") {
    throw new ConflictError(`Record '${recordId}' is already retracted`);
  }
  if (current.status === "expired") {
    throw new ConflictError(`Record '${recordId}' is expired`);
  }
  const actor = validateRecordCore({
    kind: current.kind,
    subject: current.subject,
    content: current.content,
    epistemicClass: current.epistemicClass,
    confidence: current.confidence,
    evidenceRefs: current.evidenceRefs,
    privacyClass: current.privacyClass,
    validFrom: current.validFrom,
    validUntil: current.validUntil,
    observedAt: current.observedAt,
    sourceKind: current.provenance.sourceKind,
    derivedFrom: current.provenance.derivedFrom,
    actor: input.actor,
    method: "retract",
  });
  if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
    throw new ValidationError("reason is required for retraction");
  }
  const db = store.ensureOpen();
  const now = new Date().toISOString();
  const newRevision = current.revision + 1;
  const provenance: Provenance = {
    actor: actor.actor,
    method: "retract",
    capturedAt: now,
    sourceKind: actor.sourceKind,
  };
  db.exec("BEGIN IMMEDIATE;");
  try {
    db.prepare(
      "UPDATE memory_records SET status = 'retracted', revision = ?, revised_at = ? WHERE record_id = ?",
    ).run(newRevision, now, recordId);
    insertRevision(db, recordId, newRevision, current, provenance, now, `retracted: ${input.reason.trim()}`);
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }
  store.appendEvent("memory.record.retracted", withOrigin({
    recordId,
    actor: actorKey(actor.actor),
    reason: input.reason.trim(),
  }, input.origin));
  return getRecordImpl(store, recordId);
}

/** Shared clause/param builder — reused by the plain search and its traced sibling. */
function buildSearchClauses(
  store: MemoryStore,
  filter: RecordSearchFilter,
): { clauses: string[]; params: Array<string | number> } {
  const clauses: string[] = [];
  const params: Array<string | number> = [];
  if (filter.scope !== undefined) {
    const scope = getScopeImpl(store, filter.scope);
    clauses.push("scope_id = ?");
    params.push(scope.scopeId);
  }
  if (filter.kind !== undefined) {
    clauses.push("kind = ?");
    params.push(filter.kind);
  }
  if (filter.status !== undefined && filter.status !== "all") {
    clauses.push("status = ?");
    params.push(filter.status);
  } else if (filter.status === undefined) {
    // Task 13 default view: tombstoned records are excluded from search
    // unless explicitly requested ("all" or status "deleted").
    clauses.push("status != 'deleted'");
  }
  if (filter.subjectContains !== undefined) {
    clauses.push("subject LIKE ? ESCAPE '\\'");
    params.push(`%${escapeLike(filter.subjectContains)}%`);
  }
  if (filter.contentContains !== undefined) {
    clauses.push("content LIKE ? ESCAPE '\\'");
    params.push(`%${escapeLike(filter.contentContains)}%`);
  }
  if (filter.tag !== undefined) {
    clauses.push("EXISTS (SELECT 1 FROM json_each(memory_records.tags_json) WHERE json_each.value = ?)");
    params.push(filter.tag);
  }
  // ---- Task 14: structured-filter retrieval ----
  if (filter.exactSubject !== undefined) {
    clauses.push("subject = ?");
    params.push(filter.exactSubject);
  }
  if (filter.sourceEngine !== undefined) {
    clauses.push(
      "EXISTS (SELECT 1 FROM json_each(memory_records.evidence_json) WHERE json_each.value ->> 'engine' = ?)",
    );
    params.push(filter.sourceEngine);
  }
  if (filter.actor !== undefined) {
    clauses.push(
      "json_extract(memory_records.provenance_json, '$.actor.kind') || ':' || json_extract(memory_records.provenance_json, '$.actor.name') = ?",
    );
    params.push(filter.actor);
  }
  if (filter.confidenceMin !== undefined) {
    if (typeof filter.confidenceMin !== "number" || !Number.isFinite(filter.confidenceMin)) {
      throw new ValidationError("confidenceMin must be a number");
    }
    clauses.push("confidence >= ?");
    params.push(filter.confidenceMin);
  }
  if (filter.confidenceMax !== undefined) {
    if (typeof filter.confidenceMax !== "number" || !Number.isFinite(filter.confidenceMax)) {
      throw new ValidationError("confidenceMax must be a number");
    }
    clauses.push("confidence <= ?");
    params.push(filter.confidenceMax);
  }
  if (filter.validAt !== undefined) {
    assertIsoTimestamp(filter.validAt, "validAt");
    clauses.push(
      "(valid_from IS NULL OR valid_from <= ?) AND (valid_until IS NULL OR valid_until > ?)",
    );
    params.push(filter.validAt, filter.validAt);
  }
  if (filter.createdAfter !== undefined) {
    assertIsoTimestamp(filter.createdAfter, "createdAfter");
    clauses.push("created_at > ?");
    params.push(filter.createdAfter);
  }
  if (filter.createdBefore !== undefined) {
    assertIsoTimestamp(filter.createdBefore, "createdBefore");
    clauses.push("created_at <= ?");
    params.push(filter.createdBefore);
  }
  if (filter.observedAfter !== undefined) {
    assertIsoTimestamp(filter.observedAfter, "observedAfter");
    clauses.push("observed_at > ?");
    params.push(filter.observedAfter);
  }
  if (filter.observedBefore !== undefined) {
    assertIsoTimestamp(filter.observedBefore, "observedBefore");
    clauses.push("observed_at <= ?");
    params.push(filter.observedBefore);
  }
  return { clauses, params };
}

export function searchRecordsImpl(
  store: MemoryStore,
  filter: RecordSearchFilter,
): MemoryRecord[] {
  const db = store.ensureOpen();
  const { clauses, params } = buildSearchClauses(store, filter);
  const limit = Math.min(Math.max(filter.limit ?? 100, 1), 1000);
  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const rows = db
    .prepare(
      `SELECT * FROM memory_records ${where} ORDER BY revised_at DESC, record_id DESC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  return rows.map(rowToRecord);
}

// ---- Task 20: retrieval traces — "why did this record match, which
// filters applied" alongside the plain structured search. -------------------

export interface SearchMatchReason {
  filter: string;
  reason: string;
}

export interface SearchTrace {
  /** Only the filter keys the caller actually set (no undefined noise). */
  appliedFilters: Record<string, unknown>;
  totalMatches: number;
  truncated: boolean;
  matches: Record<string, SearchMatchReason[]>;
}

/** One reason per applied filter key, citing the record's real matched value. */
export function explainSearchMatch(
  filter: RecordSearchFilter,
  record: MemoryRecord,
): SearchMatchReason[] {
  const reasons: SearchMatchReason[] = [];
  if (filter.scope !== undefined) {
    reasons.push({ filter: "scope", reason: `scopeId '${record.scopeId}' matches requested scope` });
  }
  if (filter.kind !== undefined) {
    reasons.push({ filter: "kind", reason: `kind '${record.kind}' === '${filter.kind}'` });
  }
  if (filter.status !== undefined && filter.status !== "all") {
    reasons.push({ filter: "status", reason: `status '${record.status}' === '${filter.status}'` });
  } else if (filter.status === undefined) {
    reasons.push({
      filter: "status",
      reason: `status '${record.status}' is not 'deleted' (default view excludes tombstones)`,
    });
  }
  if (filter.subjectContains !== undefined) {
    reasons.push({
      filter: "subjectContains",
      reason: `subject '${record.subject}' contains '${filter.subjectContains}'`,
    });
  }
  if (filter.contentContains !== undefined) {
    reasons.push({
      filter: "contentContains",
      reason: `content contains '${filter.contentContains}'`,
    });
  }
  if (filter.tag !== undefined) {
    reasons.push({ filter: "tag", reason: `tags include '${filter.tag}'` });
  }
  if (filter.exactSubject !== undefined) {
    reasons.push({
      filter: "exactSubject",
      reason: `subject '${record.subject}' === '${filter.exactSubject}'`,
    });
  }
  if (filter.sourceEngine !== undefined) {
    const matchedRef = record.evidenceRefs.find((r) => r.engine === filter.sourceEngine);
    reasons.push({
      filter: "sourceEngine",
      reason: `evidenceRefs include engine '${filter.sourceEngine}'${matchedRef !== undefined ? ` (ref '${matchedRef.ref}')` : ""}`,
    });
  }
  if (filter.actor !== undefined) {
    reasons.push({
      filter: "actor",
      reason: `provenance.actor '${actorKey(record.provenance.actor)}' === '${filter.actor}'`,
    });
  }
  if (filter.confidenceMin !== undefined) {
    reasons.push({
      filter: "confidenceMin",
      reason: `confidence ${record.confidence} >= confidenceMin ${filter.confidenceMin}`,
    });
  }
  if (filter.confidenceMax !== undefined) {
    reasons.push({
      filter: "confidenceMax",
      reason: `confidence ${record.confidence} <= confidenceMax ${filter.confidenceMax}`,
    });
  }
  if (filter.validAt !== undefined) {
    reasons.push({
      filter: "validAt",
      reason: `validity window [${record.validFrom ?? "-inf"}, ${record.validUntil ?? "+inf"}) contains '${filter.validAt}'`,
    });
  }
  if (filter.createdAfter !== undefined) {
    reasons.push({
      filter: "createdAfter",
      reason: `createdAt '${record.createdAt}' > '${filter.createdAfter}'`,
    });
  }
  if (filter.createdBefore !== undefined) {
    reasons.push({
      filter: "createdBefore",
      reason: `createdAt '${record.createdAt}' <= '${filter.createdBefore}'`,
    });
  }
  if (filter.observedAfter !== undefined) {
    reasons.push({
      filter: "observedAfter",
      reason: `observedAt '${record.observedAt}' > '${filter.observedAfter}'`,
    });
  }
  if (filter.observedBefore !== undefined) {
    reasons.push({
      filter: "observedBefore",
      reason: `observedAt '${record.observedAt}' <= '${filter.observedBefore}'`,
    });
  }
  return reasons;
}

const SEARCH_FILTER_KEYS = [
  "scope", "kind", "status", "subjectContains", "contentContains", "tag",
  "exactSubject", "sourceEngine", "actor", "confidenceMin", "confidenceMax",
  "validAt", "createdAfter", "createdBefore", "observedAfter", "observedBefore",
] as const satisfies ReadonlyArray<keyof RecordSearchFilter>;

function appliedFiltersOf(filter: RecordSearchFilter): Record<string, unknown> {
  const applied: Record<string, unknown> = {};
  for (const key of SEARCH_FILTER_KEYS) {
    if (filter[key] !== undefined) applied[key] = filter[key];
  }
  return applied;
}

export function searchRecordsTracedImpl(
  store: MemoryStore,
  filter: RecordSearchFilter,
): { records: MemoryRecord[]; trace: SearchTrace } {
  const db = store.ensureOpen();
  const { clauses, params } = buildSearchClauses(store, filter);
  const limit = Math.min(Math.max(filter.limit ?? 100, 1), 1000);
  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const rows = db
    .prepare(
      `SELECT * FROM memory_records ${where} ORDER BY revised_at DESC, record_id DESC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  const records = rows.map(rowToRecord);
  const totalRow = db
    .prepare(`SELECT COUNT(*) AS n FROM memory_records ${where}`)
    .get(...params) as Record<string, unknown>;
  const totalMatches = Number(totalRow["n"]);
  const matches: Record<string, SearchMatchReason[]> = {};
  for (const record of records) {
    matches[record.recordId] = explainSearchMatch(filter, record);
  }
  return {
    records,
    trace: {
      appliedFilters: appliedFiltersOf(filter),
      totalMatches,
      truncated: totalMatches > records.length,
      matches,
    },
  };
}

function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, (c) => `\\${c}`);
}

function findByIdempotencyKey(store: MemoryStore, key: string): MemoryRecord | null {
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT * FROM memory_records WHERE idempotency_key = ?")
    .get(key) as Record<string, unknown> | undefined;
  return row === undefined ? null : rowToRecord(row);
}

export function addCandidateImpl(
  store: MemoryStore,
  input: Omit<RecordInput, "relationHints" | "privacyClass" | "validFrom" | "validUntil" | "observedAt"> & {
    /** Task 8: why this proposal exists (required). */
    reason: string;
    /** Task 8: who is submitting (required under allowlist intake). */
    caller?: ActorInput;
  },
): MemoryCandidate {
  // Task 7 idempotent intake: same key ⇒ same candidate, no duplicate.
  if (input.idempotencyKey !== undefined) {
    const db = store.ensureOpen();
    const existing = db
      .prepare("SELECT * FROM memory_candidates WHERE idempotency_key = ?")
      .get(input.idempotencyKey) as Record<string, unknown> | undefined;
    if (existing !== undefined) return rowToCandidate(existing);
  }
  if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
    throw new ValidationError("reason is required: proposals must say why they exist");
  }
  if (input.reason.trim().length > LIMITS.reason) {
    throw new ValidationError(`reason exceeds ${LIMITS.reason} characters`);
  }
  // Task 8 intake authorization: scoped allowlist of caller keys.
  const scope = getScopeImpl(store, input.scope);
  assertScopeNotDeleted(scope);
  assertIntakeAuthorized(scope, input.caller);

  const core = validateRecordCore({
    kind: input.kind,
    subject: normalizeText(asNonEmpty(input.subject, "subject")),
    content: normalizeText(asNonEmpty(input.content, "content")),
    epistemicClass: input.epistemicClass,
    confidence: input.confidence,
    evidenceRefs: input.evidenceRefs,
    tags: input.tags,
    sourceKind: input.sourceKind,
    derivedFrom: input.derivedFrom,
    actor: input.actor,
    method: input.method,
  });
  const db = store.ensureOpen();
  const candidateId = newId("cand");
  const now = new Date().toISOString();
  const provenance: Provenance = {
    actor: core.actor,
    method: core.method,
    capturedAt: now,
    sourceKind: core.sourceKind,
    ...(core.derivedFrom !== undefined ? { derivedFrom: core.derivedFrom } : {}),
  };
  try {
    db.prepare(
      `INSERT INTO memory_candidates (
         candidate_id, scope_id, kind, subject, content, content_hash,
         provenance_json, epistemic_class, confidence, evidence_json,
         tags_json, status, created_at, reason, caller_json, idempotency_key
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)`,
    ).run(
      candidateId,
      scope.scopeId,
      core.kind,
      core.subject,
      core.content,
      contentHashOf(core.content),
      JSON.stringify(provenance),
      core.epistemicClass,
      core.confidence,
      JSON.stringify(core.evidenceRefs),
      JSON.stringify(core.tags),
      now,
      input.reason.trim(),
      input.caller !== undefined ? JSON.stringify(input.caller) : null,
      input.idempotencyKey ?? null,
    );
  } catch (err) {
    // Unique-index race on the same idempotency key: return the winner.
    if (
      input.idempotencyKey !== undefined &&
      err instanceof Error &&
      err.message.includes("UNIQUE constraint failed: memory_candidates.idempotency_key")
    ) {
      const winner = db
        .prepare("SELECT * FROM memory_candidates WHERE idempotency_key = ?")
        .get(input.idempotencyKey) as Record<string, unknown>;
      return rowToCandidate(winner);
    }
    throw err;
  }
  store.appendEvent("memory.candidate.created", {
    candidateId,
    scopeId: scope.scopeId,
    kind: core.kind,
    subject: core.subject,
    caller: input.caller !== undefined ? actorKey(input.caller) : null,
  });
  return getCandidateImpl(store, candidateId);
}

export function rowToCandidate(row: Record<string, unknown>): MemoryCandidate {
  const callerRaw = row["caller_json"];
  return {
    candidateId: String(row["candidate_id"]),
    scopeId: String(row["scope_id"]),
    kind: String(row["kind"]) as RecordKind,
    subject: String(row["subject"]),
    content: String(row["content"]),
    contentHash: String(row["content_hash"]),
    provenance: normalizeProvenance(JSON.parse(String(row["provenance_json"]))),
    epistemicClass: String(row["epistemic_class"]) as EpistemicClass,
    confidence: Number(row["confidence"]),
    evidenceRefs: JSON.parse(String(row["evidence_json"])) as EvidenceRef[],
    tags: JSON.parse(String(row["tags_json"])) as string[],
    status: String(row["status"]) as MemoryCandidate["status"],
    createdAt: String(row["created_at"]),
    promotedRecordId:
      row["promoted_record_id"] === null ? null : String(row["promoted_record_id"]),
    reason: String(row["reason"] ?? ""),
    caller:
      callerRaw === null || callerRaw === undefined
        ? null
        : (JSON.parse(String(callerRaw)) as MemoryCandidate["caller"]),
    idempotencyKey:
      row["idempotency_key"] === null || row["idempotency_key"] === undefined
        ? null
        : String(row["idempotency_key"]),
  };
}

function getCandidateImpl(store: MemoryStore, candidateId: string): MemoryCandidate {
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT * FROM memory_candidates WHERE candidate_id = ?")
    .get(candidateId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new NotFoundError(`Candidate '${candidateId}' not found`);
  }
  return rowToCandidate(row);
}

export function getCandidate(store: MemoryStore, candidateId: string): MemoryCandidate {
  return getCandidateImpl(store, candidateId);
}

/** Task 8: the candidate stream, oldest first (ULID order). */
export function listCandidatesImpl(
  store: MemoryStore,
  filter: { scope?: string; status?: MemoryCandidate["status"] | "all"; limit?: number } = {},
): MemoryCandidate[] {
  const db = store.ensureOpen();
  const clauses: string[] = [];
  const params: Array<string | number> = [];
  if (filter.scope !== undefined) {
    const scope = getScopeImpl(store, filter.scope);
    clauses.push("scope_id = ?");
    params.push(scope.scopeId);
  }
  if (filter.status !== undefined && filter.status !== "all") {
    clauses.push("status = ?");
    params.push(filter.status);
  }
  const limit = Math.min(Math.max(filter.limit ?? 100, 1), 1000);
  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const rows = db
    .prepare(
      `SELECT * FROM memory_candidates ${where} ORDER BY created_at ASC, candidate_id ASC LIMIT ?`,
    )
    .all(...params, limit) as Array<Record<string, unknown>>;
  return rows.map(rowToCandidate);
}

export function promoteCandidateImpl(
  store: MemoryStore,
  candidateId: string,
  decision: { actor: ActorInput; policy?: PromotionPolicyName; origin?: string },
): MemoryRecord {
  const candidate = getCandidateImpl(store, candidateId);
  if (candidate.status !== "open") {
    throw new ConflictError(
      `Candidate '${candidateId}' is '${candidate.status}'; only open candidates can be promoted`,
    );
  }
  // Task 35: explicit project/user mutation policy (restricted scopes require
  // an authorized actor, which may include a specifically authorized agent).
  assertMutationAuthorized(store, candidate.scopeId, decision.actor, "promote");
  // Task 9: deterministic policy gate — every promotion must match.
  const assessment = evaluatePromotionImpl(store, candidate);
  const policy = resolvePolicy(assessment, {
    actor: decision.actor,
    requestedPolicy: decision.policy ?? null,
  });
  const record = addRecordImpl(store, {
    scope: candidate.scopeId,
    kind: candidate.kind,
    subject: candidate.subject,
    content: candidate.content,
    actor: candidate.provenance.actor,
    method: candidate.provenance.method,
    epistemicClass: candidate.epistemicClass,
    confidence: candidate.confidence,
    evidenceRefs: candidate.evidenceRefs,
    tags: candidate.tags,
    privacyClass: "internal",
    sourceKind: candidate.provenance.sourceKind,
    derivedFrom: candidate.provenance.derivedFrom,
  });
  const db = store.ensureOpen();
  db.prepare(
    "UPDATE memory_candidates SET status = 'promoted', promoted_record_id = ? WHERE candidate_id = ?",
  ).run(record.recordId, candidateId);
  store.appendEvent("memory.candidate.promoted", withOrigin({
    candidateId,
    recordId: record.recordId,
    policy,
    approvedBy: actorKey(decision.actor),
  }, decision.origin));
  return record;
}

/** Reject a candidate explicitly (task 8 stream hygiene). */
export function rejectCandidateImpl(
  store: MemoryStore,
  candidateId: string,
  input: { actor: ActorInput; reason: string; origin?: string },
): MemoryCandidate {
  const candidate = getCandidateImpl(store, candidateId);
  if (candidate.status !== "open") {
    throw new ConflictError(
      `Candidate '${candidateId}' is '${candidate.status}'; only open candidates can be rejected`,
    );
  }
  if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
    throw new ValidationError("reason is required for rejection");
  }
  // Task 35: an explicit restricted policy may authorize a specific agent;
  // otherwise agents are structurally refused.
  const authorized = assertMutationAuthorized(store, candidate.scopeId, input.actor, "reject_candidate");
  if (!authorized && input.actor.kind === "agent") {
    throw new PromotionForbiddenError(
      "actors of kind 'agent' can never reject candidates either: promotion stream decisions are non-agent",
    );
  }
  const db = store.ensureOpen();
  db.prepare("UPDATE memory_candidates SET status = 'rejected' WHERE candidate_id = ?").run(
    candidateId,
  );
  store.appendEvent("memory.candidate.rejected", withOrigin({
    candidateId,
    actor: actorKey(input.actor),
    reason: input.reason.trim(),
  }, input.origin));
  return getCandidateImpl(store, candidateId);
}

export function expireStaleRecordsImpl(
  store: MemoryStore,
  now: string,
): number {
  if (Number.isNaN(Date.parse(now))) {
    throw new ValidationError("now must be an ISO 8601 timestamp");
  }
  const db = store.ensureOpen();
  const stale = db
    .prepare(
      "SELECT record_id FROM memory_records WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < ?",
    )
    .all(now) as Array<Record<string, unknown>>;
  if (stale.length === 0) return 0;
  db.exec("BEGIN IMMEDIATE;");
  try {
    for (const row of stale) {
      db.prepare(
        "UPDATE memory_records SET status = 'expired', revised_at = ? WHERE record_id = ?",
      ).run(now, String(row["record_id"]));
    }
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }
  store.appendEvent("memory.records.expired", {
    count: stale.length,
    recordIds: stale.map((r) => String(r["record_id"])),
  });
  return stale.length;
}
