/**
 * memory.related, memory.relation, and memory.explain implementations
 * (Tasks 6 + 21).
 *
 * - related: outgoing relation hints, incoming hints (records whose hints
 *   target this record), supersession-chain links, and contradiction group
 *   membership.
 * - relation (Task 21): attributed add/remove of a single typed relation,
 *   with provenance (who/when/how) on every hint.
 * - explain: full provenance/authority explanation for a record — what it
 *   traces to, how the claim is grounded, and its lifecycle events.
 */
import { authorityOf } from "./authority.ts";
import {
  ConflictError,
  NotFoundError,
  ValidationError,
} from "../contracts/errors.ts";
import type {
  AuthorityAssessment,
  ContradictionGroup,
  ContradictionStatus,
  EngineEvent,
  MemoryRecord,
  RelationHint,
  RelationProvenance,
  RelationType,
} from "../contracts/types.ts";
import { getContradictionGroupOrNull } from "./contradictions.ts";
import { actorKey } from "./ids.ts";
import { getRecordImpl } from "./records.ts";
import { isEvidenceRefExpired } from "./retention.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import { validateActor, validateRelationHint } from "./validation.ts";
import type { ActorInput } from "./records.ts";
import type { MemoryStore } from "./store.ts";

/** Entity-reference prefix used by the derived entity projection (Task 22). */
export const ENTITY_TARGET_PREFIX = "entity:";

export interface RelatedResult {
  recordId: string;
  outgoing: RelationHint[];
  incoming: Array<{ recordId: string; hint: RelationHint }>;
  /** Task 21: record ids this record supersedes (canonical supersession chain). */
  supersedes: string[];
  /** Task 21: record ids that superseded this record (canonical chain). */
  supersededBy: string[];
  contradictionGroup: ContradictionGroup | null;
}

export function relatedImpl(
  store: MemoryStore,
  recordId: string,
  direction: "out" | "in" | "both" = "both",
): RelatedResult {
  const record = getRecordImpl(store, recordId);
  const db = store.ensureOpen();
  const outgoing =
    direction === "in"
      ? []
      : record.relationHints;

  const incoming: Array<{ recordId: string; hint: RelationHint }> = [];
  if (direction !== "out") {
    const candidates = db
      .prepare(
        "SELECT record_id, relation_hints_json FROM memory_records WHERE scope_id = ? AND record_id != ?",
      )
      .all(record.scopeId, recordId) as Array<Record<string, unknown>>;
    for (const row of candidates) {
      const hints = JSON.parse(String(row["relation_hints_json"])) as RelationHint[];
      for (const hint of hints) {
        if (hint.target === recordId) {
          incoming.push({ recordId: String(row["record_id"]), hint });
        }
      }
    }
  }

  const contradictionGroup =
    record.contradictionGroupId !== null
      ? getContradictionGroupOrNull(store, record.contradictionGroupId)
      : null;

  // Task 21: supersession is surfaced through the relations view (canonical
  // chain, never duplicated as hints).
  const supersedes: string[] = [];
  const supersededBy: string[] = [];
  if (record.supersedesId !== null) supersedes.push(record.supersedesId);
  if (record.supersededById !== null) supersededBy.push(record.supersededById);

  return { recordId, outgoing, incoming, supersedes, supersededBy, contradictionGroup };
}

// ---- Task 21: attributed typed-relation management -------------------------

export interface RelationInput {
  type: RelationType;
  /**
   * Target MemoryRecord id, `engine:<name>:<ref>`, or `entity:<kind>:<name>`.
   */
  target: string;
  note?: string;
  /** Who established the relation. */
  actor: ActorInput;
  /** How the relation was established (e.g. "linked", "extracted"). */
  method: string;
}

function assertRelationTargetFormat(target: string): void {
  if (
    target.startsWith("mem_") ||
    target.startsWith("engine:") ||
    target.startsWith(ENTITY_TARGET_PREFIX)
  ) {
    return;
  }
  throw new ValidationError(
    `relation target must be a record id, 'engine:<name>:<ref>', or '${ENTITY_TARGET_PREFIX}<kind>:<name>' (got '${target}')`,
  );
}

function loadRelationHints(store: MemoryStore, recordId: string): RelationHint[] {
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT relation_hints_json FROM memory_records WHERE record_id = ?")
    .get(recordId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    throw new NotFoundError(`Record '${recordId}' not found`);
  }
  return JSON.parse(String(row["relation_hints_json"])) as RelationHint[];
}

function persistRelationHints(
  store: MemoryStore,
  recordId: string,
  hints: RelationHint[],
): void {
  const db = store.ensureOpen();
  db.prepare("UPDATE memory_records SET relation_hints_json = ?, revised_at = ? WHERE record_id = ?").run(
    JSON.stringify(hints),
    new Date().toISOString(),
    recordId,
  );
}

/** Attributed add of a single typed relation (Task 21). */
export function addRelationImpl(
  store: MemoryStore,
  recordId: string,
  input: RelationInput,
): RelatedResult {
  const record = getRecordImpl(store, recordId);
  if (record.status === "deleted") {
    throw new ConflictError(
      `Record '${recordId}' is tombstoned; relations cannot be added to deleted records`,
    );
  }
  const hint = validateRelationHint(
    {
      type: input.type,
      target: input.target,
      ...(input.note !== undefined ? { note: input.note } : {}),
    },
    "relation",
  );
  assertRelationTargetFormat(hint.target);

  // A record-id target must exist in the same scope and not be the record itself.
  if (hint.target.startsWith("mem_")) {
    if (hint.target === recordId) {
      throw new ValidationError("a record cannot have a relation to itself");
    }
    const target = getRecordImpl(store, hint.target);
    if (target.scopeId !== record.scopeId) {
      throw new ValidationError(
        `relation target '${hint.target}' is not in the same scope as '${recordId}'`,
      );
    }
    if (target.status === "deleted") {
      throw new ValidationError(
        `relation target '${hint.target}' is tombstoned`,
      );
    }
  }

  const actor = validateActor(input.actor);
  const method = input.method.trim();
  if (method.length === 0) {
    throw new ValidationError("relation method is required (how the relation was established)");
  }
  const provenance: RelationProvenance = {
    actor,
    method,
    capturedAt: new Date().toISOString(),
  };

  const hints = loadRelationHints(store, recordId);
  if (hints.some((h) => h.type === hint.type && h.target === hint.target)) {
    throw new ConflictError(
      `relation '${hint.type}' → '${hint.target}' already exists on '${recordId}'`,
    );
  }
  if (hints.length >= 32) {
    throw new ValidationError("relationHints exceeds 32 entries");
  }
  hints.push({ ...hint, provenance });
  persistRelationHints(store, recordId, hints);
  store.appendEvent("memory.relation.added", {
    recordId,
    type: hint.type,
    target: hint.target,
    actor: actorKey(actor),
  });
  return relatedImpl(store, recordId);
}

/** Attributed removal of a single typed relation (idempotent — missing is a typed not-found). */
export function removeRelationImpl(
  store: MemoryStore,
  recordId: string,
  input: { type: RelationType; target: string },
): RelatedResult {
  const hint = validateRelationHint(
    { type: input.type, target: input.target },
    "relation",
  );
  const hints = loadRelationHints(store, recordId);
  const idx = hints.findIndex((h) => h.type === hint.type && h.target === hint.target);
  if (idx === -1) {
    throw new NotFoundError(
      `relation '${hint.type}' → '${hint.target}' not found on '${recordId}'`,
    );
  }
  hints.splice(idx, 1);
  persistRelationHints(store, recordId, hints);
  store.appendEvent("memory.relation.removed", {
    recordId,
    type: hint.type,
    target: hint.target,
  });
  return relatedImpl(store, recordId);
}

/** Task 20: currently-valid check, ported from currentRecordsImpl's SQL clauses. */
function isCurrentlyValid(record: MemoryRecord, at: string): boolean {
  return (
    record.status === "active" &&
    (record.validFrom === null || record.validFrom <= at) &&
    (record.validUntil === null || record.validUntil > at)
  );
}

/** Task 20: deterministic evidence-completeness/freshness findings. */
export function evidenceGapsOf(record: MemoryRecord, at: string): string[] {
  const gaps: string[] = [];
  if (record.evidenceRefs.length === 0) {
    gaps.push("no evidenceRefs: this record has no traceable source evidence");
  }
  for (const ref of record.evidenceRefs) {
    if (isEvidenceRefExpired(ref, at)) {
      gaps.push(
        `evidenceRef '${ref.engine}:${ref.ref}' expired at ${ref.expiresAt as string}`,
      );
    }
  }
  return gaps;
}

export interface ExplainResult {
  recordId: string;
  contractVersion: string;
  subject: string;
  epistemicClass: MemoryRecord["epistemicClass"];
  confidence: number;
  /** Authority assessment: structural, never content-fluency based. */
  authority: AuthorityAssessment;
  provenance: MemoryRecord["provenance"];
  evidenceRefs: MemoryRecord["evidenceRefs"];
  /** Task 20: what's missing/stale about the evidence backing this claim. */
  evidenceGaps: string[];
  revision: number;
  createdAt: string;
  observedAt: string;
  status: MemoryRecord["status"];
  validFrom: string | null;
  validUntil: string | null;
  /** Task 20: validity-window answer, evaluated at a given instant. */
  validity: { at: string; currentlyValid: boolean };
  supersedesId: string | null;
  supersededById: string | null;
  /** Task 20: contradiction-group membership/status, if any. */
  contradiction: {
    groupId: string | null;
    status: ContradictionStatus | null;
    groupSize: number | null;
  };
  /** Lifecycle events that touched this record (bounded scan, newest first). */
  events: EngineEvent[];
}

export function explainImpl(
  store: MemoryStore,
  recordId: string,
  at: string = new Date().toISOString(),
): ExplainResult {
  assertIsoTimestamp(at, "at");
  const record = getRecordImpl(store, recordId);
  const authority = authorityOf(record.provenance, record.epistemicClass);
  const events = store
    .listEvents(500)
    .filter((e) => {
      const payload = e.payload as Record<string, unknown> | null;
      if (payload === null || typeof payload !== "object") return false;
      const ids = [payload["recordId"], payload["supersededById"]];
      return ids.some((v) => v === recordId);
    });
  const group =
    record.contradictionGroupId !== null
      ? getContradictionGroupOrNull(store, record.contradictionGroupId)
      : null;
  return {
    recordId: record.recordId,
    contractVersion: record.contractVersion,
    subject: record.subject,
    epistemicClass: record.epistemicClass,
    confidence: record.confidence,
    authority,
    provenance: record.provenance,
    evidenceRefs: record.evidenceRefs,
    evidenceGaps: evidenceGapsOf(record, at),
    revision: record.revision,
    createdAt: record.createdAt,
    observedAt: record.observedAt,
    status: record.status,
    validFrom: record.validFrom,
    validUntil: record.validUntil,
    validity: { at, currentlyValid: isCurrentlyValid(record, at) },
    supersedesId: record.supersedesId,
    supersededById: record.supersededById,
    contradiction: {
      groupId: record.contradictionGroupId,
      status: group?.status ?? null,
      groupSize: group?.recordIds.length ?? null,
    },
    events,
  };
}
