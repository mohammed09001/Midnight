# Midnight Memory + Performance — Compatibility Gate (v1.27.0)

Task 23, Midnight Memory Execution 08. Implemented in
`Performance/midnight_performance/compatibility_gate.py`.

## Principle

Before this Task, proving Memory+Performance compatibility meant separately
running `npm test`/`gate run` in Memory and `pytest tests/` in Performance
and eyeballing both exit codes — no single command failed non-zero on a
material breach. This gate is a thin composition layer, not a new
qualification authority: every clause shells out to or calls a real,
already-existing capability. It invents no new store, transport, check
logic, or authority — it only aggregates fresh evidence that already exists
elsewhere into one pass/fail report with named failing clauses.

## The six clauses

| Clause | Fresh evidence, reused from |
|---|---|
| `memory_product_truth` | Memory's own `gate run` (Task 46, `src/engine/gate.ts`) — all 8 Memory-internal clauses, run verbatim and flattened in |
| `performance_to_memory_propose` | a real `memory.performance.propose` round trip on a scratch store (`memory_bridge.py`) |
| `memory_to_performance_read` | a real `memory.context` round trip via `read_performance_context`, asserting the Task 13 fields (`contradiction`/`evidenceGaps`/`trace`) are present |
| `standalone_degraded_operation` | `propose_lesson_or_degrade` against an unreachable Memory — truthful degrade, never an exception |
| `no_local_duplicate_authority` | the existing, previously-orphaned `qualify_memory_integration()` (`evaluation_memory_qualification.py`) |
| `cross_language_test_suites` | a real `pytest` run of `test_memory_bridge.py`, `test_memory_bridge_recovery.py`, and `test_evaluation_memory_qualification.py` — the files that actually prove the bridge |

Each check carries `{name, passed, detail}`; a clause passes only when every
one of its checks passes. The report mirrors `gate.ts`'s
`ProductTruthGateReport`/`GateClause` shape so the two reports read the
same way, even though this one composes across languages.

## Scratch-store discipline

`run_compatibility_gate` creates a fresh, disposable scratch store per run
(mirrors `gate.ts`'s own principle: "the caller's store is never touched").
The Memory-side `gate run` step additionally uses its own internal scratch
stores for its 8 clauses, unrelated to this gate's scratch store.

## Terminal surface

```
python -m midnight_performance.compatibility_gate [--path report.json] [--memory-repo-path <path>]
```

Exit 0 when `passed: true`; exit 1 with the specific failing
clause(s)/check(s) named in the JSON report otherwise. `--path` writes the
report as evidence, mirroring `gate run --path`.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Memory unreachable (bad `node`, missing CLI) | `memory_product_truth`, `performance_to_memory_propose`, and `memory_to_performance_read` fail with a typed detail naming the cause; `standalone_degraded_operation` still passes (it is specifically testing this scenario) |
| A bridge test regresses | `cross_language_test_suites` fails with pytest's own summary line as the detail |
| A local duplicate-authority symbol is reintroduced into `midnight_performance.memory` | `no_local_duplicate_authority` fails by name |

## Agent neutrality / game independence

Every clause runs from a real subprocess or a real in-process call with no
LLM, no game dependency, and no provider beyond what Memory/Performance
already use internally.
