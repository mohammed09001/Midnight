# Library Memory Engine — Revision & Correction Semantics (v1.3.0)

Implemented in `src/engine/records.ts` (`reviseRecordImpl`) with the
immutable revision log owned by the append-oriented store (docs/PERSISTENCE.md).
Attributed-history model adapted from dolthub/dolt's commit/log/blame
concepts (main @ 2026-08-30).

## Corrections are revisions

`engine.reviseRecord(recordId, {content, actor, method, reason, …})`:

- `reason` is **REQUIRED** — corrections are attributed, never silent.
- Allowed correctors: `human` users and `engine` actors (authorized
  engines are first-class correctors). `agent` actors are refused with
  `MEMORY_CORRECTION_FORBIDDEN` — agent corrections flow through the
  candidate intake pipeline (docs/INTAKE.md) and policy-gated promotion
  (docs/PROMOTION.md).
- Each correction appends a NEW immutable row to
  `memory_record_revisions` (content, hash, provenance, reason, time) and
  advances the record's revision counter. `createdAt` never changes.

## Provenance immutability

**Historical provenance is never silently mutated:**

- Revision rows are append-only; the store exposes no update/delete path
  for them (verified by the append-integrity check,
  `engine.checkAppendIntegrity()`).
- Every revision keeps the actor, method, and source kind IN EFFECT AT
  THAT REVISION — later corrections cannot rewrite who claimed what.
- The revising actor is recorded on the new revision row and in the
  `memory.record.revised {recordId, revision, actor, reason}` event.
- Source kind / derivedFrom persist across corrections unless explicitly
  overridden by a non-agent actor.

## Relation to supersession

Corrections that keep the same record identity are **revisions** (this
document). Corrections that create a new identity while retiring the old
one are **supersession** (docs/SUPERSESSION.md) with its own explicit
reason. Retraction of a wrong claim is a reasoned, revision-advancing
state change — also never a deletion.
