# MIDNIGHT REPO INTELLIGENT 02 — EXECUTION 08

## Integrated Qualification & Economics Gate

**Mode:** fresh-checkout proof, adversarial qualification, measured economics

## Goal

Prove that Repo Intelligent 02 is not merely architecturally plausible but operationally integrated, privacy-safe, provider-neutral, and economically better than the pre-02 baseline without sacrificing required quality.

This execution adds no product features unless a qualification failure reveals a blocking defect that must be repaired.

## Baseline capture

Before changing qualification infrastructure, capture the current baseline from repository evidence:

- Performance test command/results;
- Memory test command/results;
- Repo Intelligent focused tests;
- Desktop/typecheck/tests;
- supported OS/runtime matrix;
- external-provider qualification state;
- existing cost/latency metrics where available;
- current model invocation counts for representative workloads.

Do not fabricate missing historical baselines. Mark them `UNKNOWN` and create a reproducible new baseline.

## Required cross-engine qualification

From a fresh checkout, qualification must cover:

- Performance;
- Memory;
- Repo Intelligent;
- Desktop integration/query surfaces;
- supported Python/Node/runtime assumptions;
- Windows, macOS, and Linux where the repository claims cross-platform support.

CI should exercise Memory as part of the same integrated qualification strategy rather than leaving it outside the matrix.

## End-to-end scenarios

At minimum qualify these scenarios:

### A. Internal-only success

- Performance evidence exists;
- a project question is compiled;
- Memory is sufficient;
- privacy export is enabled so it cannot mask behavior;
- external provider is available;
- external call count remains zero specifically because internal sufficiency is `SUFFICIENT`.

### B. Genuine external escalation

- internal status is insufficient/stale;
- policy permits export;
- budget permits work;
- a real production-capable adapter path is exercised when credentials/environment allow;
- returned content is treated as untrusted evidence;
- synthesis retains source lineage.

### C. Privacy denial

- external work would otherwise be useful;
- privacy denies export;
- no outbound call occurs;
- reason is `PRIVACY_DENIED`, not a false internal-sufficiency result.

### D. Learned-router abstention

- lightweight model/router is uncertain;
- it abstains;
- deterministic/deeper path takes over;
- user-visible result remains bounded and qualified.

### E. Drift rollback

- simulated/recorded drift degrades the learned router;
- production authority is removed;
- deterministic baseline resumes;
- no canonical evidence is lost.

### F. Duplicate-event replay

- same Performance/project event is delivered twice;
- canonical pipeline remains idempotent;
- learned outcome update occurs at most once when appropriate.

### G. Cross-project isolation

- Project A cannot read, train on, or retrieve Project B private evidence/learned state without explicit future federation policy.

### H. Attention unification

- terminal exposure and query explanation use the same attention decision/score components;
- repeated low-value exposure is suppressed.

### I. Performance evidence coverage

- evidence set exceeds one page/batch;
- pagination/coverage semantics prove no silent `limit=100` completeness assumption;
- truncation, when intentionally bounded, is surfaced.

## Economics experiment

Create representative workload classes such as:

- repeated known project question;
- local structural question;
- Memory-answerable question;
- novel external-comparison question;
- ambiguous question requiring escalation;
- repeated similar external question eligible for cache/reuse;
- low-value candidate that should be suppressed before LLM use.

For each compare pre-02/baseline policy vs 02 policy where reproducible.

Measure:

- deterministic resolution rate;
- cache reuse rate;
- local retrieval resolution rate;
- ML accept/abstain/escalate rate;
- external calls;
- small-model calls;
- strong-model calls;
- input/output tokens or provider-equivalent usage;
- latency;
- compute/network cost;
- qualified-answer/insight rate;
- verification quality;
- attention exposures;
- false suppression / false escalation.

## Quality gate

Cost savings count only if the applicable quality floor is preserved.

Report results by workload class. Do not hide regressions inside aggregate averages.

Acceptable final economic outcomes:

- `VERIFIED BENEFIT` — cost/latency improves at preserved quality;
- `QUALITY BENEFIT` — quality improves within bounded cost;
- `NO VERIFIED BENEFIT YET` — architecture works but the measured optimization is not better;
- `REGRESSION` — 02 is worse and affected adaptive behavior must remain disabled/rolled back.

`NO VERIFIED BENEFIT YET` is a valid engineering result.

## Adversarial qualification

Include tests for:

- prompt injection in external README/web content;
- hostile source requesting secrets/tool execution;
- stale cache incorrectly resembling current answer;
- semantic-cache false match across version/entity boundaries;
- overconfident learned router;
- corrupted learned-state checkpoint;
- unavailable external provider;
- model timeout/rate failure;
- budget exhaustion;
- contradictory Memory records;
- repository rename/move ambiguity;
- cross-project request.

## Dead-code and ownership audit

Before final `YES`, search for:

- orphaned 01 ranking/routing paths;
- unused standalone engines;
- duplicate cost ledgers;
- direct Memory database access;
- duplicate raw Performance history;
- provider-specific branching in core logic;
- test-only production claims;
- comments/docs that still overstate current behavior.

Delete or correct misleading remnants.

## Final report

Return a compact evidence-backed report containing:

- `GOAL: YES | PARTIAL | NO`
- fresh-checkout environment
- exact commands run
- actual pass/fail counts
- cross-platform CI status
- live external qualification status
- scenario A-I results
- adversarial results
- ownership/dead-code audit
- baseline vs 02 economics by workload class
- quality-floor results
- final economic verdict
- features left in shadow mode
- exact unresolved gaps

Repo Intelligent 02 is not complete if tests only prove modules independently. The final proof must exercise the canonical integrated runtime.