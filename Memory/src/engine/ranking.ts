/**
 * Provenance-aware ranking (Task 17).
 *
 * Prefer high-authority, direct, current evidence while STILL exposing
 * lower-confidence or contradicted records instead of silently hiding them.
 *
 * Ranking is a pure, deterministic function of each record's provenance
 * (authority tier, directness, currency, confidence, contradiction
 * membership). It never depends on text fluency. Every material signal is
 * surfaced as an explicit sub-score with a human-readable note so a
 * terminal/tool caller can see WHY one record outranks another and can
 * always see the low-confidence / superseded / contradicted records that
 * were ranked down but not removed.
 *
 * Provider/LLM-free: authority is structural (docs/AUTHORITY.md), not
 * content-based. Pattern ADAPTED from mem0's "importance/relevance"
 * multi-signal retrieval (main @ 2026-08-30) WITHOUT its LLM/embedding
 * scoring dependency (REJECTED here — Memory ranking must be deterministic
 * and self-hosted).
 */
import type { AuthorityAssessment, AuthorityTier, MemoryRecord } from "../contracts/types.ts";
import { authorityOf } from "./authority.ts";
import { buildFtsQuery, lexicalSearchImpl } from "./retrieval.ts";
import { assertIsoTimestamp } from "./temporal.ts";
import type { MemoryStore } from "./store.ts";

/** Numeric base for each authority tier (structural, never content-based). */
export const AUTHORITY_TIER_VALUE: Record<AuthorityTier, number> = {
  verified_source: 1.0,
  user_decision: 0.9,
  user_reported: 0.85,
  analysis: 0.7,
  agent_derived: 0.5,
  unattributed: 0.3,
};

export interface ProvenanceSignal {
  /** Authority tier value in [0,1] (structural, from source kind). */
  authority: number;
  /**
   * Directness in [0,1]: how directly the claim is grounded. Agent-derived
   * provenance, inference/recommendation epistemic classes, and missing
   * evidence references all reduce directness.
   */
  directness: number;
  /**
   * Currency in [0,1]: whether the record is currently meaningful
   * (active + within validity window + not superseded/retracted/expired/
   * archived). Past versions are exposed but ranked down.
   */
  currency: number;
  /** Record confidence in [0,1]. */
  confidence: number;
  /** Contradiction penalty in [0,1]: records in an open contradiction group are exposed but down-weighted. */
  contradiction: number;
}

export interface ProvenanceRank {
  recordId: string;
  /** Overall provenance score in [0,1] (weighted blend of signals). */
  score: number;
  signals: ProvenanceSignal;
  /** Human-readable, deterministic notes explaining each signal. */
  notes: string[];
  /** True when the record is retained but ranked down for low confidence. */
  lowConfidence: boolean;
  /** True when the record is superseded/retracted/expired/archived (exposed, not current). */
  historical: boolean;
  /** True when the record belongs to an open contradiction group. */
  contradicted: boolean;
  authority: AuthorityAssessment;
}

const CURRENCY_WEIGHT = 0.35;
const AUTHORITY_WEIGHT = 0.25;
const DIRECTNESS_WEIGHT = 0.2;
const CONFIDENCE_WEIGHT = 0.12;
const CONTRADICTION_WEIGHT = 0.08;

function currencyOf(record: MemoryRecord, at: string): { value: number; historical: boolean; notes: string[] } {
  const notes: string[] = [];
  let historical = false;
  if (record.status !== "active") {
    historical = true;
    notes.push(`status '${record.status}' is not current (exposed but ranked down)`);
  }
  if (record.supersededAt !== null) {
    historical = true;
    notes.push(`superseded at ${record.supersededAt}${record.supersededReason ? ` — ${record.supersededReason}` : ""}`);
  }
  if (record.validFrom !== null && record.validFrom > at) {
    historical = true;
    notes.push(`not yet valid (valid_from ${record.validFrom})`);
  }
  if (record.validUntil !== null && record.validUntil <= at) {
    historical = true;
    notes.push(`validity expired at ${record.validUntil}`);
  }
  const value = historical ? 0.25 : 1.0;
  return { value, historical, notes };
}

function directnessOf(record: MemoryRecord): { value: number; notes: string[] } {
  const notes: string[] = [];
  let score = 1.0;
  if (record.epistemicClass === "inferred" || record.epistemicClass === "recommendation") {
    score -= 0.35;
    notes.push(`epistemicClass '${record.epistemicClass}' is inference/recommendation, not direct evidence`);
  }
  if (record.provenance.sourceKind === "agent_summary" || record.provenance.sourceKind === "agent_inference") {
    score -= 0.3;
    notes.push(`sourceKind '${record.provenance.sourceKind}' is agent-derived (indirect)`);
  }
  if (record.provenance.derivedFrom !== undefined) {
    score -= 0.15;
    notes.push("claim is derived from another reference (indirect)");
  }
  if (record.evidenceRefs.length === 0) {
    score -= 0.2;
    notes.push("no evidence references (directness reduced)");
  }
  const value = Math.max(0, score);
  return { value, notes };
}

/**
 * Deterministic provenance rank for a single record. Exposes lower-confidence
 * and contradicted records rather than hiding them: they receive a lower
 * score and an explicit flag, but are never dropped by this function.
 */
export function provenanceRank(record: MemoryRecord, at: string = new Date().toISOString()): ProvenanceRank {
  const authority = authorityOf(record.provenance, record.epistemicClass);
  const authorityValue = AUTHORITY_TIER_VALUE[authority.tier] ?? 0.3;
  const currency = currencyOf(record, at);
  const directness = directnessOf(record);
  const contradicted = record.contradictionGroupId !== null;
  const contradictionValue = contradicted ? 0.5 : 1.0;

  const notes: string[] = [
    `authority tier '${authority.tier}' (${authorityValue.toFixed(2)}${authority.capped ? ", capped" : ""})`,
    ...currency.notes,
    ...directness.notes,
  ];
  if (contradicted) {
    notes.push("member of an open contradiction group (exposed, ranked down)");
  }

  const signals: ProvenanceSignal = {
    authority: authorityValue,
    directness: directness.value,
    currency: currency.value,
    confidence: record.confidence,
    contradiction: contradictionValue,
  };

  const score =
    CURRENCY_WEIGHT * currency.value +
    AUTHORITY_WEIGHT * authorityValue +
    DIRECTNESS_WEIGHT * directness.value +
    CONFIDENCE_WEIGHT * record.confidence +
    CONTRADICTION_WEIGHT * contradictionValue;

  return {
    recordId: record.recordId,
    score: clamp01(score),
    signals,
    notes,
    lowConfidence: record.confidence < 0.5,
    historical: currency.historical,
    contradicted,
    authority,
  };
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export interface RankedLexicalHit {
  record: MemoryRecord;
  /** Lexical (BM25) relevance, positive-better. */
  lexicalScore: number;
  /** Provenance score in [0,1] with explicit per-signal breakdown. */
  provenance: ProvenanceRank;
  /**
   * Final blended rank in [0,1]: deterministic weighted combination of the
   * normalized lexical score and the provenance score.
   */
  rank: number;
}

export interface RankedSearchResult {
  query: string;
  terms: string[];
  /** All lexical hits, re-ranked by combined relevance + provenance. */
  hits: RankedLexicalHit[];
  /** Weighting used so callers can see the fusion, not an opaque score. */
  weights: { lexical: number; provenance: number };
  diagnostics: {
    totalMatches: number;
    truncated: boolean;
  };
}

const LEXICAL_WEIGHT = 0.6;
const PROVENANCE_WEIGHT = 0.4;

/**
 * Provenance-aware ranked search: run BM25 lexical search, then re-rank the
 * full result set by a visible blend of lexical relevance and provenance
 * quality. No hit is hidden — low-confidence and contradicted records stay
 * in the result list, ranked below their higher-authority, current peers.
 */
export function rankedSearchImpl(
  store: MemoryStore,
  query: string,
  options: { scope?: string; limit?: number; at?: string } = {},
): RankedSearchResult {
  const terms = buildFtsQuery(query);
  const at = options.at ?? new Date().toISOString();
  assertIsoTimestamp(at, "at");
  const lexical = lexicalSearchImpl(store, query, {
    scope: options.scope,
    status: "all",
    limit: Math.min(Math.max(options.limit ?? 20, 1), 100),
  });

  const hits: RankedLexicalHit[] = lexical.hits.map((hit) => {
    const provenance = provenanceRank(hit.record, at);
    const normLex = lexicalNormalize(hit.score);
    const rank = clamp01(LEXICAL_WEIGHT * normLex + PROVENANCE_WEIGHT * provenance.score);
    return {
      record: hit.record,
      lexicalScore: hit.score,
      provenance,
      rank,
    };
  });

  hits.sort((a, b) => b.rank - a.rank || b.lexicalScore - a.lexicalScore);

  return {
    query,
    terms,
    hits,
    weights: { lexical: LEXICAL_WEIGHT, provenance: PROVENANCE_WEIGHT },
    diagnostics: {
      totalMatches: lexical.diagnostics.totalMatches,
      truncated: lexical.diagnostics.truncated,
    },
  };
}

/** Normalize a positive-better BM25 score into [0,1] for blending. */
function lexicalNormalize(score: number): number {
  return clamp01(score / (1 + score));
}
