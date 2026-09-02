/**
 * Canonical schema validation and privacy enforcement for Memory records.
 *
 * Structural by-reference enforcement: evidence references allow ONLY the
 * fields {engine, ref, note?} — there is no field in which a source payload
 * could be embedded, and unknown fields are rejected. Secret-class privacy
 * is refused outright (secrets belong to the secure credential layer).
 */
import type {
  Actor,
  EpistemicClass,
  EvidenceEngine,
  EvidenceRef,
  PrivacyClass,
  RecordKind,
  RelationHint,
  RelationType,
  SourceKind,
} from "../contracts/types.ts";
import {
  PrivacyViolationError,
  ValidationError,
} from "../contracts/errors.ts";
import { validateAuthority, validateSourceKind } from "./authority.ts";

export const LIMITS = {
  subject: 512,
  content: 32768,
  ref: 512,
  note: 1024,
  tag: 64,
  maxTags: 32,
  maxEvidenceRefs: 32,
  maxRelationHints: 32,
  actorName: 256,
  method: 256,
  projectKey: 128,
  displayName: 256,
  reason: 1024,
  idempotencyKey: 128,
} as const;

const RECORD_KINDS: readonly RecordKind[] = [
  "fact",
  "decision",
  "preference",
  "observation",
  "note",
];

const EPISTEMIC_CLASSES: readonly EpistemicClass[] = [
  "observed",
  "derived",
  "inferred",
  "recommendation",
  "unknown",
];

const PRIVACY_CLASSES: readonly PrivacyClass[] = [
  "public",
  "internal",
  "sensitive",
  "secret",
];

const EVIDENCE_ENGINES: readonly EvidenceEngine[] = [
  "repository_sync",
  "repository_search",
  "study_document",
  "study_lineage_versioning",
  "project_projection",
  "context",
  "midnight_synchronization",
  "performance",
  "analysis",
  "memory",
  "external",
];

const ACTOR_KINDS: readonly string[] = ["human", "agent", "engine", "tool"];

const ISO_LIKE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export interface ValidatedActor extends Actor {}

export interface ValidatedRecordCore {
  subject: string;
  content: string;
  epistemicClass: EpistemicClass;
  confidence: number;
  evidenceRefs: EvidenceRef[];
  relationHints: RelationHint[];
  tags: string[];
  privacyClass: Exclude<PrivacyClass, "secret">;
  validFrom: string | null;
  validUntil: string | null;
}

function fail(message: string): never {
  throw new ValidationError(message);
}

function checkString(
  value: unknown,
  field: string,
  max: number,
  { required = true }: { required?: boolean } = {},
): string | undefined {
  if (value === undefined || value === null) {
    if (required) fail(`${field} is required`);
    return undefined;
  }
  if (typeof value !== "string") fail(`${field} must be a string`);
  if (required && value.length === 0) fail(`${field} must not be empty`);
  if (value.length > max) fail(`${field} exceeds ${max} characters`);
  return value;
}

export function validateActor(input: unknown): ValidatedActor {
  if (input === null || typeof input !== "object") fail("actor must be an object");
  const a = input as Record<string, unknown>;
  const kind = checkString(a["kind"], "actor.kind", 16) as string;
  if (!ACTOR_KINDS.includes(kind)) {
    fail(`actor.kind must be one of ${ACTOR_KINDS.join(", ")}`);
  }
  const name = checkString(a["name"], "actor.name", LIMITS.actorName) as string;
  const agentType = checkString(a["agentType"], "actor.agentType", 64, {
    required: false,
  });
  const known = new Set(["kind", "name", "agentType"]);
  for (const key of Object.keys(a)) {
    if (!known.has(key)) fail(`actor has unknown field '${key}'`);
  }
  const actor: ValidatedActor = { kind: kind as Actor["kind"], name };
  if (agentType !== undefined) actor.agentType = agentType;
  return actor;
}

export function validateEvidenceRef(input: unknown, field: string): EvidenceRef {
  if (input === null || typeof input !== "object") fail(`${field} must be an object`);
  const e = input as Record<string, unknown>;
  const engine = checkString(e["engine"], `${field}.engine`, 64) as string;
  if (!EVIDENCE_ENGINES.includes(engine as EvidenceEngine)) {
    fail(`${field}.engine must be one of ${EVIDENCE_ENGINES.join(", ")}`);
  }
  const ref = checkString(e["ref"], `${field}.ref`, LIMITS.ref) as string;
  const note = checkString(e["note"], `${field}.note`, LIMITS.note, {
    required: false,
  });
  // Task 13: optional source-evidence expiry (ISO 8601).
  const expiresAt = validateTimestampValue(e["expiresAt"], `${field}.expiresAt`);
  for (const key of Object.keys(e)) {
    if (!["engine", "ref", "note", "expiresAt"].includes(key)) {
      fail(
        `${field} has unknown field '${key}': source payloads are stored by reference only`,
      );
    }
  }
  const out: EvidenceRef = { engine: engine as EvidenceEngine, ref };
  if (note !== undefined) out.note = note;
  if (expiresAt !== undefined) out.expiresAt = expiresAt;
  return out;
}

function validateTimestampValue(value: unknown, field: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
    Number.isNaN(Date.parse(value))
  ) {
    fail(`${field} must be an ISO 8601 timestamp`);
  }
  return value;
}

export const RELATION_TYPES: readonly RelationType[] = [
  "related",
  "depends_on",
  "supports",
  "contradicts",
  "derived_from",
  "applies_to",
  "learned_from",
];

export function validateRelationHint(input: unknown, field: string): RelationHint {
  if (input === null || typeof input !== "object") fail(`${field} must be an object`);
  const r = input as Record<string, unknown>;
  const type = checkString(r["type"], `${field}.type`, 32) as string;
  if (!RELATION_TYPES.includes(type as RelationType)) {
    fail(`${field}.type must be one of ${RELATION_TYPES.join(", ")}`);
  }
  const target = checkString(r["target"], `${field}.target`, LIMITS.ref) as string;
  const note = checkString(r["note"], `${field}.note`, LIMITS.note, {
    required: false,
  });
  // Task 21: optional relation attribution (actor/method/capturedAt).
  let provenance: RelationHint["provenance"] = undefined;
  if (r["provenance"] !== undefined && r["provenance"] !== null) {
    const p = r["provenance"] as Record<string, unknown>;
    if (p === null || typeof p !== "object") fail(`${field}.provenance must be an object`);
    const actor = validateActor(p["actor"]);
    const method = checkString(p["method"], `${field}.provenance.method`, LIMITS.method) as string;
    const capturedAt = p["capturedAt"];
    if (
      typeof capturedAt !== "string" ||
      !ISO_LIKE.test(capturedAt) ||
      Number.isNaN(Date.parse(capturedAt))
    ) {
      fail(`${field}.provenance.capturedAt must be an ISO 8601 timestamp`);
    }
    for (const key of Object.keys(p)) {
      if (!["actor", "method", "capturedAt"].includes(key)) {
        fail(`${field}.provenance has unknown field '${key}'`);
      }
    }
    provenance = { actor, method, capturedAt };
  }
  for (const key of Object.keys(r)) {
    if (!["type", "target", "note", "provenance"].includes(key)) {
      fail(`${field} has unknown field '${key}'`);
    }
  }
  const out: RelationHint = {
    type: type as RelationHint["type"],
    target,
  };
  if (note !== undefined) out.note = note;
  if (provenance !== undefined) out.provenance = provenance;
  return out;
}

function validateTimestamp(value: unknown, field: string): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || !ISO_LIKE.test(value) || Number.isNaN(Date.parse(value))) {
    fail(`${field} must be an ISO 8601 timestamp`);
  }
  return value;
}

export interface ValidatedRecordInput {
  kind: RecordKind;
  subject: string;
  content: string;
  epistemicClass: EpistemicClass;
  confidence: number;
  evidenceRefs: EvidenceRef[];
  relationHints: RelationHint[];
  tags: string[];
  privacyClass: Exclude<PrivacyClass, "secret">;
  validFrom: string | null;
  validUntil: string | null;
  observedAt: string | null;
  sourceKind: SourceKind;
  derivedFrom: EvidenceRef | undefined;
  actor: ValidatedActor;
  method: string;
}

/**
 * Validate the canonical record core (Task 3 schema). Throws
 * PrivacyViolationError for secret-class input BEFORE any persistence.
 */
export function validateRecordCore(input: {
  kind: unknown;
  subject: unknown;
  content: unknown;
  epistemicClass: unknown;
  confidence: unknown;
  evidenceRefs?: unknown;
  relationHints?: unknown;
  tags?: unknown;
  privacyClass?: unknown;
  validFrom?: unknown;
  validUntil?: unknown;
  observedAt?: unknown;
  sourceKind?: unknown;
  derivedFrom?: unknown;
  actor: unknown;
  method: unknown;
}): ValidatedRecordInput {
  const kind = checkString(input.kind, "kind", 32) as string;
  if (!RECORD_KINDS.includes(kind as RecordKind)) {
    fail(`kind must be one of ${RECORD_KINDS.join(", ")}`);
  }

  const epistemicClass = checkString(input.epistemicClass, "epistemicClass", 16) as string;
  if (!EPISTEMIC_CLASSES.includes(epistemicClass as EpistemicClass)) {
    fail(`epistemicClass must be one of ${EPISTEMIC_CLASSES.join(", ")}`);
  }

  const confidence = input.confidence;
  if (
    typeof confidence !== "number" ||
    !Number.isFinite(confidence) ||
    confidence < 0 ||
    confidence > 1
  ) {
    fail("confidence must be a number in [0, 1]");
  }

  const privacyRaw =
    input.privacyClass === undefined || input.privacyClass === null
      ? "internal"
      : (checkString(input.privacyClass, "privacyClass", 16) as string);
  if (!PRIVACY_CLASSES.includes(privacyRaw as PrivacyClass)) {
    fail(`privacyClass must be one of ${PRIVACY_CLASSES.join(", ")}`);
  }
  if (privacyRaw === "secret") {
    // Enforced BEFORE any write: secrets never enter the Memory store.
    throw new PrivacyViolationError(
      "privacyClass 'secret' cannot be stored in Memory; use the secure credential layer",
    );
  }

  const validFrom = validateTimestamp(input.validFrom, "validFrom");
  const validUntil = validateTimestamp(input.validUntil, "validUntil");
  if (
    validFrom !== null &&
    validUntil !== null &&
    Date.parse(validUntil) <= Date.parse(validFrom)
  ) {
    fail("validUntil must be after validFrom");
  }

  const evidenceRefs: EvidenceRef[] = [];
  if (input.evidenceRefs !== undefined && input.evidenceRefs !== null) {
    if (!Array.isArray(input.evidenceRefs)) fail("evidenceRefs must be an array");
    if (input.evidenceRefs.length > LIMITS.maxEvidenceRefs) {
      fail(`evidenceRefs exceeds ${LIMITS.maxEvidenceRefs} entries`);
    }
    // Task 6 (Execution 02): reject an exact-duplicate {engine, ref} pair
    // within one array. Keyed on the PAIR, never `ref` alone — two different
    // engines legitimately sharing the same literal ref string must not
    // collide (e.g. Performance's "1" and Study's "1" are distinct evidence).
    const seenPairs = new Set<string>();
    for (const [i, ref] of input.evidenceRefs.entries()) {
      const validated = validateEvidenceRef(ref, `evidenceRefs[${i}]`);
      const pairKey = `${validated.engine} ${validated.ref}`;
      if (seenPairs.has(pairKey)) {
        fail(`evidenceRefs[${i}] duplicates the {engine, ref} of an earlier entry`);
      }
      seenPairs.add(pairKey);
      evidenceRefs.push(validated);
    }
  }

  const relationHints: RelationHint[] = [];
  if (input.relationHints !== undefined && input.relationHints !== null) {
    if (!Array.isArray(input.relationHints)) fail("relationHints must be an array");
    if (input.relationHints.length > LIMITS.maxRelationHints) {
      fail(`relationHints exceeds ${LIMITS.maxRelationHints} entries`);
    }
    for (const [i, hint] of input.relationHints.entries()) {
      relationHints.push(validateRelationHint(hint, `relationHints[${i}]`));
    }
  }

  const tags: string[] = [];
  if (input.tags !== undefined && input.tags !== null) {
    if (!Array.isArray(input.tags)) fail("tags must be an array");
    if (input.tags.length > LIMITS.maxTags) fail(`tags exceeds ${LIMITS.maxTags} entries`);
    for (const tag of input.tags) {
      const t = checkString(tag, "tag", LIMITS.tag) as string;
      tags.push(t);
    }
  }

  // Task 4: provenance source kind and derivation reference.
  const sourceKind =
    input.sourceKind === undefined || input.sourceKind === null
      ? "unknown"
      : validateSourceKind(input.sourceKind);
  const derivedFrom =
    input.derivedFrom === undefined || input.derivedFrom === null
      ? undefined
      : validateEvidenceRef(input.derivedFrom, "provenance.derivedFrom");
  validateAuthority({
    epistemicClass: epistemicClass as EpistemicClass,
    evidenceRefCount: evidenceRefs.length,
    sourceKind,
    hasDerivedFrom: derivedFrom !== undefined,
  });

  const observedAt = validateTimestamp(input.observedAt, "observedAt");

  return {
    kind: kind as RecordKind,
    subject: checkString(input.subject, "subject", LIMITS.subject) as string,
    content: checkString(input.content, "content", LIMITS.content) as string,
    epistemicClass: epistemicClass as EpistemicClass,
    confidence,
    evidenceRefs,
    relationHints,
    tags,
    privacyClass: privacyRaw as Exclude<PrivacyClass, "secret">,
    validFrom,
    validUntil,
    observedAt,
    sourceKind,
    derivedFrom,
    actor: validateActor(input.actor),
    method: checkString(input.method, "method", LIMITS.method) as string,
  };
}

export function validateProjectKey(projectKey: unknown): string {
  const key = checkString(projectKey, "projectKey", LIMITS.projectKey) as string;
  if (!/^[\w][\w.-]*$/.test(key)) {
    fail(
      "projectKey must match [\\w][\\w.-]* (stable slug; never a filesystem path)",
    );
  }
  return key;
}
