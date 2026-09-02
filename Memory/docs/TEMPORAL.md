# Library Memory Engine — Temporal Validity & Historical Truth (v1.1.0)

Implemented in `src/engine/temporal.ts`; migration 4 (`temporal_authority`)
adds the columns and backfills. Pattern adapted from getzep/graphiti's
temporal knowledge graph design (main branch, accessed 2026-08-30):
**invalidate, never delete** — with the graph store itself rejected as an
out-of-boundary derived artifact.

## Bi-temporal model

| Time | Field(s) | Meaning |
|---|---|---|
| **Valid time** | `observedAt` | When the claim held in the source reality (defaults to record time). Bounded by `validFrom` / `validUntil`. |
| **Transaction time** | `createdAt`, `revisedAt` | When this store learned / changed the claim. Immutable creation; monotonic revisions. |
| **Invalidation** | `supersededAt` | When a successor superseded the record. |

Changed decisions do NOT overwrite the past: supersession creates a new
record and stamps the predecessor; revisions append immutable rows;
retraction stamps a revision with its reason; expiry is an explicit sweep.

## Historical queries

- `getRecordHistory(recordId)` → the complete supersession chain (oldest →
  newest, reachable from ANY chain member) plus all immutable revision rows.
- `queryRecordsAsOf({ asOf, scope?, includeRetracted?, limit? })` → what was
  believed at instant T:
  - learned no later than T (`created_at ≤ T`) — belief cannot precede the store;
  - validity window contains T (`validFrom ≤ T < validUntil`, nulls open);
  - not superseded before T (`supersededAt > T`; at exactly `supersededAt`
    the successor already holds);
  - retracted records are believed **until** their retraction instant
    (stamped in `revised_at`); `includeRetracted: false` hard-excludes them.
- Current view: `searchRecords({ status: "active" })` — agrees with
  `queryRecordsAsOf(now)` modulo the explicit expiry sweep.

## Boundary semantics (documented ties)

At the exact instant of supersession, the predecessor stops being true and
the successor starts — `superseded_at > T` is strict. Queries reconstructing
"just before" should use `supersededAt − 1ms`.

## CLI

```
memory-engine record history --id mem_…
memory-engine record search --as-of 2026-08-30T00:00:00.000Z [--scope K]
memory-engine contract call --operation memory.search --request '{"scope":"K","asOf":"…"}'
```
