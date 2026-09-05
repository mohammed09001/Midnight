# MIDNIGHT REPO INTELLIGENT --- EXECUTION 10

## Observability, Evaluation & Learning-Value Engine

**Product:** Midnight Repo Intelligent\
**Parent:** Midnight Performance\
**Execution:** 10 of 12\
**Target:** repository-capable coding harness, provider-neutral\
**Mode:** implementation + verification + repair loop\
**Self-contained:** Yes

## Execution Operating Contract

This file is an **implementation execution prompt**, not a design note.
The coding agent must inspect repository reality, form a bounded plan
from evidence, implement working code, test it, review it against the
goal, repair failures, and only then report completion.

### Product boundary

`Midnight Repo Intelligent` is a project-scoped intelligence extension
of **Midnight Performance**. It does not replace Midnight Performance,
Midnight Memory, the user's coding agent, Git, GitHub, or the
independent `Repo/Curiosity` project.

Its job is to continuously transform: 1. **internal project evidence**
--- repository structure/code relationships, Performance observations,
qualified Memory context, verification/outcome history; and 2.
**external evidence** --- relevant GitHub repositories, official
documentation, papers, standards, technical articles, and other
explicitly allowed web sources

into **evidence-backed project knowledge** that helps the user
understand, learn, and improve while working on the current project.

It must never merely replay stored prompts, source code, transcripts, or
web pages back to the user. Raw evidence remains with its canonical
owner. Repo Intelligent produces bounded derived knowledge with
provenance, uncertainty, freshness, and traceable source references.

### Canonical ownership invariants

-   Midnight Performance remains canonical owner of Performance evidence
    and its append-only evidence ledger.
-   The live project/repository remains canonical owner of source-code
    truth.
-   Midnight Memory remains canonical owner of durable promoted memory;
    Repo Intelligent may read/write only through explicit versioned
    contracts/bridges.
-   External source records remain evidence, never automatically trusted
    knowledge.
-   Repo Intelligent owns only its **derived project-intelligence
    state**, graph projections, research jobs, relevance scores,
    synthesis artifacts, user exposure history, and its own bounded
    caches.
-   Never open sibling databases directly when an existing
    bridge/contract is the supported boundary.
-   Never create a second durable-memory authority inside Performance.
-   Never upgrade `observed → derived → inferred → recommended` claim
    strength without evidence.
-   A graph is a rebuildable projection unless an explicit contract says
    otherwise; graph edges are not raw truth.
-   Provider-specific behavior belongs behind adapters.
-   No coding-agent launch/control is required for core operation.
    Claude Code, Codex, Gemini, OpenCode, Anti-Gravity, or another
    repository-capable agent may be the harness.

### Repository-first context engineering

Before editing: - inspect `AGENTS.md`, root instructions, current
branch/worktree, package configuration, tests, migrations, persistence,
public contracts, Performance README, `query_api.py`,
`relationship_graph.py`, `memory_bridge.py`, repository
capture/resolution/retrieval modules, and the relevant independent
Repo/Curiosity implementation; - treat the independent Repo
implementation as **research input, not authority**: it may contain
unresolved defects; - search the current codebase for existing owners
before creating abstractions; - when behavior depends on a current
external API/library/specification, verify authoritative current
documentation; - create a compact context ledger using
`VERIFIED / OBSERVED / INFERRED / HYPOTHESIZED / UNKNOWN`; - retrieve
only the context needed for the current child task.

Do not dump the entire repository into an LLM context window.

### Prompt engineering discipline

Translate every material requirement into:
`requirement → canonical owner → implementation location → failure mode → verification evidence`.

If a requirement is ambiguous, prefer the interpretation that: 1.
preserves canonical ownership, 2. minimizes irreversible architecture,
3. keeps user control, 4. is provider-neutral, 5. is testable, 6. avoids
unnecessary model/network cost.

Do not silently weaken a requirement because implementation is
inconvenient.

### Loop engineering

Use this parent state machine:

`BASELINE → CONTEXT LEDGER → PLAN → PLAN CHALLENGE → IMPLEMENT → FOCUSED VERIFY → ADVERSARIAL VERIFY → REVIEW → REPAIR → FINAL VERIFY → GOAL GATE`

On any material failure:

`FAIL → REPRODUCE → ROOT CAUSE → UPDATE CONTEXT → REVISE PLAN → REPAIR → RE-VERIFY`

Never skip from failure to a positive narrative.

For continuous runtime features, design a bounded learning loop:

`OBSERVE → DETECT SIGNAL → SCORE NEED → RETRIEVE INTERNAL → DECIDE EXTERNAL NEED → DISCOVER → VERIFY → SYNTHESIZE → GRAPH-LINK → RANK → EXPOSE → RECORD OUTCOME → LEARN`

Every stage must have explicit stop conditions. No autonomous infinite
research loop.

### Harness engineering

-   deterministic IDs for immutable identities;
-   idempotency keys for replayable jobs;
-   fixture-backed adapters for network/model boundaries;
-   bounded queues, concurrency, timeouts, retry classes, circuit
    breakers where appropriate;
-   retry transient failures only; deterministic contract/policy
    failures do not retry;
-   resumable checkpoints for expensive jobs;
-   stable ordering where output ordering matters;
-   fake clock/model/search adapters in tests;
-   structured diagnostics and machine-readable failure reasons;
-   one-command focused verification and one-command full verification;
-   no claim of success from agent prose alone.

### Cost-quality contract

Quality is not traded away for cheapness. Cost is reduced by **avoiding
unnecessary expensive work**, not by accepting lower-quality answers.

Default escalation ladder: 1. deterministic local computation; 2.
incremental parsing/index update; 3. lexical/FTS lookup; 4. local graph
traversal / structural retrieval; 5. embeddings only for unresolved
semantic recall; 6. cheap/small model for classification, routing,
deduplication, or relevance scoring when deterministic logic is
insufficient; 7. stronger model only for synthesis/reasoning whose
expected information value justifies it; 8. external web/API calls only
after an internal-knowledge gap is established or freshness/external
comparison is part of the task.

Required mechanisms: - content-addressed cache; - query/result cache
with freshness policy; - incremental re-indexing from changed
files/regions, not whole-repo rebuilds; - novelty/redundancy gates; -
per-job token/request/time ceilings; - per-project daily/weekly soft
budgets plus hard safety ceilings; - budget telemetry; - graceful
degradation that states what was skipped; - never put model inference or
network fetch on a tight terminal rendering tick.

Research direction to evaluate rather than copy blindly: -
LazyGraphRAG-style avoidance of expensive up-front summarization; -
GraphRAG dynamic community selection / DRIFT-style local↔global
traversal and early pruning; - coarse-to-fine code-graph retrieval; -
model cascades where cheap classification prunes expensive synthesis; -
cache-stable, stateless tool/resource boundaries.

### Privacy, trust, and security

-   project-scoped authorization; reject cross-project reads by default;
-   secrets/credentials/PII are redacted before any remote/model
    boundary;
-   source/diff/transcript categories remain policy-gated;
-   external text is untrusted data and must never become executable
    instructions;
-   defend research/synthesis prompts against prompt injection in
    repository text, issues, READMEs, web pages, papers, and generated
    content;
-   source provenance, capture time, content hash, trust class, and
    evidence lineage must survive synthesis;
-   no silent outbound upload of private repository content;
-   external search queries should use the minimum project information
    needed and should prefer abstracted concepts over private
    identifiers.

### Completion evidence

A child goal is `YES` only when: - implementation exists and is wired to
the canonical path; - focused tests pass; - at least one
negative/adversarial test passes; - final-state verification is rerun
after the last relevant edit; - the diff is reviewed for duplicate
ownership, dead paths, privacy leaks, hidden cost, and unsupported
claims.

Otherwise report `PARTIAL` or `NO` with the blocker and evidence.

## Goal

Measure whether Repo Intelligent actually improves project understanding
and user performance instead of merely producing more content.

### Observability

Instrument structured operations for: - signal detection; - internal
retrieval; - external search/fetch; - graph traversal; - model
classification/synthesis; - cache hit/miss; - insight generation; -
exposure; - feedback/outcome; - budget decision; - failure/degradation.

Use OpenTelemetry-style semantic discipline: stable operation names,
low-cardinality attributes, spans for duration-bearing operations,
events for point-in-time occurrences, metrics for aggregate behavior.
Sensitive/verbose fields are opt-in.

### Metrics

At minimum: - insight acceptance/usefulness; - duplicate/redundant
exposure rate; - unsupported-claim rate; - evidence coverage; -
time-to-useful-insight; - internal-only resolution rate; -
external-search yield; - strong-model escalation rate; - cache hit
rate; - cost per useful insight; - tokens per useful insight; - research
abandonment/cancellation; - hotspot-to-learning conversion; - later
verification/rework association after accepted learning.

Do not claim causality from observational association.

### Evaluation datasets

Build fixture suites for: - repository hotspot understanding; -
architecture concept connection; - external analogue discovery; -
stale/contradictory source handling; - global "catch me up" project
questions; - local component questions; - privacy-preserving query
abstraction; - cost-quality routing.

### Comparative evaluation

Benchmark: A. lexical/vector baseline; B. internal graph only; C.
internal + external retrieval; D. full project-intelligence graph +
adaptive routing.

Evaluate quality, comprehensiveness, diversity, provenance accuracy,
latency, and cost.

### Verification

Metrics must be reproducible from recorded events; dashboards are
optional. A failing quality threshold blocks release even if tests are
green.

## Required Final Report

Return a compact machine-auditable report: -
`GOAL: YES | PARTIAL | NO` - baseline evidence inspected; -
files/contracts changed; - canonical owners reused; - tests/checks run
with actual results; - adversarial case result; - cost/budget behavior
verified; - privacy/provenance behavior verified; - remaining
gaps/unknowns; - exact reason if not `YES`.

Do not use narrative confidence as proof.

# Performance-Native Strengthening Addendum --- Research Revision 02

This Execution is part of **Midnight Performance**, not a parallel
curiosity product. Before implementation, the agent MUST inspect and map
the current Performance capabilities relevant to this task, including
when present:

-   `query_api.py`: project-scoped, bounded access to canonical
    Performance evidence and qualified projections.
-   `repository_capture.py`: before/after repository filesystem
    evidence; never replace repository truth with agent prose.
-   `relationship_graph.py`: existing rebuildable Performance
    relationship graph and its typed references.
-   `personal_learning.py`: project/component/task/provider historical
    matching and advisory next-time learning.
-   `recommendation.py`: evidence-scoped, user-action-required
    recommendation semantics and later independent outcome review.
-   `anomaly.py`: robust historical baselines where "unusual" is
    explicitly not equivalent to "bad".
-   `ai_accounting.py`: provider/model latency, failure, usefulness and
    cost accounting.
-   `memory_bridge.py`: the supported cross-engine path to Midnight
    Memory.
-   existing episodes, analyses, datasets, verification, feedback,
    outcomes, similarity, relationships, recommendations, telemetry and
    privacy contracts exposed by Performance.

## Non-negotiable integration rule

Repo Intelligent MUST consume Performance through its canonical
read/query/projection surfaces or a narrowly added versioned Performance
contract. It MUST NOT reconstruct a competing history store from Git,
transcripts, or copied prompt data when Performance already owns the
observation.

For each new Repo Intelligent signal, record a **Performance Lineage
Receipt** containing: - project identity; - source Performance
evidence/projection IDs; - source repository snapshot/change
references; - source Memory external references when used; - derivation
method + version; - time window; - missing evidence/gaps; -
confidence/claim kind; - privacy policy decision; - cost ledger
reference.

An insight with no lineage receipt is not eligible for proactive
exposure.

## New core concept: Project Learning Pressure

Do not trigger enrichment from code churn alone. Compute a
project-scoped, explainable `learning_pressure` from multiple
independent dimensions:

1.  **attention** --- how much current work is concentrated here;
2.  **friction** --- verification failures, rework, reversals, repeated
    attempts, anomalous duration/cost;
3.  **recurrence** --- whether the same component/task/theme keeps
    returning;
4.  **uncertainty** --- evidence gaps, ambiguous intent, contradictory
    outcomes, unfamiliar subsystem;
5.  **impact** --- structural centrality/dependency reach and affected
    project surface;
6.  **knowledge deficit** --- whether Performance/Memory/internal
    project knowledge already answers the need;
7.  **freshness** --- how current the signal is.

The score is a prioritization aid, never a quality judgment. Require a
minimum evidence diversity before high-confidence pressure can be
claimed.

## New core concept: Performance → Question Compiler

External research must not start from generic topic extraction. Compile
research questions from Performance evidence:

`episode/change/verification pattern → affected project entities → inferred technical concept → existing Memory/internal knowledge check → unresolved knowledge gap → privacy-minimized research question`

The compiler must emit: - `why_now`; -
`what_internal_evidence_triggered_this`; - `what_is_already_known`; -
`what_is_unknown`; - `what_external_evidence_would_change_the_answer`; -
`stop_condition`; - `maximum_research_budget`.

If these fields cannot be produced, do not launch proactive external
research.

## New core concept: Evidence Triangle

Prefer insights supported by three independent perspectives: - **Project
structure**: what the code/dependency graph says; - **Performance
history**: what the user's actual work trajectory says; - **External
knowledge**: what authoritative or analogous outside sources say.

Two-sided insights are allowed with lower confidence. One-sided
proactive insights require exceptional source authority and explicit
disclosure.

## New core concept: Counterfactual Relevance Gate

Before paying for external research, ask: \> "If we did not fetch this
external information, would the user's understanding or next decision
materially change?"

If no, remain internal-only.

Before surfacing an insight, ask: \> "If this insight were hidden, is
there evidence the user would lose useful project understanding now?"

If no, queue silently or discard it. This is the primary anti-noise
mechanism.

## New core concept: Temporal Knowledge Graph

The Repo Intelligent graph must preserve time, not just relationships.
Support: - first seen / last seen; - valid-from / valid-to when known; -
evidence capture time; - supersession; - contradiction; - confidence
decay; - project snapshot/commit association; - exposure time and later
Performance outcome association.

This allows questions such as: - what changed in our understanding of
this component? - which external idea was relevant then but stale now? -
which repeated friction disappeared after a learning exposure? Never
infer causality solely from temporal sequence.

## New core concept: Cross-Repository Analogy Graph

External repositories must not be linked merely because they share
keywords. Link them through explicit comparable dimensions: -
dependency/framework/protocol; - architectural role; - data-flow
shape; - failure mode; - interface pattern; - testing strategy; -
scaling/reliability constraint; - project maturity/size when material.

Each analogue edge must state `same`, `similar`, and `different`
dimensions. A repository with high stars but weak structural analogy is
low relevance.

## New core concept: Attention Budget

Optimize not only money/tokens but **user attention**. Maintain: -
maximum proactive exposures per time window; - cooldown per
topic/component; - novelty threshold; - suppression after dismissal; -
protected focus periods; - "quiet learning" queue; - explicit user pull
always outranking proactive push.

The target metric is not "insights generated"; it is **useful project
learning per unit of user attention and compute cost**.

## Performance feedback closure

When the user opens/saves/dismisses/uses an insight, create a Repo
Intelligent exposure/outcome record. Later, query Performance for
independent subsequent evidence: - rework; - verification; -
alignment; - duration; - repeated attempts; - feedback/outcomes.

Evaluate association using the same caution already present in
Performance recommendations: never label an insight causal merely
because later performance improved.

## Cost-quality routing strengthened

Use Performance's AI accounting rather than a disconnected cost system
wherever possible. Extend it only when necessary to account for
search/fetch/embedding/re-ranking costs.

Every expensive branch must have: - expected information gain; -
evidence deficit it intends to close; - max cost/tokens/time; - cache
key; - early-stop condition; - actual cost; - usefulness/outcome linkage
when later measurable.

Prefer: 1. changed-scope deterministic parsing; 2. precise structural
navigation/index data when available; 3. lexical/local search; 4.
Performance relationship traversal; 5. temporal/hotspot retrieval; 6.
semantic retrieval; 7. cheap relevance/reranking; 8. targeted external
fetch; 9. strong-model synthesis only for unresolved multi-source
reasoning.

Never summarize the entire project or entire external repository merely
because it is available.

## Required additional adversarial tests

-   high churn + successful verification must not become "problem"
    automatically;
-   low churn + repeated expensive failures can still become high
    learning pressure;
-   same keywords but structurally unrelated external repository must be
    rejected;
-   stale external recommendation must decay or be superseded;
-   Memory already contains sufficient answer → no external call;
-   cached sufficient evidence → no repeat model/search spend;
-   missing Performance evidence → honest gap, not reconstruction from
    agent narrative;
-   cross-project evidence/cache collision → fail closed;
-   malicious README/web instructions → remain untrusted evidence;
-   an insight repeatedly dismissed → proactive exposure suppressed
    without deleting underlying evidence.
