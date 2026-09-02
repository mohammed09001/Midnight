# Midnight Memory — Cross-Engine Lineage Walkthrough (v1.27.0)

Task 19, Midnight Memory Execution 07. Proven end to end in
`Performance/tests/test_memory_bridge.py`'s `CrossEngineLineageTests`.

## Principle

Performance's development-history evidence and Memory's durable knowledge
stay two separate ledgers (docs/BOUNDARY.md Section 0) — this document does
not merge them. It walks ONE identity through every hop of the learning
loop, using only stable references, timestamps, and versions already
produced by the existing contract (docs/PERFORMANCE.md) and citation
mechanism (Task 15), so a reviewer can follow the whole chain without
querying either engine's private store or relying on prose-only
correlation.

## The chain

| Hop | Artifact | Stable reference |
|---|---|---|
| 1. Performance evidence | a sealed `ObservationEnvelope` | its canonical `Identity` (`mp:v<n>:<kind>:<uuid>`, `Performance/midnight_performance/contracts.py`) |
| 2. Performance lesson proposal | `lesson_from_sealed_envelope` / `lesson_from_qualified_claim` (`memory_bridge.py`) | `evidenceRefs` = the Hop-1 identity; `idempotencyKey` defaults to it too |
| 3. Memory candidate | `memory.performance.propose` (docs/PERFORMANCE.md) | `MemoryCandidate.candidateId` |
| 4. Promoted / superseded / contradicted Memory record | `memory.promote`, `contradiction register` + `contradiction resolve` (docs/PROMOTION.md, docs/CONTRADICTIONS.md, docs/SUPERSESSION.md) | `MemoryRecord.recordId` + `revision`; a resolved group's `groupId` |
| 5. Later Memory retrieval | `read_performance_context` → `memory.context` (Task 13 fields) | `contradiction{groupId,status,groupSize}`, `evidenceGaps`, `trace` on the returned `ContextRecord` |
| 6. Later Performance analysis | `citation_from_memory_record` → `ExternalReference` (Task 15) → `Reprocessor.run(..., memory_references=...)` / `relationship_graph.build_graph(..., memory_references=...)` | `ExternalReference.value` = `<recordId>#rev<revision>`; graph node `EntityKind.MEMORY_RECORD` keyed on `provider:kind:value` |

Every hop's reference is produced by code that already exists; this
document does not introduce a new identifier scheme.

## Contradiction and supersession survive the chain

The chain is proven not just for a clean propose→promote path but through a
real contradiction: a second, conflicting record is registered against the
same subject (`contradiction register`) and resolved in the
Performance-originated record's favor (`contradiction resolve --action
supersede`). The winning record stays `active`; `read_performance_context`
reports the group as `status: "resolved"` on it — the lineage survives
contradiction handling, not just the uncontested case.

## Citations are pinned; staleness is discovered, not pushed

A citation built by `citation_from_memory_record` names one exact revision
(`#rev<N>`) and is immutable by construction — Memory's revision rows are
append-only, so `memory.history` can always reproduce exactly what was
cited, even after the record is later revised, superseded, or its
contradiction group resolved differently.

This means a `PerformanceGraph` already built from a citation does **not**
auto-update when Memory later changes that record: the graph is a
rebuildable projection over point-in-time citations
(`relationship_graph.py`'s own docstrings), never a live pointer. Staleness
is not a gap in this design — it is the intended discovery mechanism:
a caller who wants current status re-calls `read_performance_context`,
which reports the record's live `contradiction`/status fields, and builds a
fresh citation/graph from that. A later Memory change never silently
rewrites what an already-issued citation points at (Task 15); it also never
pushes a notification into a graph built earlier.

## Non-goals

- Does **not** add a new identifier scheme, store, or transport — every
  reference above already exists.
- Does **not** make Memory aware of Performance's prompt/agent/episode
  ledger, or vice versa (docs/BOUNDARY.md Section 0 stands unchanged).
- Does **not** claim a `PerformanceGraph` is live/subscribed — see above.
