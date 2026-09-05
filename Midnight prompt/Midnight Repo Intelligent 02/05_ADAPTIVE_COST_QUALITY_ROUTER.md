# MIDNIGHT REPO INTELLIGENT 02 — EXECUTION 05

## Adaptive Cost–Quality Router

**Mode:** learned escalation + quality floor + explicit abstention

## Goal

Replace static "cheap vs expensive" model selection with a provider-neutral routing authority that chooses the cheapest resolver expected to satisfy the task's quality floor.

This execution is inspired by LLM-routing/cascade research, but Midnight must learn from its own Performance telemetry, verification outcomes, latency, and cost.

## Canonical ownership

There must be exactly one production escalation/routing authority for Repo Intelligent.

If `cost_quality.py`, pipeline logic, provider adapters, or other modules already implement overlapping routing, consolidate them. Do not add a second router beside the old one.

## Resolver classes

The router reasons over capabilities, not provider brands:

- deterministic computation;
- exact/cache reuse;
- lexical/graph retrieval;
- lightweight local ML;
- semantic retrieval;
- small/cheap model;
- strong model;
- external research;
- defer/abstain.

Providers/models are adapters underneath capability classes.

## Routing input

Use bounded features such as:

- question/task class;
- internal sufficiency status;
- evidence coverage;
- contradiction/freshness state;
- learning pressure;
- retrieval quality;
- expected information gain;
- historical provider/model usefulness for comparable tasks;
- historical latency/failure rate;
- estimated token/request cost;
- privacy policy;
- hard budget state;
- user-visible consequence severity.

## Quality floors

Define explicit quality floors by decision class.

Examples:

- classification/routing may tolerate calibrated probabilistic decisions with abstention;
- evidence synthesis requires stronger provenance/coverage;
- security/privacy decisions cannot be relaxed for cost;
- external-research necessity must not be decided solely from model self-confidence.

The router may save cost only within the applicable quality constraint.

## Cascade behavior

Implement an explicit escalation contract:

`cheap rung -> qualify result -> accept OR abstain/escalate -> next rung`

A cheaper result is accepted only when qualification succeeds.

Never escalate merely because another model exists. Never stay cheap merely because budget is low; if the quality floor cannot be met within budget, return a bounded `BUDGET_INSUFFICIENT`/deferred result.

## Research-informed mechanisms

Evaluate, not blindly adopt:

- RouteLLM-style learned routing from preference/outcome data;
- FrugalGPT-style cascades;
- BARGAIN-style quality-constrained cost optimization;
- cost-sensitive learning-to-defer;
- contextual-bandit routing after sufficient online evidence exists.

Document which mechanism is appropriate for Midnight's actual dataset size and feedback quality.

## Counterfactual evaluation

Avoid pretending every historical run tells us how every alternative model would have performed.

Track counterfactual evidence status:

- `OBSERVED` — alternative was actually run/evaluated;
- `REPLAYED` — alternative was tested later on preserved eligible input;
- `ESTIMATED` — learned estimate only;
- `UNKNOWN`.

Use shadow/replay evaluation on a bounded sample to create real comparison data where privacy/cost policy allows it.

## Provider neutrality

No hard-coded Claude/OpenAI/Gemini-specific routing semantics in the core.

Adapters expose standardized telemetry:

- model capability class;
- cost estimate/actual cost;
- latency;
- failure reason;
- context/token constraints;
- result qualification evidence.

## Budget integration

Support:

- per-job hard ceilings;
- per-project soft daily/weekly budgets;
- emergency hard ceiling;
- budget-aware early stopping;
- explicit skip/defer reasons.

Budget must never bypass privacy/security policy.

## Verification

Prove with replay fixtures and, when configured, optional live provider qualification:

- easy cases remain on cheap/local rungs;
- ambiguous cases escalate;
- high-confidence-but-wrong cheap outcomes are caught by qualification where the design claims they are;
- low confidence abstains;
- quality-floor failure does not become a cheap false success;
- router disabled -> deterministic baseline remains functional;
- provider unavailable -> alternative capability or explicit degradation;
- cost accounting reconciles with Performance AI accounting rather than creating a competing ledger;
- core routing remains provider-neutral.

## Promotion gate

Do not enable adaptive routing for production unless holdout/replay evidence demonstrates either:

- lower cost/latency at statistically credible preserved quality; or
- better quality at equal/bounded cost.

Otherwise leave the adaptive router in shadow mode.

## Final report

Return:

- `GOAL: YES | PARTIAL | NO`
- canonical routing owner before/after
- quality-floor definitions
- resolver ladder
- learned vs deterministic routing status
- replay/holdout metrics
- cost and latency delta
- counterfactual evidence quality
- abstention/escalation rates
- provider neutrality evidence
- exact reason if production promotion is denied.