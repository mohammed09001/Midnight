# Library Memory Engine — Health & Retrieval Quality (v1.20.0)

Implemented in `src/engine/health.ts`. Task 40, Phase VII.

## Principle

A single operational report measuring intake/promotion/rejection, stale and
contradicted records, missing evidence, index freshness, rebuild health, and a
sampled retrieval latency — for terminal/tool surfaces.

## Metrics

`engine.memoryHealth()` / `memory.health`:

| Group | Measures |
|---|---|
| `store` | healthy, migrations, event count |
| `intake` | open / promoted / rejected candidates |
| `staleRecords` | active records past their validity window (not yet swept) |
| `contradictedRecords` | records in open contradiction groups |
| `missingEvidence` | non-deleted records with zero evidence references |
| `index` | lexical (FTS) status + embedding projection status (freshness) |
| `rebuild` | the unified projection-integrity report (docs/PROJECTIONS.md) |
| `retrieval` | a bounded sample lexical query: hits + latency (ms) |

## Failure / degradation

The report never throws for degraded state: a corrupt index is reported
(`index.lexical.status: "corrupted"`, `rebuild.healthy: false`), not masked.
`store.healthy` reflects `doctor` integrity.

## Agent neutrality / game independence

Deterministic, local, provider-free, no game dependency. Terminal surface:
`health`.