# Library Memory Engine — Retrieval Evaluation (v1.23.0)

Implemented in `src/engine/evaluation.ts`. Task 43, Phase VIII.

## Principle

Measure precision/recall-style usefulness for the exact, lexical, temporal,
hybrid and semantic retrieval surfaces against FROZEN relevance judgments
over the qualification corpus (docs/CORPORA.md), with fully transparent
results: every query reports the relevant record keys, the retrieved record
keys, and per-query precision/recall/MRR — nothing is an opaque score.

## Transparent baselines + semantic gate

The deterministic strategies are the baseline: `exact` (structured subject
match), `lexical` (BM25 FTS), `temporal` (current view at pinned instants +
as-of at store-derived instants), and `hybrid-baseline` (deterministic
signals only). Semantic additions (`semantic` standalone, `hybrid-semantic`)
must BEAT or COMPLEMENT the baselines — the frozen gate fails on any
degradation (`verdict: "degrades"` → `passed: false`). On the frozen corpus
the verdict is `complements`: the semantic surface retrieves relevant
records where lexical AND-strictness retrieves none (`auth0 rs256 clerk`,
`sessions limit per project`), while hybrid aggregates are non-degrading.

## Frozen judgments

Queries and ground truth are frozen in code at
`QUALIFICATION_CORPUS_VERSION`; records are identified by
`subject::content` keys (no ids, no timestamps). Judgments cover exact
subject lookup, BM25-friendly queries, AND-strictness (paraphrase) cases,
privacy-gated material (`API key rotation` is exact/lexical reachable but
NEVER semantically retrievable — the projection excludes `sensitive`), and
temporal correctness (expired windows invisible at the wrong instant,
visible inside their window; superseded facts visible as-of their capture).

## Metrics

Per query: `precision@k` (k=10), `recall@k`, MRR (first relevant rank) over
record-level truth; per strategy: micro-aggregates. Pass bars are frozen
qualification thresholds (exact ≥ 0.99, temporal ≥ 0.99, lexical ≥ 0.55,
hybrid-baseline ≥ 0.55 recall; semantic gate non-degrading) — bars express
"useful retrieval", not measured self-reference.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Corpus missing | built first (replay-safe), then evaluated |
| `includeSemantic: false` | baseline-only report, `semanticGate: null`, still `passed`-eligible |
| Semantic degrades a baseline | gate `verdict: "degrades"`, `passed: false` |
| Tampered corpus | metrics move; frozen bars can fail (the evaluation is falsifiable) |

## Agent neutrality / game independence

Deterministic corpus + frozen judgments — no LLM judge, no external
provider (the optional semantic strategies use only the built-in
deterministic provider), no game. Terminal surface:
`evaluate retrieval [--no-semantic] [--path <report.json>]`
(exit 1 when the frozen bars or the gate fail).
