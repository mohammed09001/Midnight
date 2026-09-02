/**
 * Project user notes (Task 32).
 *
 * Models EXPLICIT USER-AUTHORED notes and decisions as first-class MEMORY
 * RECORDS with STRONGER SUBJECTIVE AUTHORITY within their declared scope.
 *
 * - First-class records: the user IS the authority, so a user note/decision is
 *   written directly as a durable record (no candidate gate, no promotion) —
 *   unlike agent/engine output, which must flow through the candidate intake.
 * - Explicit user-authored: the producing actor MUST be of kind `human`;
 *   agents/engines cannot use this surface (they propose via intake).
 * - Stronger subjective authority: a user-authored DECISION carries the
 *   `user_decision` source kind → `user_decision` authority tier (above a
 *   general `user_note`, below verified external evidence). A note carries
 *   `user_note` → `user_reported`. Both are scoped to the project the user
 *   declares.
 * - Epistemic honesty: default `derived` (the user's own subjective
 *   statement — no external evidence required); a user may still declare
 *   `observed` (which then requires evidence refs, per the authority model).
 */
import { ValidationError } from "../contracts/errors.ts";
import type {
  EpistemicClass,
  EvidenceRef,
  MemoryRecord,
  RelationHint,
} from "../contracts/types.ts";
import { addRecordImpl, type ActorInput } from "./records.ts";
import type { MemoryStore } from "./store.ts";

export const USER_NOTE_SOURCE_KIND = "user_note" as const;
export const USER_DECISION_SOURCE_KIND = "user_decision" as const;

export interface UserNoteInput {
  /** Project (scope id or project key) the note/decision applies to. */
  scope: string;
  subject: string;
  content: string;
  /** Explicit user-authored type: a note or a decision. */
  kind?: "note" | "decision";
  /** REQUIRED: the human author (agents/engines must use the intake pipeline). */
  actor: ActorInput;
  method?: string;
  epistemicClass?: EpistemicClass;
  confidence?: number;
  tags?: string[];
  relationHints?: RelationHint[];
  evidenceRefs?: EvidenceRef[];
  privacyClass?: "public" | "internal" | "sensitive";
  validFrom?: string;
  validUntil?: string;
  observedAt?: string;
  idempotencyKey?: string;
}

/**
 * Write an explicit user-authored note/decision as a first-class record with
 * user subjective authority within the declared scope.
 */
export function addUserNoteImpl(store: MemoryStore, input: UserNoteInput): MemoryRecord {
  if (input.actor === null || typeof input.actor !== "object" || input.actor.kind !== "human") {
    throw new ValidationError(
      "user notes/decisions require an actor of kind 'human': explicit user authorship; agents and engines must use the candidate intake pipeline",
    );
  }
  if (input.kind !== undefined && input.kind !== "note" && input.kind !== "decision") {
    throw new ValidationError("kind must be 'note' or 'decision'");
  }
  const isDecision = input.kind === "decision";
  return addRecordImpl(store, {
    scope: input.scope,
    kind: isDecision ? "decision" : "note",
    subject: input.subject,
    content: input.content,
    actor: input.actor,
    method: input.method ?? (isDecision ? "user_decision" : "user_note"),
    epistemicClass: input.epistemicClass ?? "derived",
    confidence: input.confidence ?? 0.85,
    evidenceRefs: input.evidenceRefs,
    relationHints: input.relationHints,
    tags: input.tags,
    privacyClass: input.privacyClass,
    validFrom: input.validFrom,
    validUntil: input.validUntil,
    observedAt: input.observedAt,
    sourceKind: isDecision ? USER_DECISION_SOURCE_KIND : USER_NOTE_SOURCE_KIND,
    idempotencyKey: input.idempotencyKey,
  });
}