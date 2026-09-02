# Library Memory Engine — Optional Semantic Embedding Projection (v1.8.0)

Implemented in `src/engine/embeddings.ts` (+ migration 9, `memory_embeddings`
/ `memory_embedding_projections` derived tables). Task 23, Phase IV.

## Principle

The Memory Engine fully functions WITHOUT embeddings. The semantic embedding
projection is OPTIONAL, provider-neutral, privacy-gated, and a DERIVED,
REBUILDABLE artifact that never becomes canonical truth (docs/BOUNDARY.md).

## Provider neutrality

The engine defines a synchronous interface:

```ts
interface EmbeddingProvider {
  readonly name: string;    // "local-hash" | "external:openai" | …
  readonly model: string;   // "feature-hash-v1" | "text-embedding-3-small" | …
  readonly version: string; // "1.0.0" | …
  embed(texts: string[]): Float32Array[];
}
```

A host injects a provider via `engine.setEmbeddingProvider(provider)`; the
engine imports no concrete provider. `localHashProvider` (exported from
`src/index.ts`) is a built-in, deterministic, dependency-free adapter
(feature-hash vectors) that satisfies the interface so the pipeline works
self-hosted; real semantic providers plug in behind the same interface.

Without a provider:
- `embeddingProjectionStatus(scope)` → `{status: "unavailable"}` (a status, not an error);
- `buildEmbeddingProjection` / `semanticSearch` → `MEMORY_EMBEDDINGS_UNAVAILABLE` (typed).

## Privacy gate

By default only `public` and `internal` records are embedded. `sensitive`
records are EXCLUDED unless the caller explicitly opens the gate
(`includeSensitive: true`). Tombstoned (`deleted`) records are NEVER embedded
(content is scrubbed). Records skipped for privacy are counted and reported as
`skippedPrivacy`.

## Model/version recorded + complete rebuild

Every embedding row and the per-scope projection metadata record
`provider`/`model`/`version` and `builtAt`. `embeddingProjectionStatus` reports
`rebuildRecommended: true` when the current provider's model/version differs
from what was stored, so stale projections are detectable.

- `buildEmbeddingProjection(scope, {includeSensitive?})` — embed the gated
  corpus now; emits `memory.embeddings.projection.built`.
- `rebuildEmbeddingProjection(scope, {includeSensitive?})` — complete rebuild;
  emits `memory.embeddings.projection.rebuilt`.
- Both write only the DERIVED tables (`memory_embeddings`,
  `memory_embedding_projections`) — canonical records are untouched.

## Semantic search

`semanticSearch(query, {scope?, limit?})` embeds the query with the current
provider and ranks the built projection by cosine similarity, returning
per-hit scores. It requires a configured provider
(`MEMORY_EMBEDDINGS_UNAVAILABLE` otherwise) and a built projection
(`MEMORY_EMBEDDINGS_NOT_BUILT` otherwise) — explicit failure, never a silent
fallback.

## Failure / degradation

| Condition | Behavior |
|---|---|
| No provider configured | `unavailable` status; typed `MEMORY_EMBEDDINGS_UNAVAILABLE` on build/search |
| Provider set, not built | `not_built` status; typed `MEMORY_EMBEDDINGS_NOT_BUILT` on search |
| Provider configured but FAILS at runtime (Task 41) | typed `MEMORY_EMBEDDINGS_UNAVAILABLE` with the original error as `cause` (also for provider contract violations, e.g. wrong vector count); a failed build leaves any existing projection intact; hybrid retrieval degrades the semantic signal and keeps the deterministic lexical baseline |
| Corrupt stored vector row (Task 41) | row skipped during semantic ranking; `diagnostics.skippedCorrupt` reports the count; the next embedding rebuild restores it from canonical records |
| Model changed since build | status `rebuildRecommended: true`; search still uses stored vectors (explicitly stale) |
| Empty query | `MEMORY_VALIDATION_FAILED` |

Task 41 invariant: structured/lexical Memory works with embeddings absent,
failing, or corrupt — the semantic projection is optional, derived, and
rebuildable, never a retrieval dependency.

## Agent neutrality / game independence

Provider-specific behavior lives behind the injected adapter (never in the
engine core); no agent product is special-cased; no game dependency. Terminal
surface: `embeddings status|build|rebuild --scope K [--include-sensitive]`,
`semantic search --q T [--scope K]` (both default to the built-in local
provider so the CLI works self-hosted).