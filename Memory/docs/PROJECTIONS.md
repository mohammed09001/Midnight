# Midnight Memory — Index Rebuild & Corruption Recovery (v1.10.0)

Implemented in `src/engine/projections.ts`. Task 26, Phase IV.

## Principle

Canonical records (and the immutable revision log) are the ONLY Memory truth.
Every derived projection — the FTS lexical index, the embedding projection,
and the on-demand entity/graph projections — is disposable and rebuildable
from canonical records. A corrupted derived projection NEVER corrupts Memory
truth: it is detected, repaired (rebuilt), and the canonical records stay
untouched.

## What can be checked

`engine.checkProjectionIntegrity(scope?)` / `memory.projections {action:'check'}`:

| Projection | Check | Corruption example |
|---|---|---|
| `lexical` | probes every indexable canonical record (status ≠ deleted) against the FTS index by its first subject token | a deleted/dropped index entry (undetected by FTS5 `integrity-check` on external-content tables) |
| `embedding` | orphan rows (embedding rows whose record no longer exists) and projection metadata vs actual row count | a deleted or stray embedding row; metadata/row-count mismatch |
| `graph` / `entity` | computed on demand — no stored state to corrupt | (always `ok`) |

`healthy` is true when NO projection is `corrupted`; an optional projection
that is `unavailable` (no embedding provider) or `not_built` is NOT corruption.

## Rebuild

`engine.rebuildAllProjections({scope?, includeSensitive?})` /
`memory.projections {action:'rebuild'}` rebuilds every projection from
canonical records: FTS index, entity projection, graph projection (per scope),
and the embedding projection (per scope, only when a provider is configured).
Each rebuild emits its observability event (`memory.index.rebuilt`,
`memory.entities.projection.rebuilt`, `memory.graph.projection.rebuilt`,
`memory.embeddings.projection.rebuilt`).

## Repair

`engine.repairProjections({scope?, includeSensitive?})` /
`memory.projections {action:'repair'}` runs the integrity check, rebuilds ONLY
the corrupted projections, and returns `{repaired, report}` with the fresh
post-repair integrity report. Canonical records are never modified.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Corrupted projection | reported `corrupted` (never thrown); `healthy: false` |
| No embedding provider | embedding reported `unavailable` (not corruption) |
| Provider configured but fails at runtime (Task 41) | typed `MEMORY_EMBEDDINGS_UNAVAILABLE` (cause preserved) on build/search; the lexical/entity/graph projections are unaffected and hybrid retrieval degrades the semantic signal instead of failing |
| Corrupt stored vector row (Task 41) | skipped during semantic ranking and counted in `diagnostics.skippedCorrupt`; the next embedding rebuild (`rebuildEmbeddingProjection` / `rebuildAllProjections`) restores it from canonical records |
| Unknown scope | `MEMORY_NOT_FOUND` |
| Bad action | `MEMORY_VALIDATION_FAILED` |

## Agent neutrality / game independence

All checks/rebuilds are deterministic functions over the canonical store — no
LLM, no external graph/vector database, no game dependency. Terminal surface:
`projections check|rebuild|repair [--scope K] [--include-sensitive]`.