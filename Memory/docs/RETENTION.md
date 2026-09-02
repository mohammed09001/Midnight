# Library Memory Engine — Retention, Archival & Deletion (v1.4.0)

Implemented in `src/engine/retention.ts` (+ `scopes.ts` project deletion),
migration 7. No external reference was listed for this task; the semantics
are Library-owned policy definitions honoring the Engine Isolation
Invariants (append-oriented, nothing silently destroyed).

## Lifecycle states

```
active ──archive──> archived ──restore──> active
   │  ├── supersede ──> superseded (lineage retained)
   │  ├── retract ────> retracted  (reasoned revision)
   │  ├── validUntil ─> expired    (explicit sweep)
   └── delete ────────> deleted (TOMBSTONE: payload scrubbed, row + lineage retained)
                purge ─────────────> (the ONLY hard delete; privacy-driven)
```

- **archived** — cold storage: excluded from current/active views, content
  fully retained and queryable, restorable. Belief views (`queryRecordsAsOf`)
  include archived records only until `archivedAt` (archiving applies
  forward, never rewrites the past).
- **deleted (tombstone)** — content, evidence refs, relation hints, tags,
  and validity windows are scrubbed; the row, its id, lineage pointers, and
  deletion metadata (`deletedAt/deletedBy/deleteReason`) remain so chains
  and events stay coherent. Tombstones leave the default search view and
  ALL as-of belief views (their content is no longer reconstructable — the
  documented cost of deletion).
- **purged** — the only hard delete: removes the record row, its entire
  revision log, and every inbound pointer (lineage links, candidate
  promotion pointers, relation hints in other records, contradiction group
  membership). Used for privacy-driven erasure.

All lifecycle transitions are **attributed and reasoned** (blank reason →
`MEMORY_VALIDATION_FAILED`); **agents are refused** every lifecycle
decision (`MEMORY_CORRECTION_FORBIDDEN`) — they act through the candidate
intake instead. Every transition emits an event
(`memory.record.archived/restored/deleted/purged`, `memory.scope.deleted`).

## Project deletion propagation

`engine.deleteScope(projectKey, {actor, reason, mode: "tombstone"|"purge"})`:

- tombstones (or purges) **every record** in the scope;
- closes open contradiction groups as informational closures;
- drops pending candidates (intake for a dead project is meaningless);
- marks the scope row `deletedAt/deletedBy/deleteReason` — the row and its
  deterministic identity are **retired, never reused**;
- all write paths on a deleted scope are refused (`MEMORY_CONFLICT`).

## Privacy-driven deletion

- `purgeRecord` — targeted hard erasure (e.g. subject erasure request).
- `purgeByPrivacy({privacyClasses, scope?})` — bulk erasure by privacy
  class (e.g. all `sensitive` records), optionally scoped.
- The purge event carries identity and reason **only** — content never
  enters the event stream.

## When source evidence expires

Evidence refs may carry `expiresAt`. When a source expires in its owning
engine, the memory record **survives** (memory is durable and never silently
invalidated) but its verifiability degrades visibly:

- `engine.listEvidenceExpired(scope, at)` — records whose evidence has
  fully lapsed;
- `engine.sweepExpiredEvidence(scope, at)` — emits
  `memory.evidence.expired {recordIds}` for observability;
- follow-up (retract, archive, re-verify) is then a policy/user decision.
