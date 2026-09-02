# Library Memory Engine — Context → Memory Retrieval (v1.15.0)

Implemented in `src/engine/context.ts`. Task 31, Phase V.

## Principle

A BOUNDED, context-oriented query surface for the Context Engine to assemble
provenance-rich context packs from Memory. Supports EXPLICIT SIZE / TIME /
PROJECT filters and returns PROVENANCE-RICH results. Memory never assembles
context packs itself (docs/BOUNDARY.md) — it returns bounded,
provenance-attributable records for the Context Engine to assemble.

## Query

```ts
interface ContextQuery {
  scope: string;                  // project (required — context is per-project)
  query?: string;                 // optional free-text topic refinement
  size?: number;                  // hard cap 1–100 (default 20)
  at?: string;                    // validity instant (default now)
  time?: { from?: string; until?: string };  // observed-time window
  kinds?: RecordKind[];
  sourceKinds?: SourceKind[];
  minAuthority?: AuthorityTier;   // structural authority floor
  minConfidence?: number;
  includeRetracted?: boolean;
}
```

## Filters

- **Project**: `scope` (required).
- **Size**: `size` caps returned records; `totalMatches`/`truncated` report
  how many matched and whether more matched than returned.
- **Time**: `at` (validity-window containment — future/expired windows are
  reported via `currentlyValid`) plus `time.from`/`time.until` (observed-time
  window).
- **Provenance**: `kinds`, `sourceKinds`, `minConfidence`,
  `minAuthority` (structural authority tier, docs/AUTHORITY.md),
  `includeRetracted`.

## Provenance-rich results

Every returned record is wrapped with:
`authority` (structural, never content-fluency based), `sourceKind`,
`validity {at, currentlyValid}`, `evidenceCount`, `confidence`.

Deterministic context ordering: currently valid first, then authority tier,
then recency.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Unknown scope | `MEMORY_NOT_FOUND` |
| Invalid `at` / `time` | `MEMORY_VALIDATION_FAILED` |
| `minConfidence` outside [0,1] | `MEMORY_VALIDATION_FAILED` |
| `size` out of range | clamped to 1..100 |

## Agent neutrality / game independence

Deterministic SQL + structural authority — no LLM, no provider, no game
dependency. Terminal surface: `context query --scope K [--size N] [--at <iso>]
[--time-from <iso>] [--time-until <iso>] [--min-authority tier]
[--min-confidence 0.8] [--source-kind …] [--kind …]`.