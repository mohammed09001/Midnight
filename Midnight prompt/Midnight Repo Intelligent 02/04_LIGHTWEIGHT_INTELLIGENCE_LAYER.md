# MIDNIGHT REPO INTELLIGENT 02 — EXECUTION 04

## Lightweight Intelligence Layer

**Mode:** measured ML introduction, local-first, no blind neural-network adoption

## Goal

Introduce a lightweight machine-learning/statistical layer that reduces avoidable LLM work by making cheap predictions about routing, relevance, novelty, and expected value — without becoming a new truth authority and without making correctness depend on ML availability.

## Principle

Machine learning is used where deterministic rules become brittle or expensive, but the output remains a **prediction with uncertainty**.

Preferred model order:

1. calibrated rules/baselines;
2. linear/logistic models;
3. small trees / incremental trees;
4. nearest-neighbor or similarity-based estimators;
5. contextual bandits for routing after enough outcomes exist;
6. neural networks only if a measured benchmark proves simpler models inadequate.

No GPU is required for this execution.

## Candidate decisions

Investigate which of these decisions currently consume LLM/model work or use brittle static thresholds:

- internal sufficiency probability;
- external-search usefulness;
- source/result relevance;
- novelty/redundancy prediction;
- expected learning value;
- likely need for strong synthesis;
- likely model/provider suitability;
- attention interruption risk;
- semantic-cache reuse safety.

Do not build one model for all decisions unless evidence proves the feature/target semantics genuinely align.

## Feature contract

Features must be derived from local metadata and canonical evidence references whenever possible, for example:

- learning-pressure dimensions;
- question class;
- repository entity type/depth;
- Memory sufficiency dimensions;
- Performance recurrence/friction/anomaly signals;
- source class/trust/freshness;
- retrieval hit/coverage counts;
- historical verification success;
- historical model cost/latency/usefulness;
- graph distance / structural overlap;
- contradiction state;
- prior user exposure/outcome signals.

Forbidden default features:

- raw source code;
- secrets;
- complete prompt text;
- complete Memory records;
- provider-specific identifiers that unnecessarily destroy portability.

## Training-record contract

Create a minimal project-scoped learned-decision record that references source evidence rather than copying it.

Include:

- decision ID/type;
- feature schema/version;
- feature values safe for the configured privacy policy;
- prediction and uncertainty;
- action chosen;
- later label/outcome when available;
- cost/latency;
- evidence references;
- model/version;
- timestamp/time window.

## Cold-start requirement

At first installation or insufficient sample count:

- production decisions use deterministic policy;
- ML runs in shadow mode only;
- predictions and eventual outcomes are recorded for evaluation;
- no learned model may silently take control.

## Calibration and abstention

Every production-eligible classifier/ranker must support an abstention zone.

Example behavior:

- high-confidence cheap decision -> accept;
- ambiguous prediction -> escalate to deterministic deeper retrieval or model stage;
- contradictory/stale/privacy-sensitive case -> hard-rule path, not ML override.

Calibration must be measured on replay/holdout data. Raw model probability is not automatically calibrated confidence.

## Optional implementation libraries

Inspect current dependency policy first.

A small dependency such as River or scikit-learn may be used only if:

- it materially reduces maintenance risk;
- license/dependency constraints are acceptable;
- models serialize deterministically enough for the project contract;
- a dependency-free deterministic fallback remains functional.

Otherwise implement only the minimal algorithms required.

## Evaluation

For every learned decision compare against:

- deterministic baseline;
- current LLM/model baseline when applicable;
- always-escalate baseline.

Measure:

- precision/recall or task-appropriate quality;
- calibration error;
- abstention rate;
- false suppression;
- false escalation;
- latency;
- compute/API cost avoided.

A learned component is not promoted merely because aggregate accuracy looks good.

## Verification

Prove:

- ML can be disabled/deleted with no correctness failure;
- cold start uses deterministic policy;
- shadow mode never changes user-visible action;
- feature records do not contain prohibited raw content;
- model-version mismatch fails safely;
- uncertain predictions abstain;
- hard privacy/provenance rules cannot be overridden;
- at least one candidate decision demonstrates measurable offline value before production eligibility.

## Final report

Return:

- `GOAL: YES | PARTIAL | NO`
- decisions considered for ML
- model class selected for each and why
- features used
- shadow/production status
- calibration results
- cost/latency delta
- quality delta
- abstention behavior
- dependencies added or explicitly avoided
- candidates rejected because ML did not outperform the baseline

A valid result may be: `NO ML PROMOTION — deterministic baseline remains superior`.