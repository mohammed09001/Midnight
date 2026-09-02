# Midnight Memory — Deterministic Retrieval Baseline (v1.6.0)

Implemented in `src/engine/retrieval.ts` (+ `records.ts` structured filters,
`src/engine/ranking.ts`, `src/engine/dedup.ts`, `src/engine/fusion.ts`),
migration 8. Research: mem0 multi-signal retrieval shape ADAPTED (BM25 now;
semantic + entity signals DEFERRED — no provider), getzep/graphiti temporal
recipes ADAPTED, provider/LLM dependencies REJECTED. FTS5 behaviors per
sqlite.org/fts5.html (accessed 2026-08-30); SQLite 3.50.4 via node:sqlite.

## Task 14 — structured-filter retrieval

`searchRecords` / `memory.search` accept, composable with all previous
filters: `exactSubject`, `sourceEngine` (evidence refs), `actor` (canonical
actor key), `confidenceMin`/`confidenceMax`, `validAt` (validity window
contains instant), `createdAfter/Before`, `observedAfter/Before`. Malformed
timestamps/confidences are typed errors. Exact identity retrieval remains
`memory.get` (record id) and `scope get` (project key / scope id).

## Task 15 — lexical/BM25 search

`engine.lexicalSearch(query, {scope?, status?, limit?})` / `memory.lexical`:

- **Index**: FTS5 external-content table over `memory_records`
  (subject, content, tags) — a **rebuildable derived index**, never
  canonical truth; kept consistent by triggers on the canonical table and
  rebuildable via `engine.rebuildSearchIndex()` (`memory.index.rebuilt`).
- **Ranking**: `bm25()` with column weights subject 5.0 / tags 3.0 /
  content 1.0; scores reported positive-better.
- **Exact terms**: `unicode61` tokenizer (case-insensitive, diacritics
  folded, **no stemming**) — "retry" does not match "retries".
- **Safety**: user queries are tokenized into barewords and quoted — FTS5
  operators in user input are inert.
- **Explanations**: each hit reports which fields matched
  (subject/content/tags) plus a snippet.
- **Diagnostics**: parsed `terms`, `totalMatches`, `truncated`, tokenizer
  and index mode.
- **Lifecycle-consistent**: revise updates the index (triggers), tombstone
  scrubbing removes hits, purge deletes entries; default view excludes
  tombstones, `"all"` includes.

## Task 16 — temporal retrieval

Three canonical questions, explicit validity semantics:

| Question | API / contract | Semantics |
|---|---|---|
| "What is the current decision?" | `currentRecords({scope, subject?, at?})` / `memory.current` | `active` records whose validity window contains `at` (default now) |
| "What was true at date X?" | `queryRecordsAsOf` / `memory.search {asOf}` | bi-temporal belief reconstruction (docs/TEMPORAL.md) |
| "How did the decision change?" | `decisionTimeline(scope, subject)` / `memory.timeline` | every non-deleted version of the subject ordered oldest → newest with status, `supersededAt`, and `supersededReason` |

All three views agree on the same dataset by construction (verified).

## Task 17 — provenance-aware ranking

`engine.rankedSearch(query, {scope?, limit?, at?})` / `memory.ranked`:

- Re-ranks the full BM25 result set by a **visible** blend of lexical
  relevance (60%) and a deterministic **provenance score** (40%).
- The provenance score is a weighted combination of five explicit signals:
  authority tier (structural, docs/AUTHORITY.md), directness (agent-derived /
  inferred / no-evidence reduce it), currency (active + within validity
  window), confidence, and contradiction membership.
- **Lower-confidence and contradicted records are EXPOSED, never silently
  hidden**: they are flagged (`lowConfidence`, `contradicted`, `historical`)
  and ranked below their high-authority current peers, but remain in the
  result list.
- Each hit reports its per-signal breakdown and human-readable notes, so a
  terminal/tool caller can see WHY one record outranks another.
- Deterministic and provider-free (no LLM/embedding scoring).

## Task 18 — deduplication and near-duplicate handling

`engine.analyzeDuplicates(scope, {subject, content, evidenceRefs?})` /
`memory.duplicates`, and `engine.findCandidateDuplicates(scope)`:

- **Exact duplicate**: identical normalized content (SHA-256 content hash) in
  the same scope.
- **Normalized / near duplicate**: same normalized subject with high token-set
  Jaccard overlap (≥ 0.85 near; ≥ 0.6 borderline).
- **Corroborating vs duplicate**: same subject with genuinely distinct content
  AND its own distinct evidence basis is classified as independently
  corroborating, NOT a duplicate to collapse. Records without an evidence
  basis cannot corroborate (independent).
- **Idempotency preserved**: replay-safe writes remain the existing
  `idempotencyKey` + content-hash machinery (docs/PERSISTENCE.md); this module
  adds detection + classification, never a second idempotency path.
- Provider-free: token/Jaccard matching is deterministic and self-hosted
  (embedding-based dedup from mem0 ADAPTED in intent, provider REJECTED).

## Task 19 — explainable multi-signal fusion

`engine.fusedSearch(query, {scope?, exactSubject?, tag?, kind?, limit?, at?, weights?})` /
`memory.fused`:

- Combines five deterministic signals — **lexical** (BM25), **structured**
  (exactSubject/tag/kind match), **temporal** (currency at `at`),
  **provenance** (Task 17 score), **relation** (outgoing + incoming relation
  hints / contradiction exposure) — with visible per-signal weights
  (defaults: 0.3 / 0.15 / 0.2 / 0.25 / 0.1).
- **Never an opaque score**: every hit reports each signal's normalized
  `value`, `weight`, and `contribution`, plus a deterministic explanation
  line; `total` is literally the sum of contributions.
- Custom `weights` merge over the defaults (Partial), so callers can re-weight
  the fusion transparently.

## Task 25 — hybrid lexical + semantic + relation retrieval

`engine.hybridSearch(query, {scope?, limit?, at?, weights?})` / `memory.hybrid`:

- The deterministic baseline ALWAYS runs and explains itself: lexical (BM25)
  + structured + temporal + provenance + relation, each with visible
  value/weight/contribution.
- The OPTIONAL semantic signal (Task 23 embedding projection) is fused ONLY
  when an embedding provider is configured AND the scope's projection is built
  ("only after baseline evaluation"). Otherwise it is reported
  `available: false` with the reason — never silently assumed.
- `path` explains the retrieval path: which signals participated, the
  semantic provider/model used, or why the semantic signal was unavailable
  (no provider / projection not built / record excluded by the privacy gate).
- Provider-free deterministic signals work with zero configuration; adding a
  provider + built projection upgrades the same query to hybrid fusion.

## Task 20 — retrieval traces and memory.explain

Two things a caller needs to trust a result without re-deriving it: why a
record was returned, and what a single record's full explanation is missing.

- **`memory.explain` enrichment** (`engine.explainRecord(recordId, at?)`):
  alongside the existing provenance/authority/evidenceRefs/lifecycle-events,
  now also returns `validFrom`/`validUntil` and `validity: {at,
  currentlyValid}` (the same window-containment check `memory.current`
  uses, evaluated at `at`, default now); `contradiction: {groupId, status,
  groupSize}` (open/resolved group membership, `null` when not contested);
  and `evidenceGaps: string[]` — deterministic findings distinct from the
  authority assessment: zero evidence refs, or a ref whose `expiresAt` has
  lapsed by `at` (reuses `retention.ts`'s `isEvidenceRefExpired`).
- **Retrieval traces** on `memory.search` (both the structured-filter and
  `asOf` branches, `engine.searchRecordsTraced`/`queryRecordsAsOfTraced`)
  and `memory.current` (`engine.currentRecordsTraced`): each now returns
  `{records, trace}`. `trace.appliedFilters` echoes only the filter keys
  the caller actually set; `trace.matches[recordId]` lists, per record, a
  plain-language reason for each applied filter it satisfies (citing the
  record's real field value, e.g. `"confidence 0.92 >= confidenceMin
  0.8"`); `trace.totalMatches`/`truncated` report the untruncated match
  count via the same clauses/params reused for a `COUNT(*)` — the same
  pattern Task 15's `memory.lexical` already established. This mirrors
  `memory.lexical`'s existing per-hit `explanation`/`diagnostics` shape,
  extended to the filter-based (non-ranked) retrieval paths.
- `memory.timeline` is unchanged: it has no filter/match semantics to
  trace (a full, unfiltered subject evolution).
- Zero new dependencies; purely deterministic, computed from already-loaded
  record fields — no additional queries beyond one `COUNT(*)` per traced
  call.
