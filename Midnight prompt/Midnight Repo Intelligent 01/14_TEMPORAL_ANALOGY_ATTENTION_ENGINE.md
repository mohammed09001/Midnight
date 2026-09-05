# MIDNIGHT REPO INTELLIGENT --- EXECUTION 14

## Temporal Knowledge, Cross-Repository Analogy & Attention Engine

**Parent:** Midnight Performance **Purpose:** Turn project history +
outside repositories into time-aware, explainable learning rather than
generic recommendations.

## Goal

Build three capabilities together because their value depends on each
other: 1. time-aware knowledge; 2. structural analogy to external
repositories; 3. strict user-attention gating.

## Temporal graph requirements

Every derived knowledge relation must support capture time and, where
applicable, validity/supersession/contradiction. Preserve association to
Performance episodes/change sets and repository snapshots. A later
repository state may invalidate an old insight without deleting its
historical truth.

## External analogy requirements

For each candidate external repository, compare explicit dimensions: -
architectural role; - dependency/protocol overlap; - component/data-flow
pattern; - failure/reliability problem; - test strategy; -
scale/maturity constraints; - meaningful differences.

Produce an `AnalogyRecord` with: - evidence; - comparable dimensions; -
non-comparable dimensions; - confidence; - why it matters now; -
freshness; - cost.

Reject keyword-only similarity.

## Attention requirements

Create a finite attention budget independent from compute budget. Rank
by:
`learning_pressure × evidence_strength × novelty × expected_learning_value × timing_fit`
minus: `redundancy + interruption_cost + uncertainty + stale_risk`.

Support quiet queue, cooldown, dismiss suppression, protected focus, and
user-pull override.

## Unique release metric

Measure:
`useful_project_learning / (user_attention_cost + normalized_compute_cost)`

Do not optimize click rate alone.

## Verification

Test temporal supersession, contradictory external sources, structurally
similar repository with different language, keyword-similar but
structurally irrelevant repository, stale insight, repeated dismissal,
quiet mode, and later Performance association without causal overclaim.

Final report: `GOAL YES/PARTIAL/NO`, evidence, files, tests, gaps.
