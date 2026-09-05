# MIDNIGHT REPO INTELLIGENT 02 — EXECUTION 06

## Online Learning, Feedback, and Drift Control

**Mode:** bounded adaptation, shadow-first, rollback-safe

## Goal

Allow Repo Intelligent to improve routing and decision estimates from real project outcomes over time without requiring large retraining jobs, GPU infrastructure, or blind self-reinforcement.

The system must learn from verified outcomes, not from its own previous predictions alone.

## Required investigation

Inspect:

- current exposure/outcome records;
- Performance recommendation/outcome and AI-accounting semantics;
- learning-loop scheduler/checkpoint code;
- any ML state introduced by Execution 04/05;
- project-scoped persistence and privacy contracts;
- test clocks and replay infrastructure.

Reuse existing outcome semantics instead of inventing a second feedback vocabulary.

## Online-learning policy

A learned decision receives an update only when a legitimate label/reward exists.

Preferred label sources, strongest first:

1. independent verification result;
2. later observed project outcome;
3. explicit user feedback;
4. reproducible replay/benchmark result;
5. bounded proxy metric with clearly lower epistemic strength.

Do not train on "the model said it was good" as ground truth.

## Suitable online tasks

Possible incremental tasks include:

- model/resolver selection;
- external-search usefulness;
- relevance filtering;
- novelty prediction;
- attention timing;
- expected learning value;
- cache-reuse risk.

Each task requires its own reward/label definition.

## Contextual-bandit use

Contextual bandits may be used for routing only after:

- a deterministic safe baseline exists;
- enough outcomes exist to estimate reward;
- exploration budget is explicitly bounded;
- user-facing quality floors remain enforced;
- dangerous/sensitive decisions are excluded from exploration;
- offline/shadow evaluation demonstrates plausible value.

Exploration must never intentionally degrade security/privacy guarantees.

## Drift detection

Monitor at least:

- prediction calibration drift;
- reward/usefulness drift;
- provider/model latency/cost drift;
- task-distribution drift;
- feature-distribution drift where meaningful;
- rising abstention or escalation rates.

Use lightweight rolling statistics or drift detectors. A library such as River may be used if repository policy permits, but no dependency is mandatory.

On drift:

`detect -> mark model degraded/stale -> reduce or disable production authority -> return to deterministic/router baseline -> accumulate fresh shadow evidence -> recalibrate/retrain -> requalify`

## Catastrophic self-reinforcement prevention

Prevent feedback loops where the router only collects outcomes from the option it already prefers.

Required mechanisms:

- counterfactual evidence status;
- bounded shadow evaluation of alternatives where policy allows;
- minimum exploration policy only for low-risk eligible cases;
- per-model/sample counts;
- confidence intervals or uncertainty tracking;
- no reward update when outcome attribution is ambiguous.

## Persistence

Persist only bounded learned state and references required for reproducibility:

- feature schema version;
- model parameters/version;
- training/update counts;
- rolling metrics;
- drift status;
- checkpoint hash;
- evidence/outcome references.

Learned state must be disposable. Deleting it resets intelligence to deterministic baseline rather than corrupting canonical project knowledge.

## Continuous runtime

If Repo Intelligent claims continuous learning, wire updates through the canonical bounded learning loop with:

- debounce;
- cooldown;
- durable checkpoints;
- idempotent event handling;
- bounded queues;
- circuit breaker;
- startup recovery;
- shutdown flush semantics;
- explicit opt-out.

Do not implement an uncontrolled background research loop.

## Verification

Prove:

- no label -> no learning update;
- ambiguous attribution -> no reward update;
- verified outcome updates the eligible model exactly once;
- duplicate event replay is idempotent;
- drift can disable a learned model automatically;
- deterministic fallback takes over after learned-state deletion/corruption;
- project A cannot train project B's private router unless an explicit future federated policy exists;
- shadow evaluation does not affect user-visible routing;
- exploration never overrides privacy/security hard rules.

## Final report

Return:

- `GOAL: YES | PARTIAL | NO`
- tasks allowed to learn online
- label/reward definitions
- minimum sample thresholds
- exploration policy
- drift detectors/metrics
- rollback behavior
- checkpoint/recovery results
- learned-state size/cost
- cases intentionally excluded from online learning

Do not call the system self-learning if it only stores predictions without verified feedback.