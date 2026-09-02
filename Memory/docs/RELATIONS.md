# Midnight Memory — Typed Memory Relationships (v1.7.0)

Implemented in `src/engine/relations.ts` (+ `contracts/types.ts` relation
vocabulary, `validation.ts`). Task 21, Phase IV.

## The bounded relation vocabulary

| RelationType | Meaning |
|---|---|
| `related` | topic-level association (related-to) |
| `depends_on` | the source record depends on the target |
| `supports` | the source record supports/corroborates the target |
| `contradicts` | the source record contradicts the target (see also contradiction groups) |
| `derived_from` | the source record's content derives from the target |
| `applies_to` | the source record applies to the target (records→entities, Task 22) |
| `learned_from` | the source record was learned from the target (e.g. a study/lesson) |

`supersedes` is NOT a hint type: supersession is a first-class lifecycle link
(`supersedes_id` / `superseded_by_id`, docs/SUPERSESSION.md) surfaced through
the relations view as `supersedes` / `supersededBy` — it is never duplicated
as a hint.

## Provenance on every relation

Every `RelationHint` may carry `provenance {actor, method, capturedAt}` —
who established the relation, how, and when. Relations added via
`addRelation` / `memory.relation` ALWAYS carry provenance (actor and method
are required); relations declared inline at record creation may carry it.

## Targets

A relation target is one of:

- a `MemoryRecord` id (`mem_…`) — must exist in the same scope and not be
  tombstoned; self-relations are refused;
- `engine:<name>:<ref>` — a cross-engine reference, by value only;
- `entity:<kind>:<name>` — a stable project-entity link (Task 22).

## Management surface

- `engine.addRelation(recordId, {type, target, note?, actor, method})` —
  attributed, validated, duplicate `(type, target)` pairs are refused
  (`MEMORY_CONFLICT`), exceeds the 32-hint bound (`MEMORY_VALIDATION_FAILED`).
- `engine.removeRelation(recordId, {type, target})` — removes the matching
  hint; a missing relation is `MEMORY_NOT_FOUND`.
- `memory.related` returns `{outgoing, incoming, supersedes, supersededBy,
  contradictionGroup}`.
- Events: `memory.relation.added`, `memory.relation.removed`.

## Failure behavior

All failures are typed: cross-scope/self/tombstone/malformed targets
(`MEMORY_VALIDATION_FAILED`), duplicates (`MEMORY_CONFLICT`), missing
relations (`MEMORY_NOT_FOUND`), missing source records (`MEMORY_NOT_FOUND`).
The dispatcher never throws across the boundary.

## Agent neutrality / game independence

Relations are attributed to generic actors; no agent product is
special-cased. Fully usable from the terminal (`relation add/remove`), no
game dependency.