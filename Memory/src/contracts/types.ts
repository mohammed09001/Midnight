/**
 * Public value types shared across the Memory Engine contract.
 *
 * Epistemic discipline: observed/source evidence, derived facts, agent
 * inference, recommendation and UNKNOWN remain distinguishable everywhere
 * (Engine Isolation Invariants).
 */

export type EpistemicClass =
  | "observed"
  | "derived"
  | "inferred"
  | "recommendation"
  | "unknown";

/** Machine-readable failure codes surfaced by the engine and its CLI. */
export type MemoryErrorCode =
  | "MEMORY_STORE_UNAVAILABLE"
  | "MEMORY_MIGRATION_FAILED"
  | "MEMORY_VALIDATION_FAILED"
  | "MEMORY_PRIVACY_VIOLATION"
  | "MEMORY_NOT_FOUND"
  | "MEMORY_CONFLICT"
  | "MEMORY_CONTRACT_MISMATCH"
  | "MEMORY_INTAKE_UNAUTHORIZED"
  | "MEMORY_PROMOTION_FORBIDDEN"
  | "MEMORY_CORRECTION_FORBIDDEN"
  | "MEMORY_MUTATION_FORBIDDEN"
  | "MEMORY_EMBEDDINGS_UNAVAILABLE"
  | "MEMORY_EMBEDDINGS_NOT_BUILT";

export type RecordKind =
  | "fact"
  | "decision"
  | "preference"
  | "observation"
  | "note";

export type RecordStatus =
  | "active"
  | "superseded"
  | "retracted"
  | "expired"
  | "archived"
  | "deleted";

/**
 * Privacy classes. `secret` is REFUSED by the engine: secrets belong to the
 * secure credential layer and are never persisted in Memory records.
 */
export type PrivacyClass = "public" | "internal" | "sensitive" | "secret";

/** Agent-neutral actor. No agent implementation is special-cased. */
export type ActorKind = "human" | "agent" | "engine" | "tool";

export interface Actor {
  kind: ActorKind;
  /** Stable display name. Callers reuse the same name to preserve identity. */
  name: string;
  /** Free-form agent/tool family label when kind is "agent"/"tool". */
  agentType?: string;
}

export type EvidenceEngine =
  | "repository_sync"
  | "repository_search"
  | "study_document"
  | "study_lineage_versioning"
  | "project_projection"
  | "context"
  | "midnight_synchronization"
  | "performance"
  | "analysis"
  | "memory"
  | "external";

/**
 * Reference to source/evidence payload owned by ANOTHER engine (or an
 * external system). Payloads are stored BY REFERENCE ONLY; the Memory
 * Engine never embeds another engine's payload content.
 */
export interface EvidenceRef {
  engine: EvidenceEngine;
  /** Stable external reference (id/uri) meaningful to the owning engine. */
  ref: string;
  note?: string;
  /**
   * Task 13: when the SOURCE evidence expires in its owning engine
   * (optional). Expired evidence degrades the record's verifiability but
   * never silently invalidates the record itself.
   */
  expiresAt?: string;
}

/**
 * Bounded typed-relation vocabulary (Task 21). `supersedes` is NOT a hint
 * type: supersession is a first-class lifecycle link (supersedes_id /
 * superseded_by_id) surfaced through `memory.related` — never duplicated as
 * a hint.
 */
export type RelationType =
  | "related"
  | "depends_on"
  | "supports"
  | "contradicts"
  | "derived_from"
  | "applies_to"
  | "learned_from";

/** Who/how/when a typed relation was established (Task 21 attribution). */
export interface RelationProvenance {
  actor: Actor;
  method: string;
  capturedAt: string;
}

export interface RelationHint {
  type: RelationType;
  /**
   * Target MemoryRecord id, `engine:<name>:<ref>` for cross-engine hints, or
   * `entity:<kind>:<name>` for a stable project-entity link (Task 22).
   */
  target: string;
  note?: string;
  /** Attribution: who established the relation, when, and how (optional, backward-compatible). */
  provenance?: RelationProvenance;
}

/**
 * Stable project-entity taxonomy for the derived entity projection (Task 22).
 * `other` classifies `entity:` references whose kind is not in the taxonomy.
 */
export type EntityKind = "component" | "repository" | "technology" | "decision" | "other";

/**
 * Source-kind taxonomy for provenance and evidence authority (Task 4).
 * Authority is determined by WHERE a claim came from, never by how fluent
 * its text is: agent-produced kinds (agent_summary, agent_inference) are
 * structurally capped and can never ground an "observed" record.
 */
export type SourceKind =
  | "user_note"
  | "user_decision"
  | "study_finding"
  | "performance_evidence"
  | "analysis_evidence"
  | "search_session"
  | "repository_evidence"
  | "external_document"
  | "agent_summary"
  | "agent_inference"
  | "unknown";

/** Authority tiers derived from source kind (Task 4). */
export type AuthorityTier =
  | "verified_source"
  | "user_decision"
  | "user_reported"
  | "analysis"
  | "agent_derived"
  | "unattributed";

export interface AuthorityAssessment {
  tier: AuthorityTier;
  /** How the claim is grounded, e.g. "traces to study_finding evidence". */
  basis: string;
  /** True when the tier was capped below what the source kind alone implies. */
  capped: boolean;
  capReasons: string[];
}

export interface ScopeInfo {
  scopeId: string;
  /** Stable, path-independent project key chosen by the caller. */
  projectKey: string;
  displayName: string;
  createdAt: string;
  /** Candidate intake authorization policy (Task 8). */
  intakePolicy: IntakePolicy;
  /** Task 35: mutation authorization policy (promote/revise/delete and other mutations). */
  mutationPolicy: MutationPolicy;
  /** Task 37: content-class privacy policy (export restrictions for excerpts/derived indexes). */
  privacyPolicy: PrivacyPolicy;
  /** Task 13: deletion metadata — deletion cascades to the whole project. */
  deletedAt: string | null;
  deletedBy: string | null;
  deleteReason: string | null;
}

/**
 * Task 35: mutation authorization. Under `open` (default) the structural
 * rules apply (agents are blocked from promote/revise/delete etc.). Under
 * `restricted`, mutations require the actor to be in `allow` — the explicit
 * project/user policy, including explicitly authorizing specific agent actors.
 */
export interface MutationPolicy {
  mode: "open" | "restricted";
  /** Canonical actor keys allowed to mutate when mode is "restricted". */
  allow: string[];
}

/**
 * Task 37: content-class privacy policy. `exportable` lists the content
 * classes that may be exported/excerpted WITHOUT opt-in (`sensitive` always
 * requires opt-in); `forbidSensitive` refuses sensitive content from all
 * exports/excerpts/derived indexes entirely.
 */
export interface ContentPolicy {
  exportable: Array<"public" | "internal">;
  forbidSensitive: boolean;
}

export interface PrivacyPolicy {
  content: ContentPolicy;
}

/**
 * Intake authorization for the candidate pipeline (Task 8): proposals from
 * authorized engines/users only. Caller identity is the canonical actor key
 * ("engine:repository_sync", "user:kim", "agent:worker-a", …).
 */
export interface IntakePolicy {
  mode: "open" | "allowlist";
  /** Caller keys allowed when mode is "allowlist". */
  allow: string[];
}

/** Deterministic promotion policies (Task 9). AI cannot self-promote. */
export type PromotionPolicyName =
  | "explicit_user_decision"
  | "verified_study_fact"
  | "repeated_evidence_backed_lesson";

export interface PromotionAssessment {
  candidateId: string;
  /** True when at least one deterministic policy matches. */
  eligible: boolean;
  matchedPolicies: PromotionPolicyName[];
  /** Human-readable deterministic reasons for each matched/missed policy. */
  reasons: string[];
}

export interface PromotionConfig {
  /** Minimum DISTINCT evidence refs for repeated_evidence_backed_lesson. */
  minDistinctEvidence: number;
  /** Minimum same-subject proposals (candidates+records) in the scope for a
   *  repeated lesson match. */
  minRepeatCount: number;
}

export const DEFAULT_PROMOTION_CONFIG: PromotionConfig = {
  minDistinctEvidence: 2,
  minRepeatCount: 2,
};

export interface MemoryRecord {
  recordId: string;
  contractVersion: string;
  kind: RecordKind;
  subject: string;
  /** Normalized content (whitespace-collapsed, NFC). */
  content: string;
  /** SHA-256 of the normalized content, hex-encoded. */
  contentHash: string;
  scopeId: string;
  provenance: Provenance;
  /** Epistemic class of this record's content. */
  epistemicClass: EpistemicClass;
  /** Confidence in [0,1]. */
  confidence: number;
  evidenceRefs: EvidenceRef[];
  relationHints: RelationHint[];
  tags: string[];
  privacyClass: Exclude<PrivacyClass, "secret">;
  validFrom: string | null;
  validUntil: string | null;
  /**
   * Bi-temporal "valid time": when the claim was observed to hold in the
   * source reality (defaults to record time at write). createdAt/revisedAt
   * remain the "transaction time" of the Memory store itself (Task 5).
   */
  observedAt: string;
  status: RecordStatus;
  revision: number;
  createdAt: string;
  revisedAt: string;
  /** When supersession invalidated this record (Task 5); null unless superseded. */
  supersededAt: string | null;
  /** Explicit reason recorded when superseded (Task 11). */
  supersededReason: string | null;
  /** Task 13: when this record was archived (cold, restorable). */
  archivedAt: string | null;
  /** Task 13: tombstone metadata (content scrubbed, row retained). */
  deletedAt: string | null;
  deletedBy: string | null;
  deleteReason: string | null;
  /** Record id this record supersedes, when part of a supersession chain. */
  supersedesId: string | null;
  /** Record id of the record that superseded this one, if any. */
  supersededById: string | null;
  contradictionGroupId: string | null;
  /** Caller-supplied idempotency key (Task 7): same key replays to the same record. */
  idempotencyKey: string | null;
}

export interface Provenance {
  actor: Actor;
  /** How this content came to be: e.g. "extracted", "summarized", "decided". */
  method: string;
  capturedAt: string;
  /** What kind of source the claim traces to (Task 4 authority model). */
  sourceKind: SourceKind;
  /** Required when sourceKind is agent_summary: what was summarized. */
  derivedFrom?: EvidenceRef;
}

export interface MemoryCandidate {
  candidateId: string;
  scopeId: string;
  kind: RecordKind;
  subject: string;
  content: string;
  contentHash: string;
  provenance: Provenance;
  epistemicClass: EpistemicClass;
  confidence: number;
  evidenceRefs: EvidenceRef[];
  tags: string[];
  status: CandidateStatus;
  createdAt: string;
  promotedRecordId: string | null;
  /** Why this proposal exists (Task 8: required at intake). */
  reason: string;
  /** Who submitted the proposal (may differ from the content producer). */
  caller: Actor | null;
  /** Caller-supplied idempotency key (Task 7). */
  idempotencyKey: string | null;
}

export type CandidateStatus = "open" | "promoted" | "rejected";

export interface ContradictionGroup {
  groupId: string;
  scopeId: string;
  subject: string;
  recordIds: string[];
  createdAt: string;
  /** Task 10: open groups await policy or user resolution. */
  status: ContradictionStatus;
  /** Set when resolved. */
  resolution: ContradictionResolution | null;
}

export type ContradictionStatus = "open" | "resolved";

export interface ContradictionResolution {
  /** "supersede": winner stays active, losers superseded by it.
   *  "retract": losers retracted, winner stays active. */
  action: "supersede" | "retract";
  winnerRecordId: string;
  actor: Actor;
  reason: string;
  resolvedAt: string;
}

/** Task 10: a deterministic incompatible-claim pair awaiting grouping. */
export interface ContradictionPair {
  scopeId: string;
  subject: string;
  recordIdA: string;
  recordIdB: string;
  /** Overlap window of the two claims' validity (ISO strings). */
  overlapStart: string;
  overlapEnd: string | null;
}

export interface EngineEvent {
  eventId: string;
  contractVersion: string;
  type: string;
  payload: unknown;
  createdAt: string;
}

export interface DoctorReport {
  healthy: boolean;
  contractVersion: string;
  storePath: string;
  existed: boolean;
  journalMode: string | null;
  integrity: string | null;
  appliedMigrations: number[];
  eventCount: number;
  errorCode?: MemoryErrorCode;
  errorMessage?: string;
}
