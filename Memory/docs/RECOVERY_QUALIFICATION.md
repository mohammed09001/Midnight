# Library Memory Engine — Crash/Rebuild/Deletion Qualification (v1.24.0)

Implemented in `src/engine/recovery.ts`. Task 45, Phase VIII.

## Principle

An ACTIVE qualification harness: it creates disposable scratch stores,
injects real damage (torn files, torn projections, corrupted indexes and
vectors), performs destructive lifecycle operations, and proves the engine's
DETECTION and RECOVERY behavior end to end. The caller's store is never
touched; scratch stores are removed afterwards. Every check has a stable
name and a deterministic, count-based detail.

## Frozen scenarios

| Check | Scenario |
|---|---|
| `torn-store-doctor` | a corrupted store file is reported unhealthy by `doctor` — never throws, typed error, no fabricated data |
| `append-integrity-repair` | a record projection torn from the immutable revision log is detected by `checkAppendIntegrity` and repaired FROM THE LOG |
| `lexical-corruption-repair` | FTS entries deleted underneath a record are detected (`corrupted`) and rebuilt from canonical records; retrieval is restored |
| `vector-corruption-rebuild` | a corrupt derived vector is skipped and reported (`skippedCorrupt`), then restored by an embedding rebuild — which also removes orphan rows |
| `backup-restore-snapshot` | a checksummed backup taken BEFORE destructive mutations restores faithfully into a fresh store: tombstones stay tombstones, purged records stay gone, references stay consistent, and the lexical index recovers via triggers (derived state is never part of a snapshot) |
| `source-deletion-propagation` | tombstoning scrubs content, removes the derived vector, drops the record from default lexical AND semantic retrieval, and records the lifecycle event |
| `privacy-purge-propagation` | purging a privacy class removes the record row, revision log, derived vector, and lexical entry in one step; the stale projection metadata is DETECTED and the rebuild restores health with no orphans |
| `scope-deletion-tombstone` | tombstoning a scope retires its records from the default view and leaves foreign references consistent |

## Deletion propagation contract (Task 45 hardening)

Canonical deletion now propagates to the derived embedding store: a
tombstone (Task 13) removes the record's vector rows, a privacy purge
removes them inside the purge transaction, `semanticSearch` never ranks
deleted records, and an embedding rebuild removes orphan rows whose records
no longer exist — so a purge can never leave permanent "corruption" behind.
The lexical index is trigger-maintained (delete/reindex).

## Failure / degradation

| Condition | Behavior |
|---|---|
| Any recovery path fails | the specific named check FAILS (`passed: false`, exit 1 on the CLI) |
| Corrupt store file | `MEMORY_STORE_UNAVAILABLE` via doctor — never a silent fallback |
| Stale projection after deletion | reported `corrupted`; the rebuild is the documented recovery |

## Agent neutrality / game independence

Deterministic scenarios on scratch stores — no LLM, no provider beyond the
built-in deterministic embedding adapter, no game. Terminal surface:
`qualify recovery [--path <report.json>]` (exit 1 when any scenario fails;
`--path` writes the report as evidence).
