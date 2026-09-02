# Library Memory Engine — Contradiction/Supersession Qualification (v1.23.0)

Implemented in `src/engine/qualification.ts`. Task 44, Phase VIII.

## Principle

Prove — over the frozen qualification corpus (docs/CORPORA.md) — that
historical facts remain queryable and current truth resolves correctly
WITHOUT destructive overwrite. Lineage is qualified, not asserted: every
check is a falsifiable invariant with a stable name and a deterministic
detail string.

## Frozen checks

| Check | Invariant |
|---|---|
| `chain-integrity` | the supersession chain is complete, ordered, and carries its explicit reason |
| `predecessor-immutability` | the superseded record keeps its original content, a matching canonical content hash (recomputed), its retirement reason, and its successor link |
| `resolution-non-destructive` | the contradiction LOSER is retired intact (content + hash + winner link), the winner is active, and the resolution event attributes winner/action/reason |
| `historical-queryable` | the superseded fact is retrievable as-of its capture time, via lexical search with status filter, via the decision timeline, and via the revision chain |
| `current-truth-resolves` | the current view exposes exactly the winning versions of both the supersession chain and the resolved contradiction; no open groups remain |
| `no-destructive-overwrite` | EVERY corpus record's stored hash matches a freshly recomputed canonical hash of its content, and retired records retain their frozen original content |

## Failure / degradation

| Condition | Behavior |
|---|---|
| Corpus missing | built first (replay-safe), then qualified |
| Tampered/rewritten history | the specific named check FAILS (`passed: false`, exit 1 on the CLI) |
| Forged extra "current truth" | `current-truth-resolves` fails (the check is falsifiable) |

## Agent neutrality / game independence

Deterministic invariants over frozen fixtures — no LLM, no provider, no
game. Terminal surface: `qualify lineage [--path <report.json>]`
(exit 1 when any invariant fails; `--path` writes the report as evidence).
