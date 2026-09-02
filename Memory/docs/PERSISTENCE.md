# Library Memory Engine — Append-Oriented Persistence (v1.2.0)

Implemented in `src/engine/store.ts` (+ migration 5), `src/engine/records.ts`.
Pattern note: mem0's ADD-only accumulation ("memories accumulate; nothing is
overwritten", main @ 2026-08-30) adapted WITHOUT its LLM/embedding provider
dependency — Library's accumulation is supersession + immutable revisions on
a self-hosted SQLite store (Apache-2.0 upstream, concepts only).

## Model

- **Truth** = the append-only `memory_record_revisions` log (immutable rows,
  `(record_id, revision)` 1..N) plus the append-only candidate/event streams.
- **Projection** = the `memory_records` row (current content/hash/revision),
  repairable from the log at any time.
- Nothing is overwritten: revise/retract append; supersession creates a new
  record and stamps the predecessor; deletions do not exist.

## Idempotent writes (Task 7)

Callers may pass `idempotencyKey` (≤ 128 chars) to `addRecord` /
`addCandidate` / `memory.propose`:

- same key ⇒ the ORIGINAL record/candidate is returned; no duplicate row;
- replay is safe across process restarts (key column + UNIQUE index);
- concurrent same-key writers race on the unique index; the loser returns
  the winner's row;
- keys are caller-namespaced by convention (e.g. `sync:job-7`,
  `analyzer:run-42:lesson-1`);
- omitted key ⇒ unique ULID identity (non-idempotent, unchanged behavior).

Deterministic identities "where applicable": scope ids remain hash-derived
from projectKey; identities otherwise ULID.

## Transactions & recovery

- All multi-row writes run in `BEGIN IMMEDIATE` transactions with rollback
  on failure (verified: failed supersession leaves zero partial state).
- WAL journal mode + `busy_timeout`; store open/migration failures are typed
  (`MEMORY_STORE_UNAVAILABLE`, `MEMORY_MIGRATION_FAILED`) — no silent fallback.
- Migrations are versioned, ordered, transactional, and idempotent
  (`schema_migrations`); reopening a store re-applies nothing (verified
  across restarts and across the 1.1 → 1.2 upgrade).

## Append-integrity observability (new in 1.2.0)

- `engine.checkAppendIntegrity()` — verifies every record has an unbroken
  revision chain 1..revision and that its projected content hash equals the
  newest revision row's hash.
- `engine.repairRecordProjection(recordId)` — rebuilds the record row's
  content/hash/revision FROM the newest revision row (the log is truth);
  refuses to fabricate state when log rows are missing; emits
  `memory.record.repaired`.

Derived indexes/projections remain rebuildable by design: none live in the
canonical store, and the repair path demonstrates the projection-rebuild
discipline.
