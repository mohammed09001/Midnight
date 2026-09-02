# Midnight Memory — Context → Memory Retrieval (v1.17.0)

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

**v1.17.0 additive** (Task 13, Execution 05 — Performance-oriented retrieval):
- `contradiction: {groupId, status, groupSize}` — contradiction-group
  membership/status, reused verbatim from `memory.explain`
  (`getContradictionGroupOrNull`, docs/CONTRADICTIONS.md); `null` fields when
  the record has no contradiction group.
- `evidenceGaps: string[]` — deterministic evidence-completeness/freshness
  findings, reused verbatim from `memory.explain`'s `evidenceGapsOf`
  (`src/engine/relations.ts`, now exported).
- `trace: SearchMatchReason[]` — one `{filter, reason}` entry per applied
  context filter the record actually satisfied, mirroring `memory.search`'s
  `SearchTrace`/`memory.current`'s `CurrentTrace` pattern exactly (same
  `SearchMatchReason` type, reused, not reinvented).

Deterministic context ordering: currently valid first, then authority tier,
then recency.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Unknown scope | `MEMORY_NOT_FOUND` |
| Invalid `at` / `time` | `MEMORY_VALIDATION_FAILED` |
| `minConfidence` outside [0,1] | `MEMORY_VALIDATION_FAILED` |
| `size` out of range | clamped to 1..100 |

## Cross-language transport

`memory.context` is also the read direction of the Performance-Memory
bridge (docs/PERFORMANCE.md): `Performance/midnight_performance/memory_bridge.py`'s
`build_context_envelope`/`call_memory_cli` reuse this same bounded, scoped,
provenance-rich operation for Performance to read prior Memory knowledge —
no Performance-specific read operation was added.

**Citation by reference (Task 15, Execution 05):** when a Performance
analysis consults a record read through `memory.context`, it cites the
specific `recordId#rev<N>` — never a copy of the content — via Performance's
own `ExternalReference` type (`citation_from_memory_record`,
`memory_bridge.py`). Because Memory's revision rows are immutable and
append-only, `memory.history` can always reproduce that exact cited content
later, even after the record is revised or superseded — a later Memory
change never silently rewrites what a historical Performance citation
points at.

## Agent neutrality / game independence

Deterministic SQL + structural authority — no LLM, no provider, no game
dependency. Terminal surface: `context query --scope K [--size N] [--at <iso>]
[--time-from <iso>] [--time-until <iso>] [--min-authority tier]
[--min-confidence 0.8] [--source-kind …] [--kind …]`.