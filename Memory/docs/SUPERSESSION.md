# Midnight Memory — Supersession Without Destructive Overwrite (v1.3.0)

Implemented in `src/engine/records.ts` (`supersedeRecordImpl`), exposed via
history in `src/engine/temporal.ts`. Inspiration: dolt's attributed history
and time-travel semantics (main @ 2026-08-30); graphiti's invalidate-never-
delete windows (main @ 2026-08-30).

## Semantics

`engine.supersedeRecord(recordId, {content, actor, method, reason, …})`:

- **Explicit reason REQUIRED** (`MEMORY_VALIDATION_FAILED` otherwise) —
  recorded in four places: the predecessor's `supersedeReason` column, the
  successor's initial revision row (`"supersedes <id>: <reason>"`), the
  `memory.record.superseded` event, and the history chain entries.
- The predecessor is **never deleted or content-mutated**: only its status
  (`superseded`), lineage pointers (`supersededById`), `supersededAt`, and
  `supersedeReason` change.
- The successor is a NEW record identity with inherited provenance
  (source kind, evidence refs, tags, relations, contradiction membership)
  and its own immutable revision log.
- **Attribution**: `actor.kind === "agent"` → `MEMORY_CORRECTION_FORBIDDEN`
  (agents propose supersessions through the candidate intake instead).
- Only `active` records can be superseded; chains form acyclically.

## Retained guarantees (verified per test)

- **Lineage**: `getRecordHistory` returns the complete chain (oldest →
  newest) reachable from any member; `supersedesId`/`supersededById` link
  every hop.
- **Provenance**: predecessor's actor/method/sourceKind/content-hash are
  untouched by supersession.
- **Historical queryability**: `queryRecordsAsOf` reconstructs belief before
  the invalidation instant; at exactly `supersededAt` the successor holds.
