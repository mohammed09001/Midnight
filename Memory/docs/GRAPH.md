# Library Memory Engine — Optional Relationship-Graph Projection (v1.9.0)

Implemented in `src/engine/graph.ts`. Task 24, Phase IV.

## Principle

Projects Memory relationships into a GRAPH for traversal/history experiments
WITHOUT making a graph database canonical. The graph is a DERIVED, REBUILDABLE
projection computed on demand from canonical records (docs/BOUNDARY.md) — there
is no canonical graph store, and the graph never becomes a source of truth.

## What the graph contains

Nodes:

| Kind | id | label |
|---|---|---|
| `record` | record id (`mem_…`) | record subject |
| `entity` | `entity:<kind>:<name>` (Task 22) | entity name |
| `external` | `engine:<name>:<ref>` (by reference only) | the ref |

Edges:

| type | source | meaning |
|---|---|---|
| any typed relation | record → target | from `relationHints`, with provenance |
| `supersedes` | record → predecessor | canonical supersession chain |
| `superseded_by` | record → successor | canonical supersession chain |
| `contradicts` | record ↔ record | contradiction-group membership |

## API

- `engine.graphProjection(scope)` / `memory.graph {scope}` → `{projection}` —
  the versioned graph (`version`, `schemaVersion`, `builtAt`, `nodeCount`,
  `edgeCount`, `nodes`, `edges`).
- `engine.rebuildGraphProjection(scope)` / `memory.graph {action:'rebuild'}` —
  recompute and emit `memory.graph.projection.rebuilt`.
- `engine.traverseGraph(scope, start, {direction?, relationTypes?, maxDepth?})`
  / `memory.graph {action:'traverse'}` — bounded BFS from a node id:
  `direction` `out|in|both` (default `both`), `relationTypes` filter (e.g.
  `["supersedes","superseded_by"]` for supersession-history experiments),
  `maxDepth` 1–20 (default 3). Returns reachable nodes with depths, the edges
  traversed, and `truncated` when the depth cap cut off nodes.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Unknown start node | `MEMORY_NOT_FOUND` |
| Empty start | `MEMORY_VALIDATION_FAILED` |
| Unknown scope | `MEMORY_NOT_FOUND` |
| Bad `action` | `MEMORY_VALIDATION_FAILED` |

## Agent neutrality / game independence

The graph is a pure deterministic function of canonical records — no LLM, no
external graph database, no game dependency. Terminal surface:
`graph --scope K [--rebuild]`, `graph traverse --scope K --start NODE
[--direction out|in|both] [--types a,b] [--max-depth N]`.