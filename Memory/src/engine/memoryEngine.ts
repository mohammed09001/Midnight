/**
 * MemoryEngine — the single public API surface (product boundary) of the
 * Midnight Memory Engine.
 *
 * Boundary rules enforced here (see docs/BOUNDARY.md):
 * - All durable state lives in the MemoryStore; no in-memory shadow state.
 * - Sibling-engine payloads are referenced, never read from sibling stores
 *   or embedded in this store.
 * - Everything is usable from terminal/tool surfaces; no game dependency.
 * - Every state change emits a versioned engine event (observability).
 */
import type {
  ContradictionGroup,
  ContradictionPair,
  ContradictionResolution,
  ContradictionStatus,
  DoctorReport,
  EngineEvent,
  EvidenceRef,
  IntakePolicy,
  MemoryCandidate,
  MemoryRecord,
  MutationPolicy,
  PromotionAssessment,
  PromotionPolicyName,
  RelationType,
  ScopeInfo,
  SourceKind,
  AuthorityAssessment,
} from "../contracts/types.ts";
import type { ContradictionResolutionInput } from "./contradictions.ts";
import type { RelationInput, RelatedResult } from "./relations.ts";
import type { EntityProjection } from "./entities.ts";
import type {
  EmbeddingBuildOptions,
  EmbeddingProjection,
  EmbeddingProjectionStatus,
  EmbeddingProvider,
  SemanticSearchResult,
} from "./embeddings.ts";
import type { GraphProjection, GraphTraversal, TraversalOptions } from "./graph.ts";
import type { HybridSearchOptions, HybridSearchResult } from "./fusion.ts";
import type { ProjectionIntegrityReport, RebuildResult, RepairResult } from "./projections.ts";
import type { PerformanceLesson, PerformanceProposalResult } from "./performance.ts";
import type { StudyProposal, StudyProposalResult } from "./study.ts";
import type { AnalysisFinding, AnalysisProposalResult } from "./analysis.ts";
import type { SearchSession, SearchSessionInput } from "./searchHistory.ts";
import type { ContextQuery, ContextQueryResult } from "./context.ts";
import type { UserNoteInput } from "./userNotes.ts";
import type { ContextExcerptQuery, ExcerptPack, MemoryExcerptOptions, ContextExcerpt } from "./excerpts.ts";
import {
  assertIsolationScope,
  policyStatusImpl,
  setScopePrivacyPolicyImpl,
  type PolicyStatus,
  type ProjectIsolation,
  type PrivacyPolicy,
} from "./privacy.ts";
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import { MemoryStore } from "./store.ts";

export const DEFAULT_STORE_RELATIVE_PATH = "data/memory-engine.db";

/**
 * Repo-local by default; override with MIDNIGHT_MEMORY_STORE for deployments.
 * The legacy LIBRARY_MEMORY_STORE var is still honored (deprecated) when
 * MIDNIGHT_MEMORY_STORE is unset, so a pre-existing deployment env doesn't
 * silently fall back to the default path.
 */
export function defaultStorePath(): string {
  const primary = process.env["MIDNIGHT_MEMORY_STORE"];
  if (primary !== undefined) return primary;
  const legacy = process.env["LIBRARY_MEMORY_STORE"];
  if (legacy !== undefined) {
    process.stderr.write("warning: LIBRARY_MEMORY_STORE is deprecated; use MIDNIGHT_MEMORY_STORE instead\n");
    return legacy;
  }
  return DEFAULT_STORE_RELATIVE_PATH;
}

export interface MemoryEngineOptions {
  storePath?: string;
}

export class MemoryEngine {
  readonly contractVersion = MEMORY_ENGINE_CONTRACT_VERSION;
  readonly store: MemoryStore;
  /** Optional, provider-neutral embedding provider (Task 23). In-memory only. */
  private embeddingProvider: EmbeddingProvider | null = null;
  /** Task 37: project/workspace isolation (strict by default — local/self-hosted). */
  private projectIsolation: ProjectIsolation = "strict";

  constructor(options: MemoryEngineOptions = {}) {
    this.store = new MemoryStore(options.storePath ?? defaultStorePath());
  }

  /** Task 37: set project isolation (strict requires a scope on read/query surfaces). */
  setProjectIsolation(mode: ProjectIsolation): void {
    this.projectIsolation = mode;
  }

  /** Task 37: configure the scope's content-class privacy policy. */
  setScopePrivacyPolicy(scopeOrProjectKey: string, policy: PrivacyPolicy): ScopeInfo {
    setScopePrivacyPolicyImpl(this.store, scopeOrProjectKey, policy);
    return getScopeImpl(this.store, scopeOrProjectKey);
  }

  /** Task 37: report the policy status — self-hosted default + isolation + per-scope content policies. */
  policyStatus(): PolicyStatus {
    return policyStatusImpl(this.store, this.projectIsolation);
  }

  /** Task 23: inject a provider-neutral embedding provider (null clears it). */
  setEmbeddingProvider(provider: EmbeddingProvider | null): void {
    this.embeddingProvider = provider;
  }

  open(): this {
    this.store.open();
    return this;
  }

  close(): void {
    this.store.close();
  }

  doctor(): DoctorReport {
    const health = this.store.doctor();
    let eventCount = 0;
    if (health.healthy) {
      eventCount = this.store.countEvents();
    }
    return {
      healthy: health.healthy,
      contractVersion: this.contractVersion,
      storePath: this.store.storePath,
      existed: !this.store.created,
      journalMode: health.journalMode,
      integrity: health.integrity,
      appliedMigrations: health.healthy ? this.store.appliedMigrationVersions() : [],
      eventCount,
      ...(health.errorCode !== undefined
        ? {
            errorCode: health.errorCode as DoctorReport["errorCode"],
            errorMessage: health.errorMessage,
          }
        : {}),
    };
  }

  listEvents(limit: number = 50): EngineEvent[] {
    return this.store.listEvents(limit);
  }

  // ---- Task 2: scopes and stable identities --------------------------------

  createScope(projectKey: string, displayName: string): ScopeInfo {
    return createScopeImpl(this.store, projectKey, displayName);
  }

  getScope(scopeOrProjectKey: string): ScopeInfo {
    return getScopeImpl(this.store, scopeOrProjectKey);
  }

  registerContradiction(
    scopeOrProjectKey: string,
    subject: string,
    recordIds: string[],
  ): ContradictionGroup {
    return registerContradictionImpl(this.store, scopeOrProjectKey, subject, recordIds);
  }

  // ---- Task 10: contradiction detection, grouping, and resolution -----------

  detectContradictions(scopeOrProjectKey: string): ContradictionPair[] {
    return findContradictionPairsImpl(this.store, scopeOrProjectKey);
  }

  listOpenContradictions(scopeOrProjectKey: string): ContradictionGroup[] {
    return listOpenContradictionsImpl(this.store, scopeOrProjectKey);
  }

  resolveContradiction(
    groupId: string,
    input: ContradictionResolutionInput,
  ): ContradictionGroup {
    return resolveContradictionImpl(this.store, groupId, input);
  }

  // ---- Task 3: canonical record schema and lifecycle ------------------------

  addRecord(input: RecordInput): MemoryRecord {
    return addRecordImpl(this.store, input);
  }

  getRecord(recordId: string): MemoryRecord {
    return getRecordImpl(this.store, recordId);
  }

  reviseRecord(
    recordId: string,
    input: {
      content: string;
      actor: ActorInput;
      method: string;
      reason: string;
      sourceKind?: SourceKind;
      derivedFrom?: EvidenceRef;
      origin?: string;
    },
  ): MemoryRecord {
    return reviseRecordImpl(this.store, recordId, input);
  }

  supersedeRecord(
    recordId: string,
    input: {
      content: string;
      actor: ActorInput;
      method: string;
      reason: string;
      sourceKind?: SourceKind;
      derivedFrom?: EvidenceRef;
      origin?: string;
    },
  ): MemoryRecord {
    return supersedeRecordImpl(this.store, recordId, input);
  }

  retractRecord(recordId: string, input: { actor: ActorInput; reason: string; origin?: string }): MemoryRecord {
    return retractRecordImpl(this.store, recordId, input);
  }

  searchRecords(filter: RecordSearchFilter): MemoryRecord[] {
    assertIsolationScope(this.projectIsolation, filter.scope, "memory.search");
    return searchRecordsImpl(this.store, filter);
  }

  // ---- Tasks 14–16: deterministic retrieval baseline ------------------------

  lexicalSearch(
    query: string,
    filter: LexicalSearchFilter = {},
  ): LexicalSearchResult {
    assertIsolationScope(this.projectIsolation, filter.scope, "memory.lexical");
    return lexicalSearchImpl(this.store, query, filter);
  }

  rebuildSearchIndex(): { rebuilt: true } {
    return rebuildSearchIndexImpl(this.store);
  }

  currentRecords(query: CurrentQuery): MemoryRecord[] {
    return currentRecordsImpl(this.store, query);
  }

  decisionTimeline(scopeOrProjectKey: string, subject: string): TimelineEntry[] {
    return decisionTimelineImpl(this.store, scopeOrProjectKey, subject);
  }

  // ---- Task 20: memory.explain enrichment + retrieval traces ---------------

  /** Full provenance/authority/validity/contradiction/evidence-gap explanation. */
  explainRecord(recordId: string, at?: string): ExplainResult {
    return explainImpl(this.store, recordId, at);
  }

  /** `searchRecords`, plus which filters applied and why each record matched. */
  searchRecordsTraced(filter: RecordSearchFilter): { records: MemoryRecord[]; trace: SearchTrace } {
    assertIsolationScope(this.projectIsolation, filter.scope, "memory.search");
    return searchRecordsTracedImpl(this.store, filter);
  }

  /** `currentRecords`, plus which filters applied and why each record matched. */
  currentRecordsTraced(query: CurrentQuery): { records: MemoryRecord[]; trace: CurrentTrace } {
    return currentRecordsTracedImpl(this.store, query);
  }

  /** `queryRecordsAsOf`, plus which filters applied and why each record matched. */
  queryRecordsAsOfTraced(query: AsOfQuery): { records: MemoryRecord[]; trace: AsOfTrace } {
    assertIsolationScope(this.projectIsolation, query.scope, "memory.search asOf");
    return queryRecordsAsOfTracedImpl(this.store, query);
  }

  // ---- Tasks 17–19: provenance ranking, dedup, explainable fusion --------

  /** Task 17: provenance-aware ranked search with per-record breakdowns. */
  rankedSearch(
    query: string,
    options: { scope?: string; limit?: number; at?: string } = {},
  ): RankedSearchResult {
    return rankedSearchImpl(this.store, query, options);
  }

  // ---- Tasks 21–22: typed relations with provenance + entity projection ---

  /** Task 21: attributed add of a single typed relation. */
  addRelation(recordId: string, input: RelationInput): RelatedResult {
    return addRelationImpl(this.store, recordId, input);
  }

  /** Task 21: attributed removal of a single typed relation. */
  removeRelation(recordId: string, input: { type: RelationType; target: string }): RelatedResult {
    return removeRelationImpl(this.store, recordId, input);
  }

  /** Task 22: build the derived, versioned entity projection for a scope. */
  entityProjection(scopeOrProjectKey: string): EntityProjection {
    return entityProjectionImpl(this.store, scopeOrProjectKey);
  }

  /** Task 22: force a rebuild of the entity projection (observability). */
  rebuildEntityProjection(scopeOrProjectKey: string): EntityProjection {
    return rebuildEntityProjectionImpl(this.store, scopeOrProjectKey);
  }

  // ---- Task 24: optional relationship-graph projection ---------------------

  /** Task 24: build the derived relationship-graph projection for a scope. */
  graphProjection(scopeOrProjectKey: string): GraphProjection {
    return graphProjectionImpl(this.store, scopeOrProjectKey);
  }

  /** Task 24: force a rebuild of the graph projection (observability). */
  rebuildGraphProjection(scopeOrProjectKey: string): GraphProjection {
    return rebuildGraphProjectionImpl(this.store, scopeOrProjectKey);
  }

  /** Task 24: bounded traversal of the graph projection from a node. */
  traverseGraph(
    scopeOrProjectKey: string,
    start: string,
    options: TraversalOptions = {},
  ): GraphTraversal {
    return traverseGraphImpl(this.store, scopeOrProjectKey, start, options);
  }

  // ---- Task 23: optional semantic embedding projection ---------------------

  /** Task 23: status of the derived embedding projection (unavailable/not_built/built). */
  embeddingProjectionStatus(scopeOrProjectKey: string): EmbeddingProjectionStatus {
    return embeddingProjectionStatusImpl(this.store, this.embeddingProvider, scopeOrProjectKey);
  }

  /** Task 23: build the derived embedding projection for a scope (privacy-gated). */
  buildEmbeddingProjection(
    scopeOrProjectKey: string,
    options: EmbeddingBuildOptions = {},
  ): EmbeddingProjection {
    return buildEmbeddingProjectionImpl(this.store, this.embeddingProvider, scopeOrProjectKey, options);
  }

  /** Task 23: completely rebuild the embedding projection (model/version recorded). */
  rebuildEmbeddingProjection(
    scopeOrProjectKey: string,
    options: EmbeddingBuildOptions = {},
  ): EmbeddingProjection {
    return rebuildEmbeddingProjectionImpl(this.store, this.embeddingProvider, scopeOrProjectKey, options);
  }

  /** Task 23: semantic search over the built projection (cosine ranking). */
  semanticSearch(
    query: string,
    options: { scope?: string; limit?: number } = {},
  ): SemanticSearchResult {
    assertIsolationScope(this.projectIsolation, options.scope, "memory.semantic");
    return semanticSearchImpl(this.store, this.embeddingProvider, query, options);
  }

  /** Task 18: analyze a proposed claim for duplicates vs corroboration. */
  analyzeDuplicates(
    scopeOrProjectKey: string,
    proposal: { subject: string; content: string; evidenceRefs?: EvidenceRef[] },
  ): DuplicateAnalysis {
    return analyzeProposalImpl(this.store, scopeOrProjectKey, proposal);
  }

  /** Task 18: scan a scope's candidate stream for exact/near duplicates. */
  findCandidateDuplicates(
    scopeOrProjectKey: string,
    filter: { status?: MemoryCandidate["status"] | "all"; limit?: number } = {},
  ): Array<{ candidate: MemoryCandidate; analysis: DuplicateAnalysis }> {
    return findCandidateDuplicatesImpl(this.store, scopeOrProjectKey, filter);
  }

  /** Task 19: explainable multi-signal fused search. */
  fusedSearch(query: string, options: FusionOptions = {}): FusedSearchResult {
    return fusedSearchImpl(this.store, query, options);
  }

  /** Task 25: hybrid lexical + semantic + relation retrieval with path explanations. */
  hybridSearch(query: string, options: HybridSearchOptions = {}): HybridSearchResult {
    return hybridSearchImpl(this.store, this.embeddingProvider, query, options);
  }

  // ---- Task 26: unified index rebuild + corruption recovery ---------------

  /** Task 26: verify every derived projection against canonical records. */
  checkProjectionIntegrity(scopeOrProjectKey?: string): ProjectionIntegrityReport {
    return checkProjectionIntegrityImpl(this.store, this.embeddingProvider, scopeOrProjectKey);
  }

  /** Task 26: rebuild all derived projections from canonical records. */
  rebuildAllProjections(options: { scope?: string; includeSensitive?: boolean } = {}): RebuildResult {
    return rebuildAllProjectionsImpl(this.store, this.embeddingProvider, options);
  }

  /** Task 26: detect corrupted projections and rebuild only those. */
  repairProjections(options: { scope?: string; includeSensitive?: boolean } = {}): RepairResult {
    return repairProjectionsImpl(this.store, this.embeddingProvider, options);
  }

  // ---- Task 27: Performance → Memory proposals -----------------------------

  /** Task 27: bounded, evidence-backed Performance lessons into the intake stream. */
  proposePerformanceLessons(
    scopeOrProjectKey: string,
    lessons: PerformanceLesson[],
    options: { caller?: ActorInput } = {},
  ): PerformanceProposalResult {
    return proposePerformanceLessonsImpl(this.store, scopeOrProjectKey, lessons, options);
  }

  /** Task 28: bounded Study findings + user annotations into the intake stream. */
  proposeStudy(
    scopeOrProjectKey: string,
    proposals: StudyProposal[],
    options: { caller?: ActorInput } = {},
  ): StudyProposalResult {
    return proposeStudyImpl(this.store, scopeOrProjectKey, proposals, options);
  }

  /** Task 29: bounded, evidence-linked Analysis architectural findings into the intake stream. */
  proposeAnalysis(
    scopeOrProjectKey: string,
    findings: AnalysisFinding[],
    options: { caller?: ActorInput } = {},
  ): AnalysisProposalResult {
    return proposeAnalysisImpl(this.store, scopeOrProjectKey, findings, options);
  }

  // ---- Task 30: Search → Memory history ------------------------------------

  /** Task 30: store a search intent/session as retrieval context (never promoted). */
  recordSearchSession(input: SearchSessionInput): SearchSession {
    return recordSearchSessionImpl(this.store, input);
  }

  /** Task 30: list stored search-session history, newest first. */
  listSearchSessions(filter: { scope?: string; limit?: number } = {}): SearchSession[] {
    return listSearchSessionsImpl(this.store, filter);
  }

  /** Task 30: fetch a single search session by id. */
  getSearchSession(searchSessionId: string): SearchSession {
    return getSearchSessionImpl(this.store, searchSessionId);
  }

  /** Task 31: bounded context-oriented query with size/time/project filters + provenance-rich results. */
  contextQuery(query: ContextQuery): ContextQueryResult {
    return contextQueryImpl(this.store, query);
  }

  /** Task 32: write an explicit user-authored note/decision as a first-class record. */
  addUserNote(input: UserNoteInput): MemoryRecord {
    return addUserNoteImpl(this.store, input);
  }

  /** Task 33: related view — outgoing/incoming hints, supersession, contradiction group. */
  related(recordId: string, direction: "out" | "in" | "both" = "both"): RelatedResult {
    return relatedImpl(this.store, recordId, direction);
  }

  /** Task 36: build a bounded, context-safe excerpt pack for a scope. */
  contextExcerpts(query: ContextExcerptQuery): ExcerptPack {
    return buildContextExcerptsImpl(this.store, query);
  }

  /** Task 36: a single context-safe record excerpt (sensitive content redacted by default). */
  memoryExcerpt(recordId: string, options: MemoryExcerptOptions = {}): ContextExcerpt {
    return memoryExcerptImpl(this.store, recordId, options);
  }

  /** Task 38: content-trust boundary — retrieved content is DATA, never policy. */
  contentBoundaryStatus(): ContentBoundaryStatus {
    return contentBoundaryStatusImpl(this.store);
  }

  /** Task 38: label a value as untrusted data before handing it to a host. */
  contentAsData<T>(value: T): { trust: "untrusted-data"; data: T } {
    return asUntrustedData(value);
  }

  // ---- Task 39: backup, restore, and integrity checks ----------------------

  /** Task 39: export canonical Memory + projection-rebuild metadata (with checksum). */
  backup(): BackupBundle {
    return backupImpl(this.store);
  }

  /** Task 39: write the canonical backup bundle to a file. */
  backupToFile(path: string): BackupBundle {
    return backupToFileImpl(this.store, path);
  }

  /** Task 39: verify a backup bundle's checksum + structural references. */
  verifyBackup(bundle: unknown): { valid: boolean; errors: string[] } {
    return verifyBackupImpl(bundle);
  }

  /** Task 39: restore a verified bundle into a FRESH store (full snapshot). */
  restoreBundle(bundle: unknown): { restored: true; scopes: number; records: number; candidates: number } {
    return restoreBundleImpl(this.store, bundle);
  }

  /** Task 39: verify canonical foreign references in the live store. */
  verifyStoreReferences(): StoreReferenceReport {
    return verifyStoreReferencesImpl(this.store);
  }

  // ---- Task 40: Memory health + retrieval quality ---------------------------

  /** Task 40: operational health + retrieval-quality report. */
  memoryHealth(): MemoryHealthMetrics {
    return memoryHealthImpl(this.store);
  }

  // ---- Task 42: frozen qualification corpora ---------------------------------

  /** Task 42: materialize the frozen qualification corpus (replay-safe). */
  buildQualificationCorpus(options: CorpusOptions = {}): CorpusBuildResult {
    return buildQualificationCorpusImpl(this, this.store, options);
  }

  /** Task 42: verify the frozen corpus expectations (read-only, deterministic). */
  verifyQualificationCorpus(options: CorpusOptions = {}): QualificationReport {
    return verifyQualificationCorpusImpl(this, options);
  }

  // ---- Task 43: retrieval evaluation -----------------------------------------

  /** Task 43: precision/recall-style retrieval evaluation with transparent baselines. */
  evaluateRetrieval(options: EvaluationOptions = {}): RetrievalEvaluationReport {
    return evaluateRetrievalImpl(this, options);
  }

  // ---- Task 44: contradiction/supersession qualification ----------------------

  /** Task 44: qualify lineage invariants — history queryable, truth resolved, no overwrite. */
  qualifyContradictionSupersession(): LineageQualificationReport {
    return qualifyContradictionSupersessionImpl(this);
  }

  // ---- Task 45: crash/rebuild/deletion qualification ---------------------------

  /** Task 45: exercise crash, corruption, restore, and deletion recovery on scratch stores. */
  qualifyRecovery(options: RecoveryQualificationOptions = {}): RecoveryQualificationReport {
    return qualifyRecoveryImpl(this, options);
  }

  addCandidate(
    input: Omit<
      RecordInput,
      "relationHints" | "privacyClass" | "validFrom" | "validUntil" | "observedAt"
    > & {
      /** Task 8: required proposal reason. */
      reason: string;
      /** Task 8: submitting caller (required under allowlist intake). */
      caller?: ActorInput;
      /** Task 7: replay-safe intake. */
      idempotencyKey?: string;
    },
  ): MemoryCandidate {
    return addCandidateImpl(this.store, input);
  }

  promoteCandidate(
    candidateId: string,
    decision: { actor: ActorInput; policy?: PromotionPolicyName; origin?: string },
  ): MemoryRecord {
    return promoteCandidateImpl(this.store, candidateId, decision);
  }

  rejectCandidate(
    candidateId: string,
    input: { actor: ActorInput; reason: string; origin?: string },
  ): MemoryCandidate {
    return rejectCandidateImpl(this.store, candidateId, input);
  }

  listCandidates(
    filter: { scope?: string; status?: MemoryCandidate["status"] | "all"; limit?: number } = {},
  ): MemoryCandidate[] {
    return listCandidatesImpl(this.store, filter);
  }

  evaluatePromotion(candidateId: string): PromotionAssessment {
    const candidate = getCandidate(this.store, candidateId);
    return evaluatePromotionImpl(this.store, candidate);
  }

  setScopeIntakePolicy(scopeOrProjectKey: string, policy: IntakePolicy): ScopeInfo {
    return setScopeIntakePolicyImpl(this.store, scopeOrProjectKey, policy);
  }

  /** Task 35: configure the mutation authorization policy for a scope. */
  setScopeMutationPolicy(scopeOrProjectKey: string, policy: MutationPolicy): ScopeInfo {
    return setScopeMutationPolicyImpl(this.store, scopeOrProjectKey, policy);
  }

  expireStaleRecords(now: string = new Date().toISOString()): number {
    return expireStaleRecordsImpl(this.store, now);
  }

  // ---- Task 5: temporal validity and historical truth -----------------------

  getRecordHistory(recordId: string): RecordHistory {
    return getRecordHistoryImpl(this.store, recordId);
  }

  queryRecordsAsOf(query: AsOfQuery): MemoryRecord[] {
    assertIsolationScope(this.projectIsolation, query.scope, "memory.search asOf");
    return queryRecordsAsOfImpl(this.store, query);
  }

  // ---- Task 4: evidence authority -------------------------------------------

  explainAuthority(recordId: string): AuthorityAssessment {
    const record = getRecordImpl(this.store, recordId);
    return authorityOf(record.provenance, record.epistemicClass);
  }

  // ---- Task 13: retention, archival, and deletion ----------------------------

  archiveRecord(recordId: string, input: { actor: ActorInput; reason: string; origin?: string }): MemoryRecord {
    return archiveRecordImpl(this.store, recordId, input);
  }

  restoreRecord(recordId: string, input: { actor: ActorInput; reason: string; origin?: string }): MemoryRecord {
    return restoreRecordImpl(this.store, recordId, input);
  }

  deleteRecord(recordId: string, input: { actor: ActorInput; reason: string; origin?: string }): MemoryRecord {
    return deleteRecordImpl(this.store, recordId, input);
  }

  purgeRecord(recordId: string, input: { actor: ActorInput; reason: string; origin?: string }): { purged: boolean } {
    return purgeRecordImpl(this.store, recordId, input);
  }

  purgeByPrivacy(input: {
    actor: ActorInput;
    reason: string;
    privacyClasses: Array<"public" | "internal" | "sensitive">;
    scope?: string;
    origin?: string;
  }): { purgedCount: number; recordIds: string[] } {
    return purgeByPrivacyImpl(this.store, input);
  }

  listEvidenceExpired(scopeOrProjectKey: string, at: string): MemoryRecord[] {
    return listEvidenceExpiredImpl(this.store, scopeOrProjectKey, at);
  }

  sweepExpiredEvidence(scopeOrProjectKey: string, at: string): { expiredCount: number; recordIds: string[] } {
    return sweepExpiredEvidenceImpl(this.store, scopeOrProjectKey, at);
  }

  deleteScope(
    scopeOrProjectKey: string,
    input: { actor: ActorInput; reason: string; mode?: "tombstone" | "purge"; origin?: string },
  ): ScopeInfo {
    return deleteScopeImpl(this.store, scopeOrProjectKey, input);
  }

  // ---- Task 7: append-oriented persistence observability/recovery -----------

  checkAppendIntegrity(): AppendIntegrityReport {
    return this.store.checkAppendIntegrity();
  }

  repairRecordProjection(recordId: string): { repaired: boolean; detail: string } {
    return this.store.repairRecordProjection(recordId);
  }
}

export type {
  ContradictionGroup,
  DoctorReport,
  EngineEvent,
  MemoryCandidate,
  MemoryRecord,
  ScopeInfo,
};
export type {
  Actor,
  ActorKind,
  AuthorityAssessment,
  AuthorityTier,
  CandidateStatus,
  EpistemicClass,
  EvidenceEngine,
  EvidenceRef,
  IntakePolicy,
  MemoryErrorCode,
  PrivacyClass,
  PromotionAssessment,
  PromotionConfig,
  PromotionPolicyName,
  Provenance,
  RecordKind,
  RecordStatus,
  RelationHint,
  RelationType,
  SourceKind,
} from "../contracts/types.ts";
export {
  ConflictError,
  ContractMismatchError,
  CorrectionForbiddenError,
  EmbeddingsNotBuiltError,
  EmbeddingsUnavailableError,
  IntakeUnauthorizedError,
  MemoryEngineError,
  MigrationError,
  MutationForbiddenError,
  NotFoundError,
  PrivacyViolationError,
  PromotionForbiddenError,
  StoreUnavailableError,
  ValidationError,
} from "../contracts/errors.ts";
export { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";

export type {
  ProvenanceRank,
  ProvenanceSignal,
  RankedSearchResult,
  RankedLexicalHit,
} from "./ranking.ts";
export type {
  DuplicateAnalysis,
  DuplicateMatch,
  DuplicateKind,
} from "./dedup.ts";
export type {
  FusedSearchResult,
  FusedHit,
  FusionOptions,
  FusionSignalName,
  SignalContribution,
} from "./fusion.ts";
export type {
  HybridSearchResult,
  HybridSearchOptions,
  HybridHit,
  HybridSignal,
  HybridSignalName,
  HybridPath,
} from "./fusion.ts";
export type {
  ProjectionIntegrityReport,
  ProjectionStatus,
  ProjectionName,
  RebuildResult,
  RepairResult,
} from "./projections.ts";
export type {
  PerformanceLesson,
  PerformanceProposalResult,
  PerformanceRejection,
} from "./performance.ts";
export type {
  StudyProposal,
  StudyProposalResult,
  StudyRejection,
  StudyProposalKind,
} from "./study.ts";
export type {
  AnalysisFinding,
  AnalysisProposalResult,
  AnalysisRejection,
} from "./analysis.ts";
export type { SearchSession, SearchSessionInput } from "./searchHistory.ts";
export type { ContextQuery, ContextQueryResult, ContextRecord, ContextTimeFilter } from "./context.ts";
export type { UserNoteInput } from "./userNotes.ts";
export type { ContextExcerpt, ContextExcerptQuery, ExcerptPack, MemoryExcerptOptions } from "./excerpts.ts";
export type { ContentPolicy, PrivacyPolicy, ProjectIsolation, PolicyStatus } from "./privacy.ts";
export type { ContentBoundaryStatus } from "./trust.ts";
export type { BackupBundle, BackupData, StoreReferenceReport } from "./backup.ts";
export type { MemoryHealthMetrics } from "./health.ts";
export type {
  CorpusBuildResult,
  CorpusOptions,
  QualificationCheck,
  QualificationReport,
} from "./corpora.ts";
export type {
  EvaluationOptions,
  RetrievalEvaluationReport,
  StrategyEvaluation,
  StrategyQueryResult,
  SemanticGate,
} from "./evaluation.ts";
export type { LineageQualificationReport } from "./qualification.ts";
export type {
  RecoveryQualificationOptions,
  RecoveryQualificationReport,
} from "./recovery.ts";
export { QUALIFICATION_CORPUS_VERSION, QUALIFICATION_CORPUS_SCOPE_KEY, CORPUS_AT } from "./corpora.ts";
export type { ExplainResult, RelationInput } from "./relations.ts";
export type {
  EntityProjection,
  EntityProjectionEntry,
  EntityProjectionRecord,
} from "./entities.ts";
export type {
  EmbeddingProjection,
  EmbeddingProjectionEntry,
  EmbeddingProjectionStatus,
  EmbeddingProvider,
  EmbeddingBuildOptions,
  SemanticHit,
  SemanticSearchResult,
} from "./embeddings.ts";
export type {
  GraphProjection,
  GraphNode,
  GraphEdge,
  GraphTraversal,
  TraversalNode,
  TraversalOptions,
} from "./graph.ts";
export type { SearchTrace, SearchMatchReason } from "./records.ts";
export type { CurrentTrace, CurrentMatchReason } from "./retrieval.ts";
export type { AsOfTrace, AsOfMatchReason } from "./temporal.ts";

// ---- implementation imports (kept at bottom for readability) ---------------
import { authorityOf } from "./authority.ts";
import {
  getRecordHistoryImpl,
  queryRecordsAsOfImpl,
  queryRecordsAsOfTracedImpl,
  type RecordHistory,
  type AsOfQuery,
  type AsOfTrace,
} from "./temporal.ts";
import {
  addCandidateImpl,
  addRecordImpl,
  expireStaleRecordsImpl,
  getCandidate,
  getRecordImpl,
  listCandidatesImpl,
  promoteCandidateImpl,
  rejectCandidateImpl,
  retractRecordImpl,
  reviseRecordImpl,
  searchRecordsImpl,
  searchRecordsTracedImpl,
  supersedeRecordImpl,
  type SearchTrace,
} from "./records.ts";
import type { RecordInput, RecordSearchFilter, ActorInput } from "./records.ts";
import {
  buildFtsQuery,
  currentRecordsImpl,
  currentRecordsTracedImpl,
  decisionTimelineImpl,
  lexicalSearchImpl,
  rebuildSearchIndexImpl,
  type CurrentQuery,
  type CurrentTrace,
  type LexicalSearchFilter,
  type LexicalSearchResult,
  type TimelineEntry,
} from "./retrieval.ts";
import { explainImpl, relatedImpl, addRelationImpl, removeRelationImpl, type ExplainResult } from "./relations.ts";
import { entityProjectionImpl, rebuildEntityProjectionImpl } from "./entities.ts";
import {
  buildEmbeddingProjectionImpl,
  embeddingProjectionStatusImpl,
  rebuildEmbeddingProjectionImpl,
  semanticSearchImpl,
} from "./embeddings.ts";
import {
  graphProjectionImpl,
  rebuildGraphProjectionImpl,
  traverseGraphImpl,
} from "./graph.ts";
import {
  fusedSearchImpl,
  hybridSearchImpl,
  type FusedSearchResult,
  type FusionOptions,
} from "./fusion.ts";
import {
  checkProjectionIntegrityImpl,
  rebuildAllProjectionsImpl,
  repairProjectionsImpl,
} from "./projections.ts";
import { proposePerformanceLessonsImpl } from "./performance.ts";
import { proposeStudyImpl } from "./study.ts";
import { proposeAnalysisImpl } from "./analysis.ts";
import {
  getSearchSessionImpl,
  listSearchSessionsImpl,
  recordSearchSessionImpl,
} from "./searchHistory.ts";
import { contextQueryImpl } from "./context.ts";
import { addUserNoteImpl } from "./userNotes.ts";
import { buildContextExcerptsImpl, memoryExcerptImpl } from "./excerpts.ts";
import {
  asUntrustedData,
  contentBoundaryStatusImpl,
  type ContentBoundaryStatus,
} from "./trust.ts";
import {
  backupImpl,
  backupToFile as backupToFileImpl,
  verifyBackup as verifyBackupImpl,
  restoreBundle as restoreBundleImpl,
  verifyStoreReferences as verifyStoreReferencesImpl,
  type BackupBundle,
  type StoreReferenceReport,
} from "./backup.ts";
import { memoryHealthImpl, type MemoryHealthMetrics } from "./health.ts";
import {
  buildQualificationCorpusImpl,
  verifyQualificationCorpusImpl,
  type CorpusBuildResult,
  type CorpusOptions,
  type QualificationCheck,
  type QualificationReport,
} from "./corpora.ts";
import {
  evaluateRetrievalImpl,
  type EvaluationOptions,
  type RetrievalEvaluationReport,
} from "./evaluation.ts";
import {
  qualifyContradictionSupersessionImpl,
  type LineageQualificationReport,
} from "./qualification.ts";
import {
  qualifyRecoveryImpl,
  type RecoveryQualificationOptions,
  type RecoveryQualificationReport,
} from "./recovery.ts";
import { evaluatePromotionImpl } from "./policies.ts";
import {
  archiveRecordImpl,
  deleteRecordImpl,
  listEvidenceExpiredImpl,
  purgeByPrivacyImpl,
  purgeRecordImpl,
  restoreRecordImpl,
  sweepExpiredEvidenceImpl,
} from "./retention.ts";
import {
  findContradictionPairsImpl,
  listOpenContradictionsImpl,
  registerContradictionImpl,
  resolveContradictionImpl,
} from "./contradictions.ts";
import {
  createScopeImpl,
  deleteScopeImpl,
  getScopeImpl,
  setScopeIntakePolicyImpl,
  setScopeMutationPolicyImpl,
} from "./scopes.ts";
import {
  rankedSearchImpl,
  type RankedSearchResult,
} from "./ranking.ts";
import {
  analyzeProposalImpl,
  findCandidateDuplicatesImpl,
  type DuplicateAnalysis,
} from "./dedup.ts";

/** Task 7: append-integrity report shape (projection vs revision log). */
export interface AppendIntegrityReport {
  consistent: boolean;
  recordCount: number;
  broken: Array<{ recordId: string; problem: string }>;
}
