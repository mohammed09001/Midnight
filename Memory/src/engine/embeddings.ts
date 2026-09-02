/**
 * Optional semantic embedding projection (Task 23).
 *
 * Provider-neutral embeddings behind an interface AND a privacy gate. The
 * Memory Engine fully functions WITHOUT embeddings; the projection is an
 * OPTIONAL, DERIVED, REBUILDABLE artifact that never becomes canonical truth
 * (docs/BOUNDARY.md).
 *
 * - Provider-neutral: the engine defines a sync `EmbeddingProvider` interface
 *   and never imports any concrete provider. A caller injects a provider via
 *   `engine.setEmbeddingProvider(...)`. `localHashProvider` is a built-in,
 *   deterministic, dependency-free adapter that satisfies the interface so the
 *   whole pipeline works self-hosted; real semantic providers (OpenAI, Cohere,
 *   local ONNX, …) plug in behind the same interface.
 * - Privacy gate: by default only `public` and `internal` records are
 *   embedded; `sensitive` records are EXCLUDED unless the caller explicitly
 *   opts in (`includeSensitive: true`). Tombstoned records are never embedded.
 *   Skipped-for-privacy records are counted and reported.
 * - Model/version recorded: every embedding row and the projection metadata
 *   carry provider/model/version; the status surfaces `rebuildRecommended`
 *   when the current provider's model/version differs from what was stored.
 * - Complete rebuild: `rebuildEmbeddingProjection` re-embeds the gated corpus
 *   and emits `memory.embeddings.projection.rebuilt`.
 * - Task 41 graceful degradation: a provider that is CONFIGURED but FAILS at
 *   runtime is embeddings-unavailable (typed MEMORY_EMBEDDINGS_UNAVAILABLE
 *   with the original error as cause); a corrupt derived vector row is
 *   skipped and reported. Lexical/structured Memory keeps working.
 *
 * Research: mem0's semantic retrieval and getzep/graphiti's hybrid search are
 * ADAPTED in intent (provider abstraction, derived vector projection) but the
 * mandatory-LLM/embedding assumption is REJECTED — Memory must run without a
 * provider (main @ 2026-08-30).
 */
import { EmbeddingsNotBuiltError, EmbeddingsUnavailableError, ValidationError } from "../contracts/errors.ts";
import type { MemoryRecord, PrivacyClass } from "../contracts/types.ts";
import { getScopeImpl } from "./scopes.ts";
import { rowToRecord } from "./records.ts";
import { getContentPolicy, checkExportable } from "./privacy.ts";
import type { MemoryStore } from "./store.ts";

/** Synchronous, provider-neutral embedding interface. */
export interface EmbeddingProvider {
  /** Stable provider identity (e.g. "local-hash", "external:openai"). */
  readonly name: string;
  /** Model identifier (e.g. "feature-hash-v1", "text-embedding-3-small"). */
  readonly model: string;
  /** Model version for staleness detection (e.g. "1.0.0"). */
  readonly version: string;
  /** Embed texts into fixed-dimension vectors. Deterministic for built-in providers. */
  embed(texts: string[]): Float32Array[];
}

/** Default privacy gate: sensitive records are skipped unless explicitly included. */
export interface EmbeddingBuildOptions {
  /** Explicit opt-in to embed `sensitive` records (the privacy gate). */
  includeSensitive?: boolean;
}

export interface EmbeddingProjectionStatus {
  /** unavailable (no provider) | not_built (provider set, not yet embedded) | built. */
  status: "unavailable" | "not_built" | "built";
  scopeId: string;
  reason?: string;
  provider?: string;
  model?: string;
  version?: string;
  vectorDim?: number;
  recordCount?: number;
  skippedPrivacy?: number;
  builtAt?: string;
  /** True when the stored model/version differs from the current provider's. */
  rebuildRecommended?: boolean;
}

export interface EmbeddingProjectionEntry {
  recordId: string;
  subject: string;
  privacyClass: Exclude<PrivacyClass, "secret">;
  vector: Float32Array;
}

export interface EmbeddingProjection extends EmbeddingProjectionStatus {
  embeddings: EmbeddingProjectionEntry[];
}

export interface SemanticHit {
  record: MemoryRecord;
  /** Cosine similarity in [-1, 1]; higher = more similar. */
  score: number;
}

export interface SemanticSearchResult {
  query: string;
  status: "built";
  provider: string;
  model: string;
  version: string;
  hits: SemanticHit[];
  diagnostics: {
    totalEmbedded: number;
    truncated: boolean;
    /** Task 41: corrupt derived vector rows skipped during ranking (rebuildable). */
    skippedCorrupt?: number;
  };
}

// ---- deterministic built-in provider (dependency-free, self-hosted) ---------

/** FNV-1a 32-bit hash — deterministic across processes. */
function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

const LOCAL_DIM = 64;

/** Feature-hash embedding: deterministic bag-of-token-hashes, L2-normalized. */
function localHashEmbed(texts: string[]): Float32Array[] {
  return texts.map((text) => {
    const tokens = text
      .toLowerCase()
      .split(/[^\p{L}\p{N}_]+/u)
      .filter((t) => t.length > 0);
    const v = new Float32Array(LOCAL_DIM);
    for (const token of tokens) {
      const h = fnv1a(token);
      const idx = h % LOCAL_DIM;
      const sign = (h >>> 8) & 1 ? 1 : -1;
      v[idx] = (v[idx] ?? 0) + sign;
    }
    const norm = Math.sqrt(Array.from(v).reduce((sum, x) => sum + x * x, 0));
    if (norm > 0) {
      for (let i = 0; i < LOCAL_DIM; i++) v[i] = (v[i] ?? 0) / norm;
    }
    return v;
  });
}

/**
 * Built-in deterministic embedding provider. NOT a true semantic model — it is
 * a stable feature-hash vector projection that satisfies the interface so the
 * engine works self-hosted with zero dependencies. Real providers replace it.
 */
export const localHashProvider: EmbeddingProvider = {
  name: "local-hash",
  model: "feature-hash-v1",
  version: "1.0.0",
  embed: localHashEmbed,
};

export function cosineSimilarity(a: Float32Array, b: Float32Array): number {
  const n = Math.min(a.length, b.length);
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < n; i++) {
    const ai = a[i] ?? 0;
    const bi = b[i] ?? 0;
    dot += ai * bi;
    na += ai * ai;
    nb += bi * bi;
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb);
  return denom === 0 ? 0 : dot / denom;
}

// ---- projection status -------------------------------------------------------

export function embeddingProjectionStatusImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  scopeOrProjectKey: string,
): EmbeddingProjectionStatus {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  if (provider === null) {
    return {
      status: "unavailable",
      scopeId: scope.scopeId,
      reason: "no embedding provider configured (Memory functions without embeddings)",
    };
  }
  const db = store.ensureOpen();
  const row = db
    .prepare("SELECT * FROM memory_embedding_projections WHERE scope_id = ?")
    .get(scope.scopeId) as Record<string, unknown> | undefined;
  if (row === undefined) {
    return { status: "not_built", scopeId: scope.scopeId };
  }
  const storedVersion = String(row["version"]);
  return {
    status: "built",
    scopeId: scope.scopeId,
    provider: String(row["provider"]),
    model: String(row["model"]),
    version: storedVersion,
    vectorDim: Number(row["vector_dim"]),
    recordCount: Number(row["record_count"]),
    skippedPrivacy: Number(row["skipped_privacy"]),
    builtAt: String(row["built_at"]),
    rebuildRecommended:
      storedVersion !== provider.version || String(row["model"]) !== provider.model,
  };
}

// ---- build / rebuild ---------------------------------------------------------

function requireProvider(provider: EmbeddingProvider | null): EmbeddingProvider {
  if (provider === null) {
    throw new EmbeddingsUnavailableError(
      "no embedding provider configured; set one via engine.setEmbeddingProvider(...) (Memory functions fully without embeddings)",
    );
  }
  return provider;
}

/**
 * Task 41: run a provider embed with explicit degradation. A provider that is
 * CONFIGURED but FAILS at runtime (network/model error, wrong result arity) is
 * a form of "embeddings unavailable" — surfaced as the stable typed code
 * MEMORY_EMBEDDINGS_UNAVAILABLE (with the original error as `cause`), never as
 * an untyped provider exception. Lexical/structured Memory keeps working.
 */
export function embedWithProvider(provider: EmbeddingProvider, texts: string[]): Float32Array[] {
  let vectors: Float32Array[];
  try {
    vectors = provider.embed(texts);
  } catch (err) {
    throw new EmbeddingsUnavailableError(
      `embedding provider '${provider.name}' failed at runtime (Memory functions fully without embeddings): ${err instanceof Error ? err.message : String(err)}`,
      { cause: err },
    );
  }
  if (!Array.isArray(vectors) || vectors.length !== texts.length) {
    throw new EmbeddingsUnavailableError(
      `embedding provider '${provider.name}' violated its contract: expected ${texts.length} vector(s), got ${Array.isArray(vectors) ? vectors.length : typeof vectors}`,
    );
  }
  return vectors;
}

/** Parse a stored embedding vector; null when the derived row is corrupt. */
export function parseStoredVector(row: Record<string, unknown>): Float32Array | null {
  try {
    return Float32Array.from(JSON.parse(String(row["vector_json"])) as number[]);
  } catch {
    return null;
  }
}

/**
 * Build (or fully rebuild) the derived embedding projection for a scope.
 * Embeds the privacy-gated corpus with the CURRENT provider, records
 * model/version, and stores the projection (a derived table, never canonical
 * truth). Emits a build event.
 */
export function buildEmbeddingProjectionImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  scopeOrProjectKey: string,
  options: EmbeddingBuildOptions = {},
  eventType: "memory.embeddings.projection.built" | "memory.embeddings.projection.rebuilt" =
    "memory.embeddings.projection.built",
): EmbeddingProjection {
  const active = requireProvider(provider);
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const includeSensitive = options.includeSensitive === true;
  const db = store.ensureOpen();
  const builtAt = new Date().toISOString();

  const rows = db
    .prepare(
      `SELECT record_id, subject, content, privacy_class FROM memory_records
       WHERE scope_id = ? AND status != 'deleted'`,
    )
    .all(scope.scopeId) as Array<Record<string, unknown>>;

  const eligible: Array<{ recordId: string; subject: string; privacyClass: Exclude<PrivacyClass, "secret">; text: string }> = [];
  let skippedPrivacy = 0;
  // Task 37: content-class policy — only exportable records are embedded.
  const policy = getContentPolicy(store, scope.scopeId);
  for (const row of rows) {
    const privacyClass = String(row["privacy_class"]) as Exclude<PrivacyClass, "secret">;
    if (!checkExportable({ privacyClass }, policy, includeSensitive).exportable) {
      skippedPrivacy++;
      continue;
    }
    eligible.push({
      recordId: String(row["record_id"]),
      subject: String(row["subject"]),
      privacyClass,
      text: `${String(row["subject"])} ${String(row["content"])}`,
    });
  }

  const vectors = embedWithProvider(active, eligible.map((e) => e.text));
  const embeddings: EmbeddingProjectionEntry[] = eligible.map((e, i) => ({
    recordId: e.recordId,
    subject: e.subject,
    privacyClass: e.privacyClass,
    vector: vectors[i]!,
  }));

  db.exec("BEGIN IMMEDIATE;");
  try {
    db.prepare("DELETE FROM memory_embeddings WHERE record_id IN (SELECT record_id FROM memory_records WHERE scope_id = ?)").run(scope.scopeId);
    // Task 45: the rebuild is also the recovery path for orphaned derived
    // rows (e.g. from a privacy purge) — orphans can never survive a rebuild.
    db.prepare("DELETE FROM memory_embeddings WHERE record_id NOT IN (SELECT record_id FROM memory_records)").run();
    db.prepare("DELETE FROM memory_embedding_projections WHERE scope_id = ?").run(scope.scopeId);
    const insert = db.prepare(
      `INSERT INTO memory_embeddings (record_id, vector_json, provider, model, version, embedded_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
    );
    for (const e of embeddings) {
      insert.run(e.recordId, JSON.stringify(Array.from(e.vector)), active.name, active.model, active.version, builtAt);
    }
    db.prepare(
      `INSERT INTO memory_embedding_projections (scope_id, provider, model, version, vector_dim, record_count, skipped_privacy, built_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      scope.scopeId,
      active.name,
      active.model,
      active.version,
      embeddings[0]?.vector.length ?? 0,
      embeddings.length,
      skippedPrivacy,
      builtAt,
    );
    db.exec("COMMIT;");
  } catch (err) {
    db.exec("ROLLBACK;");
    throw err;
  }

  store.appendEvent(eventType, {
    scopeId: scope.scopeId,
    provider: active.name,
    model: active.model,
    version: active.version,
    recordCount: embeddings.length,
    skippedPrivacy,
  });

  return {
    status: "built",
    scopeId: scope.scopeId,
    provider: active.name,
    model: active.model,
    version: active.version,
    vectorDim: embeddings[0]?.vector.length ?? 0,
    recordCount: embeddings.length,
    skippedPrivacy,
    builtAt,
    rebuildRecommended: false,
    embeddings,
  };
}

export function rebuildEmbeddingProjectionImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  scopeOrProjectKey: string,
  options: EmbeddingBuildOptions = {},
): EmbeddingProjection {
  return buildEmbeddingProjectionImpl(store, provider, scopeOrProjectKey, options, "memory.embeddings.projection.rebuilt");
}

// ---- semantic search ---------------------------------------------------------

/**
 * Rank the built embedding projection against a query by cosine similarity.
 * Requires a provider AND a built projection (explicit failure otherwise).
 */
export function semanticSearchImpl(
  store: MemoryStore,
  provider: EmbeddingProvider | null,
  query: string,
  options: { scope?: string; limit?: number } = {},
): SemanticSearchResult {
  const active = requireProvider(provider);
  if (typeof query !== "string" || query.trim().length === 0) {
    throw new ValidationError("query must be a non-empty string");
  }
  const db = store.ensureOpen();
  let scopeId: string | null = null;
  if (options.scope !== undefined) {
    scopeId = getScopeImpl(store, options.scope).scopeId;
  }
  const meta = scopeId === null ? undefined : db
    .prepare("SELECT * FROM memory_embedding_projections WHERE scope_id = ?")
    .get(scopeId) as Record<string, unknown> | undefined;
  if (meta === undefined) {
    throw new EmbeddingsNotBuiltError(
      "embedding projection is not built for this scope; build it first (engine.buildEmbeddingProjection / memory.embeddings {action:'build'})",
    );
  }

  const [queryVector] = embedWithProvider(active, [query]);
  const clauses = ["e.provider = ?", "e.version = ?", "r.status != 'deleted'"];
  const params: Array<string | number> = [active.name, active.version];
  if (scopeId !== null) {
    clauses.push("r.scope_id = ?");
    params.push(scopeId);
  }
  const limit = Math.min(Math.max(options.limit ?? 10, 1), 100);
  const rows = db
    .prepare(
      `SELECT e.record_id, e.vector_json FROM memory_embeddings e
       JOIN memory_records r ON r.record_id = e.record_id
       WHERE ${clauses.join(" AND ")} ORDER BY e.embedded_at DESC`,
    )
    .all(...params) as Array<Record<string, unknown>>;

  // Task 41: a corrupt DERIVED vector row is skipped and reported — it can
  // never corrupt retrieval truth (docs/PROJECTIONS.md; repair via
  // engine.repairProjections).
  let skippedCorrupt = 0;
  const scored: Array<{ recordId: string; score: number }> = [];
  for (const row of rows) {
    const vector = parseStoredVector(row);
    if (vector === null) {
      skippedCorrupt++;
      continue;
    }
    scored.push({ recordId: String(row["record_id"]), score: cosineSimilarity(queryVector!, vector) });
  }

  const hits: SemanticHit[] = scored
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((h) => {
      const recordRow = db.prepare("SELECT * FROM memory_records WHERE record_id = ?").get(h.recordId) as Record<string, unknown>;
      return { record: rowToRecord(recordRow), score: h.score };
    });

  return {
    query,
    status: "built",
    provider: active.name,
    model: active.model,
    version: active.version,
    hits,
    diagnostics: { totalEmbedded: Number(meta["record_count"]), truncated: rows.length > hits.length, skippedCorrupt },
  };
}