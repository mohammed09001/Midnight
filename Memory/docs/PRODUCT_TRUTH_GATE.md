# Midnight Memory — Product-Truth Gate (v1.25.0)

Implemented in `src/engine/gate.ts`. Task 46, Phase VIII — the V1 gate.

## Principle

A machine-verifiable audit of the eight product-truth clauses. Every check
executes FRESH evidence at gate time — the gate never rests on prose or on
historical test runs. It composes the Task 42–45 qualification suites as
evidence, runs its own audits on disposable scratch stores, and touches
nothing the caller owns. The module deliberately stands OUTSIDE the public
surface it audits: nothing in the engine imports it, so the runtime import
graph stays acyclic.

## The eight clauses

| Clause | Fresh evidence |
|---|---|
| ownership | public surface exposes canonical owners only (no store export, no store contract operation, deterministic scope identity) |
| contracts | stable version format; 0.x callers rejected with `MEMORY_CONTRACT_MISMATCH`; unknown operations return typed envelope errors; same-major callers accepted across minors |
| standalone | add + lexical + degraded hybrid succeed with no provider, no MCP host, and no sibling engines |
| terminal | `doctor`, `corpus build/verify`, `evaluate retrieval`, `qualify lineage`, `qualify recovery` all exit 0 from fresh CLI processes |
| provenance | every record traces to by-reference evidence; observed claims without evidence are rejected; epistemic classes remain distinguishable |
| privacy | secret material rejected; sensitive material excluded from excerpts (labeled untrusted data) and embeddings; privacy purges propagate to derived stores; isolation defaults to strict |
| explanations | lexical, ranked, fused, and hybrid retrieval all expose why each record matched and how it ranks (per-signal contributions, provenance breakdowns, availability reasons) |
| extensibility | third-party providers plug in behind the neutral interface with their identity flowing through; zero runtime dependencies; additive contract surface |

## Failure / degradation

| Condition | Behavior |
|---|---|
| Any clause fails | `passed: false`, exit 1 on the CLI, failing clause:check named in the report |
| Scratch-store setup fails | the affected checks fail honestly — the gate never reports vacuous success |

## Agent neutrality / game independence

The gate proves the engine is USEFUL BEFORE GAME INTEGRATION: every audited
capability runs from a terminal process with zero runtime dependencies and
no provider beyond the built-in deterministic adapter. Terminal surface:
`gate run [--path <report.json>]` (exit 1 when any clause fails; `--path`
writes the report as release evidence).
