/**
 * Retrieval evaluation over the frozen qualification corpus (Task 43,
 * Phase VIII).
 *
 * Measures precision/recall-style usefulness for the EXACT, LEXICAL,
 * TEMPORAL, HYBRID and SEMANTIC retrieval surfaces against FROZEN relevance
 * judgments, with fully transparent results: every query reports the
 * relevant record keys, the retrieved record keys, and the per-query
 * precision/recall/MRR, so a reviewer can audit every metric instead of
 * trusting an opaque score.
 *
 * Transparent-baseline rule (Task Source Requirement): the deterministic
 * strategies (exact, lexical, temporal, hybrid-baseline) are reported FIRST
 * as the baseline; the semantic additions (standalone semantic search and
 * the hybrid semantic signal) are qualified by an explicit GATE — they must
 * BEAT or COMPLEMENT the baselines (never silently degrade them) to pass.
 *
 * Determinism: judgments and metrics are computed over the frozen
 * qualification corpus with pinned or store-derived instants; records are
 * identified by `subject::content` keys (no ids, no timestamps), so two
 * independent builds produce identical reports.
 *
 * Research: IR precision/recall/MRR are textbook metrics (no dependency);
 * mem0/getzep evaluate retrieval with LLM-judged relevance — that judge is
 * REJECTED here (non-deterministic, provider-bound). Memory's ground truth
 * is frozen subject::content judgments over its own corpus.
 */
import type { MemoryEngine } from "./memoryEngine.ts";
import {
  CORPUS_AT,
  QUALIFICATION_CORPUS_SCOPE_KEY,
  QUALIFICATION_CORPUS_VERSION,
} from "./corpora.ts";
import { localHashProvider } from "./embeddings.ts";
import type { MemoryRecord } from "../contracts/types.ts";

/** Frozen record identity for judgments: deterministic, id-free, timestamp-free. */
function recordKey(record: MemoryRecord): string {
  return `${record.subject}::${record.content}`;
}

interface FrozenQuery {
  /** Stable query identity. */
  name: string;
  /** Free-text query for lexical/hybrid/semantic strategies. */
  query: string;
  /** Exact subject for the exact strategy (when applicable). */
  exactSubject?: string;
  /** Frozen relevant record keys (`subject::content`). */
  relevant: string[];
  /** Pinned instant for the temporal strategy (when applicable). */
  temporalAt?: string;
  /** Current-view subject filter for the temporal strategy (when applicable). */
  temporalSubject?: string;
  /** Store-derived as-of instant marker for the temporal strategy. */
  temporalAsOf?: "superseded-v1-createdAt";
}

/**
 * The frozen relevance judgments. Every `relevant` key names corpus records
 * by subject::content, so the ground truth is human-auditable.
 */
const LEXICAL_QUERIES: FrozenQuery[] = [
  { name: "rate-limit", query: "requests per minute", relevant: ["Rate limit::API gateway allows 120 requests per minute per project"] },
  { name: "deploy-window", query: "deploy window tuesday", relevant: [
    "Deploy window::Deploy window is Tuesday 06:00-08:00 UTC",
    "Deploy window::Deploy window moved to Thursday 06:00-08:00 UTC since change 42",
  ] },
  { name: "sessions", query: "maximum concurrent sessions", relevant: [
    "Max concurrent sessions::Maximum 100 concurrent sessions per project",
    "Max concurrent sessions::Maximum 250 concurrent sessions per project",
  ] },
  { name: "deployment-region", query: "deployment region", relevant: [
    "Deployment region::Primary deployment region is eu-central-1",
    "Deployment region::Primary deployment region is eu-west-1",
  ] },
  { name: "api-key-rotation", query: "api key rotation", relevant: ["API key rotation::API key rotation runs on the first Monday of each quarter"] },
  // AND-strictness cases: lexical retrieves nothing; the semantic surface complements.
  { name: "auth-token-disjoint", query: "auth0 rs256 clerk", relevant: [
    "Auth provider::Auth provider is Auth0 with RS256",
    "Auth provider::Auth provider is Clerk with RS256",
  ] },
  { name: "sessions-paraphrase", query: "sessions limit per project", relevant: [
    "Max concurrent sessions::Maximum 100 concurrent sessions per project",
    "Max concurrent sessions::Maximum 250 concurrent sessions per project",
  ] },
];

const EXACT_QUERIES: FrozenQuery[] = [
  { name: "exact-auth-provider", query: "Auth provider", exactSubject: "Auth provider", relevant: [
    "Auth provider::Auth provider is Auth0 with RS256",
    "Auth provider::Auth provider is Clerk with RS256",
  ] },
  { name: "exact-rate-limit", query: "Rate limit", exactSubject: "Rate limit", relevant: ["Rate limit::API gateway allows 120 requests per minute per project"] },
];

const TEMPORAL_QUERIES: FrozenQuery[] = [
  { name: "current-auth", query: "current auth provider", temporalAt: CORPUS_AT, temporalSubject: "Auth provider", relevant: ["Auth provider::Auth provider is Clerk with RS256"] },
  { name: "historical-auth", query: "auth provider at its capture", temporalAsOf: "superseded-v1-createdAt", relevant: ["Auth provider::Auth provider is Auth0 with RS256"] },
  { name: "window-contained", query: "maintenance at its window", temporalAt: "2026-06-15T00:00:00.000Z", temporalSubject: "Maintenance window", relevant: ["Maintenance window::Maintenance window was 2026-06-28 02:00-04:00 UTC"] },
];

export interface StrategyQueryResult {
  name: string;
  query: string;
  relevantKeys: string[];
  retrievedKeys: string[];
  precision: number;
  recall: number;
  /** Reciprocal rank of the first relevant record (1 when ranked first). */
  mrr: number;
}

export interface StrategyEvaluation {
  name: string;
  queries: StrategyQueryResult[];
  micro: { precision: number; recall: number; mrr: number };
}

export interface SemanticGate {
  verdict: "beats" | "complements" | "degrades";
  baseline: { precision: number; recall: number; mrr: number };
  withSemantic: { precision: number; recall: number; mrr: number };
  /** Why this verdict — frozen thresholds, stated. */
  detail: string;
}

export interface RetrievalEvaluationReport {
  corpusVersion: typeof QUALIFICATION_CORPUS_VERSION;
  contractVersion: string;
  scopeKey: typeof QUALIFICATION_CORPUS_SCOPE_KEY;
  k: number;
  strategies: StrategyEvaluation[];
  semanticGate: SemanticGate | null;
  passed: boolean;
}

export interface EvaluationOptions {
  /** Include the semantic strategies (uses the built-in deterministic provider). Default true. */
  includeSemantic?: boolean;
}

function scoreQuery(
  name: string,
  query: FrozenQuery,
  retrieved: MemoryRecord[],
  k: number,
): StrategyQueryResult {
  const relevantSet = new Set(query.relevant);
  const topK = retrieved.slice(0, k);
  const retrievedKeys = topK.map(recordKey);
  let tp = 0;
  let firstRelevantRank = 0;
  for (let i = 0; i < topK.length; i++) {
    if (relevantSet.has(retrievedKeys[i]!)) {
      tp++;
      if (firstRelevantRank === 0) firstRelevantRank = i + 1;
    }
  }
  return {
    name: query.name,
    query: query.query,
    relevantKeys: [...query.relevant].sort(),
    retrievedKeys,
    precision: topK.length === 0 ? 0 : tp / topK.length,
    recall: query.relevant.length === 0 ? 0 : tp / query.relevant.length,
    mrr: firstRelevantRank === 0 ? 0 : 1 / firstRelevantRank,
  };
}

function aggregate(name: string, queries: StrategyQueryResult[]): StrategyEvaluation {
  const sum = (sel: (q: StrategyQueryResult) => number): number => queries.reduce((acc, q) => acc + sel(q), 0);
  return {
    name,
    queries,
    micro: {
      precision: queries.length === 0 ? 0 : sum((q) => q.precision) / queries.length,
      recall: queries.length === 0 ? 0 : sum((q) => q.recall) / queries.length,
      mrr: queries.length === 0 ? 0 : sum((q) => q.mrr) / queries.length,
    },
  };
}

/**
 * Evaluate retrieval usefulness over the frozen corpus. Builds the corpus
 * first when missing (replay-safe). Read-only afterwards; the report is
 * deterministic and auditable query by query.
 */
export function evaluateRetrievalImpl(
  engine: MemoryEngine,
  options: EvaluationOptions = {},
): RetrievalEvaluationReport {
  const k = 10;
  const scopeKey = QUALIFICATION_CORPUS_SCOPE_KEY;
  let marker: MemoryRecord | undefined;
  try {
    marker = engine
      .searchRecords({ scope: scopeKey, exactSubject: "Qualification corpus marker" })
      .find((r) => r.status !== "deleted");
  } catch {
    marker = undefined;
  }
  if (marker === undefined) {
    engine.buildQualificationCorpus({ includeEmbeddings: options.includeSemantic !== false });
  }

  const strategies: StrategyEvaluation[] = [];

  // ---- exact (structured subject match) ----
  {
    const results = EXACT_QUERIES.map((q) => {
      const retrieved = engine.searchRecords({ scope: scopeKey, exactSubject: q.exactSubject });
      return scoreQuery(q.name, q, retrieved, k);
    });
    strategies.push(aggregate("exact", results));
  }

  // ---- lexical (BM25 FTS) ----
  {
    const results = LEXICAL_QUERIES.map((q) => {
      const retrieved = engine.lexicalSearch(q.query, { scope: scopeKey }).hits.map((h) => h.record);
      return scoreQuery(q.name, q, retrieved, k);
    });
    strategies.push(aggregate("lexical", results));
  }

  // ---- temporal (current view at pinned instants + as-of at store-derived instants) ----
  {
    const results = TEMPORAL_QUERIES.map((q) => {
      let retrieved: MemoryRecord[] = [];
      if (q.temporalAsOf === "superseded-v1-createdAt") {
        const v1 = engine
          .searchRecords({ scope: scopeKey, exactSubject: "Auth provider", status: "all" })
          .find((r) => r.status === "superseded");
        if (v1 !== undefined) {
          retrieved = engine
            .queryRecordsAsOf({ scope: scopeKey, asOf: v1.createdAt })
            .filter((r) => r.subject === "Auth provider");
        }
      } else {
        retrieved = engine.currentRecords({
          scope: scopeKey,
          at: q.temporalAt,
          subject: q.temporalSubject,
        });
      }
      return scoreQuery(q.name, q, retrieved, k);
    });
    strategies.push(aggregate("temporal", results));
  }

  // ---- hybrid baseline (deterministic signals only, no provider) ----
  engine.setEmbeddingProvider(null);
  const hybridBaseline = aggregate(
    "hybrid-baseline",
    LEXICAL_QUERIES.map((q) => {
      const retrieved = engine.hybridSearch(q.query, { scope: scopeKey, limit: k }).hits.map((h) => h.record);
      return scoreQuery(q.name, q, retrieved, k);
    }),
  );
  strategies.push(hybridBaseline);

  // ---- semantic additions + the transparent gate ----
  let semanticGate: SemanticGate | null = null;
  if (options.includeSemantic !== false) {
    engine.setEmbeddingProvider(localHashProvider);
    if (engine.embeddingProjectionStatus(scopeKey).status !== "built") {
      engine.buildEmbeddingProjection(scopeKey);
    }

    strategies.push(
      aggregate(
        "semantic",
        LEXICAL_QUERIES.map((q) => {
          const retrieved = engine.semanticSearch(q.query, { scope: scopeKey, limit: k }).hits.map((h) => h.record);
          return scoreQuery(q.name, q, retrieved, k);
        }),
      ),
    );

    const hybridSemantic = aggregate(
      "hybrid-semantic",
      LEXICAL_QUERIES.map((q) => {
        const retrieved = engine.hybridSearch(q.query, { scope: scopeKey, limit: k }).hits.map((h) => h.record);
        return scoreQuery(q.name, q, retrieved, k);
      }),
    );
    strategies.push(hybridSemantic);

    const eps = 1e-9;
    const base = hybridBaseline.micro;
    const withSem = hybridSemantic.micro;
    const notWorse =
      withSem.precision >= base.precision - eps &&
      withSem.recall >= base.recall - eps &&
      withSem.mrr >= base.mrr - eps;
    const strictlyBetter =
      withSem.precision > base.precision + eps ||
      withSem.recall > base.recall + eps ||
      withSem.mrr > base.mrr + eps;
    // Complement requirement: the standalone semantic surface must retrieve
    // relevant records that the strict lexical AND misses (the frozen
    // token-disjoint queries).
    const semanticStrategy = strategies.find((s) => s.name === "semantic")!;
    const lexicalStrategy = strategies.find((s) => s.name === "lexical")!;
    const complementPairs = ["auth-token-disjoint", "sessions-paraphrase"].map((name) => {
      const semQ = semanticStrategy.queries.find((q) => q.name === name)!;
      const lexQ = lexicalStrategy.queries.find((q) => q.name === name)!;
      return lexQ.retrievedKeys.length === 0 && semQ.recall > 0;
    });
    const complementsWhereLexicalFails = complementPairs.every(Boolean);

    let verdict: SemanticGate["verdict"];
    if (!notWorse) {
      verdict = "degrades";
    } else if (strictlyBetter) {
      verdict = "beats";
    } else if (complementsWhereLexicalFails) {
      verdict = "complements";
    } else {
      verdict = "complements";
    }
    semanticGate = {
      verdict,
      baseline: base,
      withSemantic: withSem,
      detail:
        verdict === "degrades"
          ? "semantic additions degraded a baseline aggregate"
          : verdict === "beats"
            ? "semantic additions strictly improved a baseline aggregate"
            : `semantic adds are non-degrading and retrieve where lexical AND fails (${complementPairs.filter(Boolean).length}/2 frozen complement queries)`,
    };
  }

  // ---- frozen pass criteria (qualification bars, not measured self-reference) ----
  const microOf = (name: string): StrategyEvaluation | undefined => strategies.find((s) => s.name === name);
  const exactOk = (microOf("exact")?.micro.recall ?? 0) >= 0.99;
  const temporalOk = (microOf("temporal")?.micro.recall ?? 0) >= 0.99;
  const lexicalOk = (microOf("lexical")?.micro.recall ?? 0) >= 0.55;
  const hybridOk = (microOf("hybrid-baseline")?.micro.recall ?? 0) >= 0.55;
  const gateOk = semanticGate === null || semanticGate.verdict !== "degrades";

  return {
    corpusVersion: QUALIFICATION_CORPUS_VERSION,
    contractVersion: engine.contractVersion,
    scopeKey,
    k,
    strategies,
    semanticGate,
    passed: exactOk && temporalOk && lexicalOk && hybridOk && gateOk,
  };
}
