/**
 * Public module surface of the Library Memory Engine.
 *
 * This is the ONLY supported import path for other packages/engines.
 * MemoryStore is deliberately NOT exported: the canonical store is private
 * to this engine, and no caller may read it directly (Task 6). External
 * callers use the MemoryEngine API or the versioned contract dispatcher.
 */
export { MemoryEngine, defaultStorePath } from "./engine/memoryEngine.ts";
export {
  QUALIFICATION_CORPUS_VERSION,
  QUALIFICATION_CORPUS_SCOPE_KEY,
  CORPUS_AT,
} from "./engine/corpora.ts";
export type {
  CorpusBuildResult,
  CorpusOptions,
  QualificationCheck,
  QualificationReport,
} from "./engine/corpora.ts";
export type {
  EvaluationOptions,
  RetrievalEvaluationReport,
  StrategyEvaluation,
  StrategyQueryResult,
  SemanticGate,
} from "./engine/evaluation.ts";
export type { LineageQualificationReport } from "./engine/qualification.ts";
export type {
  RecoveryQualificationOptions,
  RecoveryQualificationReport,
} from "./engine/recovery.ts";
export {
  dispatch,
} from "./engine/dispatcher.ts";
export {
  MEMORY_OPERATIONS,
  isMemoryOperation,
  type MemoryOperation,
  type MemoryRequestEnvelope,
  type MemoryResponseEnvelope,
} from "./contracts/operations.ts";
export { MEMORY_ENGINE_CONTRACT_VERSION, MEMORY_ENGINE_ID } from "./contracts/version.ts";
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
} from "./contracts/errors.ts";
export type {
  Actor,
  ActorKind,
  AuthorityAssessment,
  AuthorityTier,
  ContradictionGroup,
  ContradictionPair,
  ContradictionResolution,
  ContradictionStatus,
  DoctorReport,
  EngineEvent,
  EpistemicClass,
  EvidenceEngine,
  EvidenceRef,
  MemoryCandidate,
  MemoryRecord,
  Provenance,
  RecordKind,
  RecordStatus,
  RelationHint,
  RelationProvenance,
  RelationType,
  EntityKind,
  ScopeInfo,
  SourceKind,
} from "./contracts/types.ts";
export type { ContradictionResolutionInput } from "./engine/contradictions.ts";
export type {
  RecordHistory,
  AsOfQuery,
  AsOfTrace,
  AsOfMatchReason,
} from "./engine/temporal.ts";
export type {
  RecordInput,
  RecordSearchFilter,
  SearchTrace,
  SearchMatchReason,
} from "./engine/records.ts";
export type {
  RelatedResult,
  ExplainResult,
  RelationInput,
} from "./engine/relations.ts";
export type {
  EntityProjection,
  EntityProjectionEntry,
  EntityProjectionRecord,
} from "./engine/entities.ts";
export { localHashProvider } from "./engine/embeddings.ts";
export type {
  EmbeddingProjection,
  EmbeddingProjectionEntry,
  EmbeddingProjectionStatus,
  EmbeddingProvider,
  EmbeddingBuildOptions,
  SemanticHit,
  SemanticSearchResult,
} from "./engine/embeddings.ts";
export type {
  GraphProjection,
  GraphNode,
  GraphEdge,
  GraphTraversal,
  TraversalNode,
  TraversalOptions,
} from "./engine/graph.ts";
export type {
  CurrentQuery,
  CurrentTrace,
  CurrentMatchReason,
  LexicalSearchFilter,
  LexicalSearchResult,
  LexicalHit,
  TimelineEntry,
} from "./engine/retrieval.ts";
export type {
  ProvenanceRank,
  ProvenanceSignal,
  RankedSearchResult,
  RankedLexicalHit,
} from "./engine/ranking.ts";
export type {
  DuplicateAnalysis,
  DuplicateMatch,
  DuplicateKind,
} from "./engine/dedup.ts";
export type {
  FusedSearchResult,
  FusedHit,
  FusionOptions,
  FusionSignalName,
  SignalContribution,
} from "./engine/fusion.ts";
export type {
  HybridSearchResult,
  HybridSearchOptions,
  HybridHit,
  HybridSignal,
  HybridSignalName,
  HybridPath,
} from "./engine/fusion.ts";
export type {
  ProjectionIntegrityReport,
  ProjectionStatus,
  ProjectionName,
  RebuildResult,
  RepairResult,
} from "./engine/projections.ts";
export type {
  PerformanceLesson,
  PerformanceProposalResult,
  PerformanceRejection,
} from "./engine/performance.ts";
export type {
  StudyProposal,
  StudyProposalResult,
  StudyRejection,
  StudyProposalKind,
} from "./engine/study.ts";
export type {
  AnalysisFinding,
  AnalysisProposalResult,
  AnalysisRejection,
} from "./engine/analysis.ts";
export type { SearchSession, SearchSessionInput } from "./engine/searchHistory.ts";
export type { ContextQuery, ContextQueryResult, ContextRecord, ContextTimeFilter } from "./engine/context.ts";
export type { UserNoteInput } from "./engine/userNotes.ts";
export type { ContextExcerpt, ContextExcerptQuery, ExcerptPack, MemoryExcerptOptions } from "./engine/excerpts.ts";
export type { ContentPolicy, PrivacyPolicy, ProjectIsolation, PolicyStatus } from "./engine/privacy.ts";
export type { ContentBoundaryStatus } from "./engine/trust.ts";
export type { BackupBundle, BackupData, StoreReferenceReport } from "./engine/backup.ts";
export type { MemoryHealthMetrics } from "./engine/health.ts";
export { MEMORY_TOOLS, readTools, findTool } from "./tools/memoryTools.ts";
export type { MemoryTool, ToolCategory } from "./tools/memoryTools.ts";
export { runMcpServer } from "./tools/mcpServer.ts";
export type { McpServerOptions } from "./tools/mcpServer.ts";
