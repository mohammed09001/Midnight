/**
 * Explainable multi-signal fusion (Task 19).
 *
 * Combine lexical, structured, temporal, provenance and relation signals
 * with VISIBLE per-signal contributions. The engine never collapses the
 * result into an opaque score: every hit reports each signal's normalized
 * value, weight, and its contribution to the total, plus a deterministic
 * explanation of why it ranks where it does.
 *
 * Signals (each normalized to [0,1]):
 *  - lexical     : BM25 keyword relevance (docs/RETRIEVAL.md)
 *  - structured  : structured-filter match strength (subject/tag/kind)
 *  - temporal    : currency — is the record currently meaningful (docs/TEMPORAL.md)
 *  - provenance  : authority + directness + confidence (docs/AUTHORITY.md, Task 17)
 *  - relation    : corroboration through relation hints / contradiction exposure
 *
 * Provider-free and deterministic. Pattern ADAPTED from mem0's hybrid
 * multi-signal retrieval (semantic + BM25 + entities) in intent (main @
 * 2026-08-30); the embedding/LLM-dependent semantic signal is REJECTED here
 * — Memory fuses only self-hosted, deterministic signals and exposes each.
 */
import type { MemoryRecord, RelationHint } from "../contracts/types.ts";
import { buildFtsQuery, lexicalSearchImpl } from "./retrieval.ts";
import { provenanceRank } from "./ranking.ts";
import { getScopeImpl } from "./scopes.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import {
  cosineSimilarity,
  embedWithProvider,
  parseStoredVector,
  type EmbeddingProvider,
} from "./embeddings.ts";
import type { MemoryStore } from "./store.ts";

export type FusionSignalName = "lexical" | "structured" | "temporal" | "provenance" | "relation";

export interface SignalContribution {
  /** Normalized signal value in [0,1]. */
  value: number;
  /** Weight of this signal in the fusion. */
  weight: number;
  /** value * weight — this signal's contribution to the total. */
  contribution: number;
}

export interface FusedHit {
  record: MemoryRecord;
  /** Per-signal visible breakdown (never an opaque score). */
  signals: Record<FusionSignalName, SignalContribution>;
  /** Sum of contributions; the final rank in [0,1]. */
  total: number;
  /** Deterministic human-readable explanation. */
  explanation: string[];
}

export interface FusedSearchResult {
  query: string;
  terms: string[];
  /** Global per-signal weights so callers can inspect the fusion. */
  weights: Record<FusionSignalName, number>;
  hits: FusedHit[];
  diagnostics: {
    totalMatches: number;
    truncated: boolean;
  };
}

/** Default per-signal weights (deterministic; overridable per call). */
export const DEFAULT_FUSION_WEIGHTS: Record<FusionSignalName, number> = {
  lexical: 0.3,
  structured: 0.15,
  temporal: 0.2,
  provenance: 0.25,
  relation: 0.1,
};

export interface FusionOptions {
  scope?: string;
  /** Restrict structured signal to exact subject matches. */
  exactSubject?: string;
  tag?: string;
  kind?: MemoryRecord["kind"];
  limit?: number;
  at?: string;
  weights?: Partial<Record<FusionSignalName, number>>;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function lexicalNormalize(score: number): number {
  return clamp01(score / (1 + score));
}

/** Structured signal: how well the record matches explicit structured filters. */
function structuredSignal(
  record: MemoryRecord,
  q: { exactSubject?: string; tag?: string; kind?: MemoryRecord["kind"] },
): number {
  let score = 0;
  const matched: string[] = [];
  if (q.exactSubject !== undefined) {
    if (record.subject === q.exactSubject) {
      score += 0.6;
      matched.push("exactSubject");
    }
  } else {
    // Without an explicit exact subject, a query-token overlap in the subject helps.
    score += 0.2;
    matched.push("subject-present");
  }
  if (q.tag !== undefined && record.tags.includes(q.tag)) {
    score += 0.25;
    matched.push("tag");
  }
  if (q.kind !== undefined && record.kind === q.kind) {
    score += 0.15;
    matched.push("kind");
  }
  return clamp01(score);
}

/** Temporal signal: currency at instant `at` (current is preferred). */
function temporalSignal(record: MemoryRecord, at: string): number {
  if (record.status !== "active") return 0.2;
  if (record.validFrom !== null && record.validFrom > at) return 0.2;
  if (record.validUntil !== null && record.validUntil <= at) return 0.2;
  return 1.0;
}

/**
 * Relation/corroboration signal: how connected the record is via relation
 * hints (outgoing + incoming) and contradiction exposure. Well-connected
 * records corroborate more; a member of an open contradiction group is
 * exposed but slightly down-weighted.
 */
function relationSignal(record: MemoryRecord, incoming: RelationHint[]): number {
  let score = 0;
  const degree = record.relationHints.length + incoming.length;
  // Saturation curve so a few links matter but the signal never dominates.
  score += clamp01(degree / 4) * 0.7;
  if (record.contradictionGroupId !== null) {
    score += 0.1; // exposed, low weight
  }
  return clamp01(score);
}

/**
 * Compute incoming relation hints (records whose hints target this record).
 * Bounded scan of the scope; relations are stored as JSON on each record.
 */
function incomingHints(db: { prepare(sql: string): { all(...p: unknown[]): Array<Record<string, unknown>> } }, scopeId: string, recordId: string): RelationHint[] {
  const rows = db
    .prepare("SELECT relation_hints_json FROM memory_records WHERE scope_id = ? AND record_id != ?")
    .all(scopeId, recordId) as Array<Record<string, unknown>>;
  const incoming: RelationHint[] = [];
  for (const row of rows) {
    const hints = JSON.parse(String(row["relation_hints_json"])) as RelationHint[];
    for (const hint of hints) {
      if (hint.target === recordId) incoming.push(hint);
    }
  }
  return incoming;
}

/**
 * Explainable multi-signal fused search. Runs lexical search over the full
 * (non-tombstoned) corpus, then for every hit computes the five signals and
 * reports their contributions explicitly.
 */
export function fusedSearchImpl(
  store: MemoryStore,
  query: string,
  options: FusionOptions = {},
): FusedSearchResult {
  const terms = buildFtsQuery(query);
  const at = options.at ?? new Date().toISOString();
  assertIsoTimestamp(at, "at");
  const weights: Record<FusionSignalName, number> = { ...DEFAULT_FUSION_WEIGHTS, ...options.weights };
  const scopeId = options.scope !== undefined ? getScopeImpl(store, options.scope).scopeId : undefined;
  const db = store.ensureOpen();

  const lexical = lexicalSearchImpl(store, query, {
    scope: options.scope,
    status: "all",
    limit: Math.min(Math.max(options.limit ?? 20, 1), 100),
  });

  const hits: FusedHit[] = lexical.hits.map((hit) => {
    const record = hit.record;
    const incoming = scopeId !== undefined ? incomingHints(db, scopeId, record.recordId) : [];
    const prov = provenanceRank(record, at);

    const raw: Record<FusionSignalName, number> = {
      lexical: lexicalNormalize(hit.score),
      structured: structuredSignal(record, {
        exactSubject: options.exactSubject,
        tag: options.tag,
        kind: options.kind,
      }),
      temporal: temporalSignal(record, at),
      provenance: prov.score,
      relation: relationSignal(record, incoming),
    };

    const signals = {} as Record<FusionSignalName, SignalContribution>;
    let total = 0;
    for (const name of Object.keys(weights) as FusionSignalName[]) {
      const weight = weights[name]!;
      const contribution = weight * raw[name]!;
      signals[name] = { value: raw[name]!, weight, contribution };
      total += contribution;
    }

    const explanation = [
      `lexical ${raw.lexical!.toFixed(2)} (BM25 ${hit.score.toFixed(2)})`,
      `temporal ${raw.temporal!.toFixed(2)} (${record.status})`,
      `provenance ${raw.provenance!.toFixed(2)} (${prov.authority.tier})`,
      `structured ${raw.structured!.toFixed(2)}`,
      `relation ${raw.relation!.toFixed(2)} (${record.relationHints.length + incoming.length} links)`,
    ];
    if (prov.historical) explanation.push("historical: not currently meaningful but exposed");
    if (prov.contradicted) explanation.push("member of an open contradiction group (exposed)");

    return { record, signals, total, explanation };
  });

  hits.sort((a, b) => b.total - a.total);

  return {
    query,
    terms,
    weights,
    hits,
    diagnostics: {
      totalMatches: lexical.diagnostics.totalMatches,
      truncated: lexical.diagnostics.truncated,
    },
  };
}

// ---- Task 25: hybrid lexical + semantic + relation retrieval ---------------

/**
 * Hybrid retrieval signal name: the deterministic Task-19 set PLUS the
 * OPTIONAL semantic signal (Task 23), fused only when an embedding provider
 * is configured and the scope's projection is built ("only after baseline
 * evaluation"). The retrieval PATH is always explained.
 */
export type HybridSignalName =
  | "lexical"
  | "structured"
  | "temporal"
  | "provenance"
  | "relation"
  | "semantic";

export interface HybridSignal {
  /** True when the signal actually participated in the fusion. */
  available: boolean;
  /** Normalized [0,1]; 0 when unavailable. */
  value: number;
  weight: number;
  contribution: number;
  provider?: string;
  model?: string;
  /** Why the signal was unavailable (e.g. semantic without a provider/built projection). */
  reason?: string;
}

export interface HybridHit {
  record: MemoryRecord;
  signals: Record<HybridSignalName, HybridSignal>;
  /** Sum of available contributions; the final rank in [0,1]. */
  total: number;
  explanation: string[];
}

export interface HybridPath {
  /** Signal names that actually participated. */
  signals: HybridSignalName[];
  /** Retrieval-path explanation for the optional semantic signal. */
  semantic: { available: boolean; provider?: string; model?: string; reason?: string };
  /** Relation signal is always available from canonical relation hints. */
  relation: { available: true; source: "relation_hints" };
}

export interface HybridSearchResult {
  query: string;
  terms: string[];
  weights: Record<HybridSignalName, number>;
  /** Retrieval-path explanation (which signals fused, and why). */
  path: HybridPath;
  hits: HybridHit[];
  diagnostics: { totalMatches: number; truncated: boolean };
}

export const DEFAULT_HYBRID_WEIGHTS: Record<HybridSignalName, number> = {
  lexical: 0.25,
  structured: 0.1,
  temporal: 0.15,
  provenance: 0.2,
  relation: 0.1,
  semantic: 0.2,
};

export interface HybridSearchOptions {
  scope?: string;
  exactSubject?: string;
  tag?: string;
  kind?: MemoryRecord["kind"];
  limit?: number;
  at?: string;
  weights?: Partial<Record<HybridSignalName, number>>;
}

interface SemanticRecordSignal {
  value: number;
  available: boolean;
  reason?: string;
}

interface SemanticContext {
  available: boolean;
  provider?: string;
  model?: string;
  reason?: string;
  forRecord(recordId: string): SemanticRecordSignal;
}

function buildSemanticContext(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  scopeId: string | undefined,
  candidateRecordIds: string[],
  queryText: string,
): SemanticContext {
  if (provider === null) {
    return {
      available: false,
      reason: "no embedding provider configured (semantic signal unavailable; deterministic baseline used)",
      forRecord: () => ({ value: 0, available: false, reason: "semantic unavailable (no provider)" }),
    };
  }
  // Task 41: a provider that fails at runtime (network/model error, contract
  // violation) DEGRADES the semantic signal — the deterministic lexical
  // baseline is never lost to an optional signal.
  let queryVector: Float32Array;
  try {
    queryVector = embedWithProvider(provider, [queryText])[0]!;
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return {
      available: false,
      reason: `embedding provider failed (semantic signal unavailable; deterministic baseline used): ${detail}`,
      forRecord: () => ({ value: 0, available: false, reason: "semantic unavailable (provider failed)" }),
    };
  }
  const db = store.ensureOpen();
  const meta = scopeId !== undefined
    ? db.prepare("SELECT 1 FROM memory_embedding_projections WHERE scope_id = ?").get(scopeId)
    : db.prepare("SELECT 1 FROM memory_embedding_projections LIMIT 1").get();
  if (meta === undefined) {
    return {
      available: false,
      reason: "embedding projection not built for this scope (semantic signal unavailable; deterministic baseline used)",
      forRecord: () => ({ value: 0, available: false, reason: "semantic unavailable (projection not built)" }),
    };
  }
  const vectors = new Map<string, Float32Array>();
  for (const recordId of candidateRecordIds) {
    const row = db.prepare("SELECT vector_json FROM memory_embeddings WHERE record_id = ?").get(recordId) as Record<string, unknown> | undefined;
    if (row !== undefined) {
      // Task 41: a corrupt derived vector row degrades that record's semantic
      // signal — it never breaks hybrid retrieval (repair via repairProjections).
      const vector = parseStoredVector(row);
      if (vector !== null) vectors.set(recordId, vector);
    }
  }
  return {
    available: true,
    provider: provider.name,
    model: provider.model,
    forRecord: (recordId) => {
      const vector = vectors.get(recordId);
      if (vector === undefined) {
        return { value: 0, available: false, reason: "record not embedded (privacy gate, absent or corrupt in projection)" };
      }
      const cos = cosineSimilarity(queryVector, vector);
      return { value: (cos + 1) / 2, available: true };
    },
  };
}

/**
 * Hybrid lexical + semantic + relation retrieval (Task 25).
 *
 * The deterministic baseline (lexical BM25 + structured/temporal/provenance/
 * relation) ALWAYS runs and explains itself. The optional SEMANTIC signal
 * (cosine distance over the Task-23 embedding projection) is fused ONLY when
 * an embedding provider is configured AND the scope's projection is built —
 * never required, never silently assumed. Every hit reports each signal's
 * availability, value, weight and contribution, and `path` explains the
 * retrieval path (which signals participated and why).
 */
export function hybridSearchImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  query: string,
  options: HybridSearchOptions = {},
): HybridSearchResult {
  const terms = buildFtsQuery(query);
  const at = options.at ?? new Date().toISOString();
  assertIsoTimestamp(at, "at");
  const weights: Record<HybridSignalName, number> = { ...DEFAULT_HYBRID_WEIGHTS, ...options.weights };
  const scopeId = options.scope !== undefined ? getScopeImpl(store, options.scope).scopeId : undefined;
  const db = store.ensureOpen();

  const lexical = lexicalSearchImpl(store, query, {
    scope: options.scope,
    status: "all",
    limit: Math.min(Math.max(options.limit ?? 20, 1), 100),
  });

  const semantic = buildSemanticContext(store, provider, scopeId, lexical.hits.map((h) => h.record.recordId), query);

  const hits: HybridHit[] = lexical.hits.map((hit) => {
    const record = hit.record;
    const incoming = scopeId !== undefined ? incomingHints(db, scopeId, record.recordId) : [];
    const prov = provenanceRank(record, at);
    const sem = semantic.forRecord(record.recordId);

    const signals = {} as Record<HybridSignalName, HybridSignal>;
    let total = 0;
    const active: HybridSignalName[] = [];
    const setSignal = (
      name: HybridSignalName,
      value: number,
      available: boolean,
      extra: Partial<HybridSignal> = {},
    ): void => {
      const weight = weights[name]!;
      const contribution = available ? weight * value : 0;
      signals[name] = {
        available,
        value: available ? value : 0,
        weight,
        contribution,
        ...extra,
      };
      total += contribution;
      if (available) active.push(name);
    };

    setSignal("lexical", lexicalNormalize(hit.score), true);
    setSignal("structured", structuredSignal(record, { exactSubject: options.exactSubject, tag: options.tag, kind: options.kind }), true);
    setSignal("temporal", temporalSignal(record, at), true);
    setSignal("provenance", prov.score, true);
    setSignal("relation", relationSignal(record, incoming), true);
    setSignal("semantic", sem.value, sem.available, sem.available
      ? { provider: semantic.provider, model: semantic.model }
      : { reason: sem.reason });

    const explanation = [
      `lexical ${signals.lexical.value.toFixed(2)} (BM25 ${hit.score.toFixed(2)})`,
      `temporal ${signals.temporal.value.toFixed(2)} (${record.status})`,
      `provenance ${signals.provenance.value.toFixed(2)} (${prov.authority.tier})`,
      `structured ${signals.structured.value.toFixed(2)}`,
      `relation ${signals.relation.value.toFixed(2)} (${record.relationHints.length + incoming.length} links)`,
      sem.available
        ? `semantic ${sem.value.toFixed(2)} (${semantic.provider}/${semantic.model})`
        : `semantic unavailable: ${sem.reason ?? ""}`,
    ];
    if (prov.historical) explanation.push("historical: not currently meaningful but exposed");
    if (prov.contradicted) explanation.push("member of an open contradiction group (exposed)");

    return { record, signals, total, explanation };
  });

  hits.sort((a, b) => b.total - a.total);

  const activeSignals = [...new Set(hits.flatMap((h) => Object.keys(h.signals).filter((n) => h.signals[n as HybridSignalName].available)))];
  return {
    query,
    terms,
    weights,
    path: {
      signals: activeSignals as HybridSignalName[],
      semantic: semantic.available
        ? { available: true, provider: semantic.provider, model: semantic.model }
        : { available: false, reason: semantic.reason },
      relation: { available: true, source: "relation_hints" },
    },
    hits,
    diagnostics: {
      totalMatches: lexical.diagnostics.totalMatches,
      truncated: lexical.diagnostics.truncated,
    },
  };
}
