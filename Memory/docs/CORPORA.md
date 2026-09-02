# Midnight Memory — Frozen Qualification Corpora (v1.22.0)

Implemented in `src/engine/corpora.ts`. Task 42, Phase VIII.

## Principle

A DETERMINISTIC, VERSIONED corpus of Memory records — `qualification-v1`,
frozen at `QUALIFICATION_CORPUS_VERSION` — that exercises every qualification
area (current facts, historical facts, contradictions, supersession,
duplicates, privacy restrictions, provenance variety) plus a verifier that
freezes the engine's EXPECTED outcomes into a stable, subject-keyed report.
Qualification results are comparable across runs, machines, and restarts:
two independent builds of the same corpus version produce identical
verification reports.

## Frozen content (v1.0.0 — 18 records)

| Area | Records |
|---|---|
| Current facts | `Rate limit` (user decision, internal), `Retry backoff` (public, relation hint) |
| Duplicates | `Deploy window` ×3 — exact pair (identical content+evidence) and one distinct corroborating record |
| Contradictions | `Max concurrent sessions` pair — detected, registered, RESOLVED (winner supersedes) |
| Historical | `Maintenance window` (expired), `Deployment region` ×2 (adjacent windows — lineage, not contradiction), `Legacy cache` (archived), `Auth provider` v1→v2 supersession chain |
| Privacy | `API key rotation` (sensitive — queryable, never exported) |
| Provenance | human / agent / tool / engine actors × user_note / user_decision / repository_evidence / study_finding / agent_inference / performance_evidence source kinds, confidences 0.6–1.0 |

## Determinism contract

- Corpus content is frozen in code; materialization goes ONLY through the
  public engine API (no direct store writes; the store reference is used
  solely for the engine's own event append).
- Replay safety: Task-7 idempotency keys on every direct write; a corpus
  marker record gates re-entry; supersede/resolve/archive steps check state
  before acting.
- Temporal filters pin to `CORPUS_AT` (2026-07-01) or to instants READ BACK
  from the store (as-of checks use the superseded record's capture time);
  wall-clock build time never appears in expectations.
- The report carries NO volatile fields (no record ids, no build timestamps)
  and names every check with a stable identifier.

## Verify (read-only)

`engine.verifyQualificationCorpus({includeEmbeddings?})` →
`{corpusVersion, contractVersion, scopeKey, embeddingsChecked, checks, passed}`
with stable checks: `scope-exists`, `record-counts`, `lexical-current-facts`,
`current-view`, `historical-absent-from-current`, `as-of-supersession`,
`supersession-lineage`, `contradiction-pairs`, `duplicates`,
`privacy-excerpts`, `provenance-filters`, `secret-rejected`, `embeddings`,
`corpus-event`. A corpus that cannot fail would be worthless: tampering
(e.g. retracting a record through the public API) or a missing corpus makes
specific named checks FAIL.

## Build (replay-safe)

`engine.buildQualificationCorpus({includeEmbeddings?})` →
`{corpusVersion, scopeKey, built, recordCount, embeddings}`; `built: false`
when already materialized. Emits `memory.corpus.built`. The optional
embedding area uses ONLY the built-in deterministic provider (17 embedded,
1 skipped for privacy). The builder REFUSES to materialize on a
non-conforming engine: secret-class material must be rejected with
`MEMORY_PRIVACY_VIOLATION`.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Corpus not materialized | verify fails `scope-exists` (exit 1 on the CLI) — never a vacuous pass |
| Tampered/degraded store | the specific named checks FAIL; `passed: false` |
| `includeEmbeddings: false` | build/verify skip the embedding area (no provider needed); all other areas still verify |
| Secret-class write attempted | `MEMORY_PRIVACY_VIOLATION` — the build aborts loudly (boundary proof) |
| Crash mid-build (no marker) | re-run rebuilds idempotently; lifecycle steps skip already-applied transitions |

## Agent neutrality / game independence

Frozen fixtures and deterministic checks — no LLM, no external provider, no
MCP host, no sibling engine, no game. Terminal surface:
`corpus build|verify [--no-embeddings] [--path <report.json>]`
(verify exits 1 when any frozen expectation fails; `--path` writes the
report as an evidence artifact).
