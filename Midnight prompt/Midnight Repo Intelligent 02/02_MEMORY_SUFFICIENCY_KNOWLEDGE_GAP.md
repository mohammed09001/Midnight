# MIDNIGHT REPO INTELLIGENT 02 — EXECUTION 02

## Memory Sufficiency & Knowledge-Gap Engine

**Mode:** root-cause repair + causal qualification

## Goal

Make the internal-knowledge gate real. Repo Intelligent must be able to determine, **for the specific research question being considered**, whether Performance + Memory already provide enough evidence to answer it.

External research must not happen simply because a generic Memory lookup returned `PARTIAL`, and a test must not appear to prove this behavior merely because privacy independently blocked export.

## Ownership

- Memory remains canonical owner of durable knowledge.
- Performance remains canonical owner of development-history evidence.
- Repo Intelligent may derive a project-scoped sufficiency decision from bounded reads through supported contracts.
- Sufficiency is a routing decision, not a new Memory record.

## Required investigation

Inspect current implementations of:

- Memory bridge/query contracts;
- `_memory_answer_status` or equivalent;
- `question_compiler.py`;
- internal-answer status enum/contract;
- research-question lifecycle;
- privacy/export gate;
- external discovery gate;
- E2E tests that claim Memory sufficiency skips external research.

Reproduce the current behavior with privacy export explicitly enabled.

## Required status model

A per-question decision must support at least:

- `ABSENT` — no usable internal evidence;
- `PARTIAL` — relevant evidence exists but material question dimensions remain unresolved;
- `SUFFICIENT` — internal evidence satisfies the bounded answer contract strongly enough that external research has no justified expected value;
- `STALE` — evidence was once relevant but freshness requirements are not met;
- `CONTRADICTED` — internal evidence materially conflicts and requires resolution/escalation;
- `UNKNOWN` — the gate cannot evaluate reliably.

Do not map "records exist" directly to sufficiency.

## Sufficiency dimensions

Derive the decision from explicit dimensions appropriate to the question type, for example:

- semantic/structural relevance;
- evidence coverage of requested entities/components;
- provenance quality;
- recency/freshness;
- contradiction status;
- confidence/claim kind;
- verification/outcome support;
- whether the question explicitly requests current external comparison.

The decision must explain which dimensions passed or failed.

## Cheap-first decision policy

Use deterministic retrieval and scoring first. A lightweight classifier may later predict sufficiency, but in this execution the deterministic qualification contract must work without ML or LLM access.

Any future learned sufficiency predictor must be allowed to abstain and must never override hard privacy, provenance, contradiction, or freshness rules.

## Counterfactual relevance gate

External research is allowed only when at least one is true:

- internal status is `ABSENT`, `PARTIAL`, `STALE`, `CONTRADICTED`, or `UNKNOWN` **and** expected information value is positive;
- freshness/external comparison is explicitly part of the user's request;
- the user explicitly requested external research.

`SUFFICIENT` must suppress external work unless explicit user intent requires it.

## Causal qualification requirement

Repair tests so each gate is isolated.

At minimum prove:

1. with `allow_export=True`, external provider configured, sufficient Memory evidence, and no explicit external request -> **zero external calls because of sufficiency**;
2. with the same setup but `PARTIAL` evidence -> external research may run;
3. with sufficient evidence but stale freshness -> appropriate stale behavior;
4. with sufficient evidence but privacy export disabled -> zero external calls with reason `PRIVACY_DENIED`, not `INTERNAL_SUFFICIENT`;
5. with contradictory internal evidence -> do not silently mark sufficient;
6. no Memory bridge -> deterministic degradation with explicit `ABSENT/UNAVAILABLE` diagnostics.

The test harness must expose which gate caused the stop.

## Performance interaction

Internal sufficiency must be able to incorporate relevant Performance lineage when the question concerns project history, recurring friction, changed behavior, verification, recommendation outcomes, or user work patterns.

Do not ask Memory to answer questions that Performance canonically owns as current development history.

## Final report

Return:

- `GOAL: YES | PARTIAL | NO`
- old failure reproduced
- new sufficiency contract
- causal gate diagnostics
- tests with privacy export enabled
- external-call counts for sufficient vs partial cases
- Memory and Performance boundaries preserved
- unresolved question classes

Do not report success unless `SUFFICIENT` is produced by a real per-question path and independently prevents avoidable external work.