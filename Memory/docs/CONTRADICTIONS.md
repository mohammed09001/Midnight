# Midnight Memory — Contradiction Detection & Resolution (v1.3.0)

Implemented in `src/engine/contradictions.ts`; migration 6 adds group
status/resolution. Research: deterministic detection + preserved history
adapted from getzep/graphiti (main @ 2026-08-30); LLM-judged auto-resolution
REJECTED; conflict-pending-resolution model adapted from dolthub/dolt
(main @ 2026-08-30); Dolt itself rejected as over-accumulation.

## Detection (deterministic, no LLM)

`engine.detectContradictions(scope)` → `ContradictionPair[]`. A pair is two
ACTIVE records in the same scope with:

- the **same normalized subject**, and
- **different content** (distinct content hash), and
- **overlapping validity windows** (`validFrom`/`validUntil`/`observedAt`;
  open bounds extend indefinitely), and
- no supersession link between them (lineage ≠ contradiction), and
- no existing shared contradiction group (already pending resolution).

Detection is a pure read — it never writes.

## Grouping (preserve both, await resolution)

`engine.registerContradiction(scope, subject, recordIds)` links both claims
into an open `ctg_` group. Both records remain fully intact and queryable —
grouped pairs are excluded from re-detection and surface via
`listOpenContradictions(scope)` and `memory.related`.

Groups carry `status: "open" | "resolved"` and, once resolved, an attributed
`ContradictionResolution`.

## Resolution (attributed; agents refused)

`engine.resolveContradiction(groupId, {action, winnerRecordId, actor, reason})`:

- `action: "supersede"` — losers are superseded BY the winner (lineage
  retained; `supersededReason` = the resolution reason);
- `action: "retract"` — losers retracted with a reasoned revision row;
- the winner must be active and belong to the group;
- `actor.kind === "agent"` → `MEMORY_PROMOTION_FORBIDDEN` — resolution is a
  user or policy decision, never an agent's;
- double resolution → `MEMORY_CONFLICT`;
- emits `memory.contradiction.resolved {groupId, action, winner, losers, actor, reason}`.
