# Midnight Memory — Entity Linking as a Derived Projection (v1.7.0)

Implemented in `src/engine/entities.ts`. Task 22, Phase IV.

## Principle

Stable project entities (components, repositories, technologies, decisions)
are EXPRESSED as attributed `applies_to` relations targeting
`entity:<kind>:<name>` on canonical records (Task 21). The **entity index is a
DERIVED, REBUILDABLE projection** computed FROM those canonical records — it is
NEVER canonical truth (docs/BOUNDARY.md: "derived indexes, vector stores,
graphs, caches and projections are rebuildable and never silently become
canonical truth"). There is no canonical entity table.

## Entity references

Target format `entity:<kind>:<name>` with a bounded taxonomy:

| Kind | Example |
|---|---|
| `component` | `entity:component:api-gateway` |
| `repository` | `entity:repository:memory-engine` |
| `technology` | `entity:technology:sqlite` |
| `decision` | `entity:decision:release-cadence` |
| `other` | any `entity:` target whose kind is not in the taxonomy |

## What the projection extracts

`engine.entityProjection(scope)` / `memory.entities` scans every non-deleted
record in the scope and:

1. **Explicit extraction** — every `applies_to` relation targeting an
   `entity:` reference links that record to the entity.
2. **Subject auto-linking** — a record whose `subject` exactly equals an
   entity's canonical name is also linked (deterministic corpus extraction,
   no LLM/embedding).
3. For each entity it groups the linked records with the link kind
   (`applies_to` explicit, `subject` auto, or `both`), and reports
   `explicitCount`/`autoCount` and `firstSeenAt`/`lastSeenAt`.

The projection carries `schemaVersion`, `version` (contract version + build
counter + build time) and `builtAt` so callers can detect when it was built.

## Rebuildable and versioned

The projection is computed on demand — always current by construction.
`engine.rebuildEntityProjection(scope)` / `memory.entities {rebuild: true}`
forces a fresh build and emits `memory.entities.projection.rebuilt`
(observability/recovery path, mirroring the FTS index rebuild).

## Failure behavior

Unknown scopes are `MEMORY_NOT_FOUND`. Entity extraction itself is
deterministic and cannot fail on malformed references (malformed/empty
`entity:` targets are ignored; unknown kinds classify as `other`).

## Agent neutrality / game independence

Extraction is a pure deterministic function of canonical records — no LLM,
no embedding provider, no game dependency. Terminal surface:
`entities --scope K [--rebuild]`.