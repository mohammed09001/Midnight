# Midnight Memory — Canonical Record Schema (v1.5.0)

Implemented in `src/contracts/types.ts` (contract), `src/engine/validation.ts`
(enforcement), migrations in `src/engine/store.ts`. Contract version: **1.0.0**.

## Canonical MemoryRecord

| Field | Type / shape | Rules |
|---|---|---|
| `recordId` | `mem_` + ULID | Immutable identity (docs/IDENTITIES.md) |
| `contractVersion` | semver string | Schema version stamped per record |
| `kind` | `fact \| decision \| preference \| observation \| note` | Required |
| `subject` | string ≤ 512, normalized (NFC, whitespace-collapsed) | Required, non-empty |
| `content` | normalized text ≤ 32768 chars | The canonical statement; hash-stamped |
| `contentHash` | SHA-256 hex of normalized content | Integrity + duplicate detection |
| `scopeId` | `scp_…` | Required; record belongs to exactly one scope |
| `provenance` | `{actor:{kind,name,agentType?}, method, capturedAt, sourceKind, derivedFrom?}` | Who/how/when; `sourceKind` drives authority (docs/AUTHORITY.md); `derivedFrom` required for agent summaries |
| `epistemicClass` | `observed \| derived \| inferred \| recommendation \| unknown` | Epistemic discipline: source evidence, derived fact, agent inference, recommendation and UNKNOWN remain distinguishable |
| `confidence` | number ∈ [0,1] | Required, finite |
| `evidenceRefs` | ≤ 32 × `{engine, ref, note?}` | **By reference ONLY** — unknown fields rejected; engines: repository_sync, repository_search, study_document, study_lineage_versioning, project_projection, context, midnight_synchronization, performance, analysis, memory, external |
| `relationHints` | ≤ 32 × `{type, target, note?, provenance?}` | type ∈ `related \| depends_on \| supports \| contradicts \| derived_from \| applies_to \| learned_from` (Task 21, docs/RELATIONS.md); target is a record id, `engine:<name>:<ref>`, or `entity:<kind>:<name>` (Task 22); `provenance {actor, method, capturedAt}` optional attribution |
| `tags` | ≤ 32 strings ≤ 64 chars each | Non-empty |
| `privacyClass` | `public \| internal \| sensitive` | `secret` is REFUSED pre-write (`MEMORY_PRIVACY_VIOLATION`); secrets live in the secure credential layer |
| `validFrom` / `validUntil` | ISO 8601, nullable | Temporal validity; `validUntil ≤ validFrom` rejected |
| `observedAt` | ISO 8601 | Bi-temporal **valid time** (when true in reality); defaults to record time. `createdAt`/`revisedAt` stay transaction time (docs/TEMPORAL.md) |
| `status` | `active \| superseded \| retracted \| expired \| archived \| deleted` | State machine (docs/RETENTION.md); `archived` = cold/restorable, `deleted` = tombstone |
| `revision` | integer ≥ 1 | Advances on revise/retract; history in `memory_record_revisions` (immutable rows: content, hash, provenance, reason, revisedAt) |
| `createdAt` / `revisedAt` | ISO 8601 | `createdAt` immutable |
| `supersedesId` / `supersededById` | record ids, nullable | Supersession chain links |
| `supersededAt` | ISO 8601, nullable | When supersession invalidated this record |
| `supersededReason` | string, nullable | Explicit reason required at supersession (docs/SUPERSESSION.md) |
| `idempotencyKey` | string ≤ 128, nullable, UNIQUE | Replay-safe writes (docs/PERSISTENCE.md) |
| `contradictionGroupId` | `ctg_…`, nullable | Contradiction group membership |

## MemoryCandidate (`cand_`)

Pre-promotion knowledge with the same core shape (kind, subject, content,
provenance, epistemic class, confidence, evidence refs, tags) plus
`status: open | promoted | rejected` and `promotedRecordId`. Promotion creates
a NEW record identity and stamps the candidate `promoted`.

## Storage layout (canonical, migrations 1–5)

- `memory_records` — current record state (one row per record id), incl.
  `observed_at` / `superseded_at` (migration 4) and `idempotency_key`
  (migration 5, UNIQUE).
- `memory_record_revisions` — append-only `(record_id, revision)` history —
  the truth of record content; record rows are repairable projections.
- `memory_candidates` — candidates + `reason`, `caller_json`,
  `idempotency_key` (migration 5).
- `memory_scopes`, `contradiction_groups` — identity ownership (migration 2);
  scopes carry `intake_policy_json` (migration 5), `mutation_policy_json`
  (migration 11), and `privacy_policy_json` (migration 12); groups carry
  `status`/`resolution_json` and records `supersede_reason` (migration 6);
  records carry `archived_at`/`deleted_at`/`deleted_by`/`delete_reason` and
  scopes deletion metadata (migration 7).
- `memory_fts` — FTS5 **derived** full-text index over records (migration 8):
  rebuildable, never canonical truth (docs/RETRIEVAL.md).
- `memory_embeddings`, `memory_embedding_projections` — **derived** semantic
  embedding projection (migration 9): per-record vectors + per-scope build
  metadata (provider/model/version), privacy-gated, fully rebuildable, never
  canonical truth (docs/EMBEDDINGS.md).
- `memory_search_sessions` — append-only search intent/session history as
  retrieval context (migration 10): scoped, by-reference results/candidates,
  never promoted to durable knowledge (docs/SEARCH_HISTORY.md).
- `engine_events`, `schema_migrations` — observability + bookkeeping (migration 1).
- Migration 4 backfills: `observed_at = created_at`, `superseded_at =
  revised_at` for superseded rows, `provenance.sourceKind = "unknown"`.

Derived artifacts (embeddings, vector stores, graphs, caches, context packs,
projections) are rebuildable and never canonical truth; where a derived
artifact does live in this store (`memory_fts`, `memory_embeddings`,
`memory_embedding_projections`) it is a discardable, rebuildable table, never a
source of truth. See docs/BOUNDARY.md.

## Lifecycle semantics

- **create** — status `active`, revision 1; event `memory.record.created`.
- **revise** — active only; new immutable revision row + event
  `memory.record.revised`; `createdAt` never changes.
- **supersede** — active only; new record with `supersedesId`, old record
  flips to `superseded` with `supersededById`; events
  `memory.record.created` + `memory.record.superseded`.
- **retract** — active/superseded only; requires reason; status `retracted`,
  revision advances with `retracted: <reason>`; event
  `memory.record.retracted`.
- **expire** — explicit sweep (`expireStaleRecords`): active records past
  `validUntil` become `expired`; event `memory.records.expired`.
- **contradiction** — `registerContradiction` requires ≥ 2 existing records in
  the same scope; links both to a `ctg_` group; event
  `memory.contradiction.registered`.

Events carry references and metadata only — never content bodies.

## Verification map

`test/t3_schema.test.ts` covers: full-field round-trip, normalization+hash,
by-reference enforcement (payload-smuggling rejected), secret refusal with
persistence check, 11-case validation matrix, revision immutability,
supersession chain + non-active conflicts, retraction, expiry sweep, search
filters (scope/kind/status/subject/content/tag/limit/LIKE-escaping), candidate
promotion, restart hash stability, not-found negatives.
