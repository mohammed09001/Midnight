# MIDNIGHT WATCH DATA EXECUTION 26 — BUILD STANDALONE WATCH DATA QUALIFICATION + BUILD COMBINED MIDNIGHT WATCH AND FINAL ARCHITECTURE QUALIFICATION

## Execution Identity

- **Execution:** Midnight Watch Data Execution 26
- **Compiled from:** Midnight Watch Data Roadmap O1
- **Roadmap tasks embedded in this prompt:** 67, 68
- **Roadmap phase:** PHASE X — EVALUATION, SCALE, FAILURE RECOVERY, AND RELEASE QUALIFICATION
- **Expected prior baseline:** Tasks 1–66 are expected historical predecessors, not guaranteed implementation truth. Verify them only to the extent necessary for this Execution.
- **Execution order:** Task 67 → Task 68
- **Prompt version:** O1 Execution Pack / New-Midnight Architecture
- **Created:** 28 August 2026
- **Purpose:** Ready-to-run repository execution prompt for Claude Code CLI, Codex CLI, OpenCode CLI, or another repository-capable coding agent.
- **Self-contained:** Yes. The coding agent does not need access to the roadmap document that was used to compile this file.

# PARENT LOOP — EXECUTION GOAL

## Main Goal

Deliver one coherent Midnight Watch Data execution slice spanning Build Standalone Watch Data Qualification; and Build Combined Midnight Watch and Final Architecture Qualification, with each capability integrated, independently verified, and reviewed as one dependency-aware unit.

This Execution is complete only when every Child Loop reaches `YES`, the integrated result survives the Parent Review, and fresh final-state verification supports the full Execution Goal.

## Parent Loop State Machine

`BASELINE → CHILD PLAN → CHILD EXECUTE → CHILD VERIFY → CHILD REVIEW → CHILD GOAL GATE → NEXT CHILD → INTEGRATION REVIEW → FINAL VERIFY → PARENT GOAL GATE → REPORT`

On any material failure:

`FAILURE → ROOT-CAUSE / EVIDENCE REVIEW → REVISED PLAN → REPAIR → RE-VERIFY → RE-REVIEW`

Do not skip forward to create a positive narrative. The loop advances on evidence, not effort.

## EXECUTION CONTRACT — APPLIES TO THE ENTIRE FILE

This file is a **self-contained executable engineering prompt**, not a design essay.

### Source-access rule

The roadmap used to compile this prompt may not be available to the coding agent. **Do not require or assume access to it.** The task requirements needed for execution are embedded below and are authoritative for this Execution.

### Authority and evidence order

1. Explicit user instructions in this file.
2. The task-specific Goal, source requirement, invariants, constraints, and prohibited outcomes embedded in this file.
3. Current repository evidence for implementation reality.
4. Project-local operating documents and skills when present and relevant.
5. External primary documentation only when current protocol/library/provider facts are materially required.

Never let an older document override verified repository reality. Never let repository reality silently erase the intended product requirement; expose the conflict and resolve it deliberately.

### Companion documents

If present in the repository/workspace, read and apply `Prompt Format.md`, `Mode.md` or `Mode(1).md`, `Dead Code.md`, `Bug Hunter.md`, and `How to Report.md`. Use them as companion operating contracts. Do not assume their contents if absent. This prompt remains executable without them.

### No-sycophancy rule

Do not praise the user, roadmap, repository, architecture, prior implementation, or your own work. Agreement is not evidence.

### Anti-hallucination rule

Do not invent files, functions, APIs, schemas, dependencies, tests, commands, runtime behavior, compatibility, security, performance, or completion. Keep `UNKNOWN` as `UNKNOWN` until evidence resolves it. Static inspection does not prove runtime behavior. A passing test proves only the assertions exercised by that run.

### Repository-first and anti-accumulation rule

Before creating a material new owner, service, store, handler, adapter, execution path, state authority, schema, abstraction, or compatibility wrapper:

- locate the current canonical owner;
- search for existing, partial, legacy, duplicate, or superseded implementations and their consumers;
- prefer reuse, repair, extension, or verified replacement over parallel implementation;
- if replacement is necessary, migrate valid consumers and remove superseded code when safe;
- search residual references after migration;
- do not retain dead or duplicate code “just in case” without a verified compatibility requirement;
- do not perform unrelated repository-wide cleanup.

### Preserve user work

Before material edits, inspect repository/worktree state and preserve unrelated user changes. Never use destructive cleanup merely to obtain a clean tree. Do not overwrite overlapping uncommitted user work.

### Continuous execution rule

Execute this file from start to finish without routine user checkpoints. Resolve questions from repository evidence, tests, project documentation, and authoritative external documentation when possible. Ask the user only when a genuine external product decision, credential/authorization requirement, or unsafe irreversible action cannot be resolved safely.

### Cross-agent portability

This prompt must work in Claude Code CLI, Codex CLI, OpenCode CLI, or another repository-capable coding agent. Do not depend on host-specific slash commands. When an explicit Plan mode exists, use it for planning; otherwise perform the same planning discipline in the current session.

### Review strategy

After each Task, perform two distinct reviews:

1. **Goal/Spec Review** — compare implementation and evidence against the embedded Task requirement, invariants, non-goals, and prohibited outcomes.
2. **Engineering Review** — inspect the actual diff/architecture for bugs, incorrect assumptions, security/privacy defects, failure/recovery gaps, compatibility problems, performance hazards where relevant, dead/superseded code, duplicate ownership, and insufficient tests.

If fresh-context reviewers/subagents are supported, prefer them for at least one review. Give them the Goal, relevant repository context, diff, and verification evidence—not the implementing agent's conclusions.

### Verification-before-completion rule

No success claim is valid without fresh final-state verification appropriate to the claim. Identify the command, test, runtime reproduction, inspection, measurement, replay, migration, or recovery exercise that proves each material claim; execute it after the final relevant change; inspect actual output/exit status; state only what it proves.

### Current Midnight architecture invariants

- Watch Data owns data architecture and data-runtime truth; Watch Runtime owns application-runtime truth.
- Metadata-first, relationship-first, aggregate-first, redaction-first, read-only-first, least-privilege.
- PostgreSQL first; Supabase PostgreSQL is a first-class deployment profile, not a separate domain model.
- Raw customer rows are not required by default; raw-data access is explicit capability escalation.
- Recommendations are hypotheses until before/after verification proves the outcome.
- No direct sibling-product database reads; use stable references/contracts.
- Relationship graphs are rebuildable projections; GraphRAG is not a core dependency.
- Collector failure must not affect database/application availability and missing capabilities remain explicit.

# PARENT LOOP — BASELINE GATE

Before Child Loop 1:

- Read the real repository and establish the actual Midnight Watch Data baseline.
- Tasks 1–66 are expected historical predecessors, not guaranteed implementation truth. Verify them only to the extent necessary for this Execution.
- Inspect `git status`, branch/worktree state, and preserve unrelated user work.
- Locate the current Watch Data product boundary, database adapters/collectors, evidence ledger, privacy/access contracts, query/schema/runtime domains, Data Memory, and any completed execution work.
- Identify pre-existing build/test/runtime failures that could contaminate verification.
- Search the changed scope for existing implementations before creating new owners.
- If repository reality contradicts the embedded requirement, classify the conflict and choose the smallest architecture-preserving resolution.

### Parent Baseline Questions

- What can the repository prove about the expected baseline, and what is only historical assertion?
- Which current modules are canonical for the responsibilities this Execution extends?
- Which failures or uncommitted changes are pre-existing?
- Which product/evidence/privacy/ownership invariants must remain true across all Child Loops?
- What would make it unsafe or dishonest to continue?

Do not demand user clarification for facts the repository can answer.
---

# CHILD LOOP — TASK 67: Build Standalone Watch Data Qualification

## Task Source Requirement

Prove that Midnight Watch Data can operate without Watch Runtime, Performance, Security, GraphRAG, external AI, or a managed Midnight cloud.

It must independently demonstrate:

- secure PostgreSQL/Supabase connection;
- metadata discovery;
- relationship extraction;
- query identity;
- query/access intelligence;
- time-window runtime analysis;
- plan/index/lock/connection evidence;
- schema change and regression detection;
- cost/growth signals;
- recommendation generation;
- before/after verification;
- Data Memory;
- API/query access;
- backup/recovery.

After completion:

- Watch Data is a real standalone capability rather than an integration feature;
- optional siblings clearly improve value but are not dependencies.

## Objective

Implement **Task 67: Build Standalone Watch Data Qualification** as a coherent repository-native capability. Preserve the exact functional intent embedded above while adapting implementation details to verified repository architecture.

## Final Goal for This Child Loop

An independent reviewer can inspect the final repository and fresh evidence and conclude that **Task 67: Build Standalone Watch Data Qualification** is implemented, integrated with canonical owners, protected against relevant failure cases, and does not leave unjustified duplicate or superseded architecture.

## Phase A — Ground Truth / Context

Before coding:

- inspect the repository/worktree, current branch/state, project instructions, architecture notes, schemas/contracts, tests, and recent implementation around this responsibility;
- verify required predecessor behavior instead of trusting historical reports;
- locate canonical owners, consumers, persistence, public/API boundaries, adapters, migrations, and tests related to this task;
- classify material findings as `VERIFIED`, `OBSERVED`, `INFERRED`, `HYPOTHESIZED`, or `UNKNOWN` when the distinction matters;
- identify pre-existing failures or user changes that could contaminate verification;
- inspect current code before deciding that a new abstraction, dependency, service, database, graph, queue, model, or adapter is necessary.

Do not edit implementation code until there is enough evidence for a defensible plan.

## Phase B — Deep Questions That Must Be Answered

1. What is VERIFIED from the repository now, what comes only from this embedded requirement, what is INFERRED, and what remains UNKNOWN?
2. Who currently owns this responsibility? Is there an existing partial, alternate, legacy, or duplicate implementation to reuse, repair, migrate, or remove?
3. Which assumption would most damage correctness if false, and what evidence can falsify it before implementation?
4. What could appear complete while still compiling or passing narrow happy-path tests?
5. Which trust, identity, persistence, versioning, privacy, compatibility, concurrency, or failure-recovery boundary could this Task accidentally violate?
6. What evidence is required to prove the final claim, and can it be produced against the final implementation state?
7. Are we turning correlation, similarity, absence of evidence, agent prose, scanner prose, model output, or documentation into stronger truth than the evidence supports?
8. What newly introduced complexity can be removed or folded into the canonical owner without weakening the Goal?
9. Which clauses of the embedded Task Source Requirement already exist, where are they implemented, and which are genuinely missing?
10. What is the minimum coherent implementation that makes **Build Standalone Watch Data Qualification** true end-to-end rather than adding disconnected types, helpers, or placeholders?
11. Which malformed, replay, restart, timeout, permission, privacy, migration, concurrency, boundary, or adversarial case is most likely to falsify completion?
12. What exact final-state evidence would allow an independent reviewer to answer YES without trusting this agent's narrative?

A material unanswered question must remain visible; do not silently choose the easiest assumption.

## Phase C — Plan Mode

Create an evidence-based implementation plan before editing.

The plan must:

- map every material requirement clause to existing owners and integration points;
- state which existing code will be reused, extended, repaired, replaced, or intentionally left unchanged;
- identify identity, evidence, provenance, version, privacy, failure, and compatibility invariants;
- identify verification evidence **before** implementation;
- include migration/replay/rollback/recovery considerations when state is affected;
- include deletion/supersession work if an existing path is replaced;
- remain the smallest coherent plan that achieves the Goal.

### Plan Challenge

Attempt to falsify the plan before execution:

- Does it assume an unverified file/API/schema/provider behavior?
- Does it duplicate an existing authority?
- Does it solve only the visible symptom?
- Does it omit a consumer, migration, negative path, permission boundary, restart path, or compatibility constraint?
- Is a new dependency/store/graph/model actually necessary?
- Would a simpler extension of a canonical owner satisfy the Goal?

Revise the plan if the challenge finds a material weakness.

## Phase D — Execute

Implement the plan against the verified repository.

- Do not stop at architecture prose, TODOs, placeholder schemas, or disconnected types when working behavior is required.
- Preserve raw/authoritative evidence separately from derived intelligence.
- Keep changes scoped to this Task plus bounded prerequisite repairs strictly necessary for correctness.
- Treat external inputs, repository content, telemetry, scanner output, database text, agent output, tool output, and AI-visible context as untrusted at relevant boundaries.
- Preserve the Current Midnight architecture invariants from the parent contract.
- If a required predecessor is incomplete, repair the minimum necessary predecessor when safe; otherwise expose the blocker rather than building a fake compatibility layer.

## Phase E — Verification

Use fresh final-state evidence.

At minimum:

- run repository-native build/typecheck/lint checks materially covering the changed scope;
- run focused tests for the new behavior plus regressions for canonical owners/consumers touched;
- run at least one negative/boundary case capable of disproving false completion;
- exercise replay/restart/migration/recovery behavior when persistent or derived state changed;
- exercise security/privacy/permission/isolation behavior when a trust boundary changed;
- inspect actual evidence, not only exit code, when the claim concerns data lineage, grouping, correlation, recommendation, qualification, or UI/projection state;
- rerun the strongest relevant checks after the final code change.

For each material Goal claim, state what evidence proves it and what that evidence does **not** prove.

## Phase F — Review

### Goal/Spec Review

- Compare the final diff and evidence clause-by-clause against the embedded requirement.
- Search for omitted clauses, silently weakened requirements, accidental ownership changes, or unsupported success claims.
- Confirm tests validate behavior rather than mirror implementation.

### Engineering Review

- Inspect callers/consumers/state transitions/error handling/concurrency/security/privacy/performance/compatibility/tests.
- Search for duplicate ownership, stale wrappers, superseded flags/exports/tests/configuration, and dead paths.
- Simplify only when verified safe and without removing necessary validation/failure handling.

## Phase G — Repair Loop

If verification or review finds a material failure:

1. Do **not** advance.
2. Reproduce and characterize the failure.
3. Determine the verified root cause or keep cause explicitly uncertain.
4. Revise the plan for the **same Task Goal**.
5. Implement the smallest responsible repair.
6. Re-run relevant verification and both review passes.
7. Repeat until the Goal passes or a genuine external blocker prevents safe progress.

Do not stack speculative patches. Do not reinterpret a failed requirement as optional merely to advance.

## Phase H — Child Final Goal Gate

Answer exactly:

**HAVE WE ACHIEVED THE FINAL GOAL FOR TASK 67? — YES / PARTIALLY / NO**

Advance only if the answer is `YES` and fresh evidence supports it. If `PARTIALLY` or `NO` because of an irreducible blocker, stop dependent execution, preserve the safest truthful repository state, and carry the evidence into the final report.
---

# CHILD LOOP — TASK 68: Build Combined Midnight Watch and Final Architecture Qualification

## Task Source Requirement

Run Watch Runtime + Watch Data together and prove the umbrella model works without collapsing domain ownership.

The final gate must prove:

- Watch Runtime owns application-runtime truth.
- Watch Data owns data architecture and data-runtime truth.
- shared incidents use references rather than duplicated truth;
- cross-Watch correlation is evidence-backed;
- either capability degrades independently;
- Performance consumes bounded Watch Data evidence without owning it;
- Security integration remains optional and bounded;
- raw customer data is not required for core Watch Data value;
- read-only and least-privilege defaults are enforced;
- recommendations remain hypotheses until verification;
- Memory contains promoted knowledge, not raw telemetry;
- the relationship graph is not GraphRAG and is not canonical storage;
- AI is optional and outside the hot collection path;
- self-hosted/BYOC operation is first-class;
- no current task requires autonomous production database mutation.

After completion, this roadmap reaches its O1 Definition of Done.

---

## Objective

Implement **Task 68: Build Combined Midnight Watch and Final Architecture Qualification** as a coherent repository-native capability. Preserve the exact functional intent embedded above while adapting implementation details to verified repository architecture.

## Final Goal for This Child Loop

An independent reviewer can inspect the final repository and fresh evidence and conclude that **Task 68: Build Combined Midnight Watch and Final Architecture Qualification** is implemented, integrated with canonical owners, protected against relevant failure cases, and does not leave unjustified duplicate or superseded architecture.

## Phase A — Ground Truth / Context

Before coding:

- inspect the repository/worktree, current branch/state, project instructions, architecture notes, schemas/contracts, tests, and recent implementation around this responsibility;
- verify required predecessor behavior instead of trusting historical reports;
- locate canonical owners, consumers, persistence, public/API boundaries, adapters, migrations, and tests related to this task;
- classify material findings as `VERIFIED`, `OBSERVED`, `INFERRED`, `HYPOTHESIZED`, or `UNKNOWN` when the distinction matters;
- identify pre-existing failures or user changes that could contaminate verification;
- inspect current code before deciding that a new abstraction, dependency, service, database, graph, queue, model, or adapter is necessary.

Do not edit implementation code until there is enough evidence for a defensible plan.

## Phase B — Deep Questions That Must Be Answered

1. What is VERIFIED from the repository now, what comes only from this embedded requirement, what is INFERRED, and what remains UNKNOWN?
2. Who currently owns this responsibility? Is there an existing partial, alternate, legacy, or duplicate implementation to reuse, repair, migrate, or remove?
3. Which assumption would most damage correctness if false, and what evidence can falsify it before implementation?
4. What could appear complete while still compiling or passing narrow happy-path tests?
5. Which trust, identity, persistence, versioning, privacy, compatibility, concurrency, or failure-recovery boundary could this Task accidentally violate?
6. What evidence is required to prove the final claim, and can it be produced against the final implementation state?
7. Are we turning correlation, similarity, absence of evidence, agent prose, scanner prose, model output, or documentation into stronger truth than the evidence supports?
8. What newly introduced complexity can be removed or folded into the canonical owner without weakening the Goal?
9. Which clauses of the embedded Task Source Requirement already exist, where are they implemented, and which are genuinely missing?
10. What is the minimum coherent implementation that makes **Build Combined Midnight Watch and Final Architecture Qualification** true end-to-end rather than adding disconnected types, helpers, or placeholders?
11. Which malformed, replay, restart, timeout, permission, privacy, migration, concurrency, boundary, or adversarial case is most likely to falsify completion?
12. What exact final-state evidence would allow an independent reviewer to answer YES without trusting this agent's narrative?

A material unanswered question must remain visible; do not silently choose the easiest assumption.

## Phase C — Plan Mode

Create an evidence-based implementation plan before editing.

The plan must:

- map every material requirement clause to existing owners and integration points;
- state which existing code will be reused, extended, repaired, replaced, or intentionally left unchanged;
- identify identity, evidence, provenance, version, privacy, failure, and compatibility invariants;
- identify verification evidence **before** implementation;
- include migration/replay/rollback/recovery considerations when state is affected;
- include deletion/supersession work if an existing path is replaced;
- remain the smallest coherent plan that achieves the Goal.

### Plan Challenge

Attempt to falsify the plan before execution:

- Does it assume an unverified file/API/schema/provider behavior?
- Does it duplicate an existing authority?
- Does it solve only the visible symptom?
- Does it omit a consumer, migration, negative path, permission boundary, restart path, or compatibility constraint?
- Is a new dependency/store/graph/model actually necessary?
- Would a simpler extension of a canonical owner satisfy the Goal?

Revise the plan if the challenge finds a material weakness.

## Phase D — Execute

Implement the plan against the verified repository.

- Do not stop at architecture prose, TODOs, placeholder schemas, or disconnected types when working behavior is required.
- Preserve raw/authoritative evidence separately from derived intelligence.
- Keep changes scoped to this Task plus bounded prerequisite repairs strictly necessary for correctness.
- Treat external inputs, repository content, telemetry, scanner output, database text, agent output, tool output, and AI-visible context as untrusted at relevant boundaries.
- Preserve the Current Midnight architecture invariants from the parent contract.
- If a required predecessor is incomplete, repair the minimum necessary predecessor when safe; otherwise expose the blocker rather than building a fake compatibility layer.

## Phase E — Verification

Use fresh final-state evidence.

At minimum:

- run repository-native build/typecheck/lint checks materially covering the changed scope;
- run focused tests for the new behavior plus regressions for canonical owners/consumers touched;
- run at least one negative/boundary case capable of disproving false completion;
- exercise replay/restart/migration/recovery behavior when persistent or derived state changed;
- exercise security/privacy/permission/isolation behavior when a trust boundary changed;
- inspect actual evidence, not only exit code, when the claim concerns data lineage, grouping, correlation, recommendation, qualification, or UI/projection state;
- rerun the strongest relevant checks after the final code change.

For each material Goal claim, state what evidence proves it and what that evidence does **not** prove.

## Phase F — Review

### Goal/Spec Review

- Compare the final diff and evidence clause-by-clause against the embedded requirement.
- Search for omitted clauses, silently weakened requirements, accidental ownership changes, or unsupported success claims.
- Confirm tests validate behavior rather than mirror implementation.

### Engineering Review

- Inspect callers/consumers/state transitions/error handling/concurrency/security/privacy/performance/compatibility/tests.
- Search for duplicate ownership, stale wrappers, superseded flags/exports/tests/configuration, and dead paths.
- Simplify only when verified safe and without removing necessary validation/failure handling.

## Phase G — Repair Loop

If verification or review finds a material failure:

1. Do **not** advance.
2. Reproduce and characterize the failure.
3. Determine the verified root cause or keep cause explicitly uncertain.
4. Revise the plan for the **same Task Goal**.
5. Implement the smallest responsible repair.
6. Re-run relevant verification and both review passes.
7. Repeat until the Goal passes or a genuine external blocker prevents safe progress.

Do not stack speculative patches. Do not reinterpret a failed requirement as optional merely to advance.

## Phase H — Child Final Goal Gate

Answer exactly:

**HAVE WE ACHIEVED THE FINAL GOAL FOR TASK 68? — YES / PARTIALLY / NO**

Advance only if the answer is `YES` and fresh evidence supports it. If `PARTIALLY` or `NO` because of an irreducible blocker, stop dependent execution, preserve the safest truthful repository state, and carry the evidence into the final report.
---

# PARENT LOOP — INTEGRATION REVIEW

After all Child Loops reach `YES`:

- inspect the combined diff and resulting architecture as one unit;
- verify that adjacent Tasks integrate through canonical owners rather than parallel paths;
- verify migrations/replay/recovery across the combined state where relevant;
- verify no Task invalidated evidence or assumptions established by another Task;
- search for stale references, duplicate owners, dead code, unused compatibility layers, unnecessary dependencies, and temporary scaffolding;
- run the strongest integrated verification available for this Execution;
- re-check Current Midnight product boundaries and optional-sibling behavior.

## Parent Final Goal Gate

Answer exactly:

**HAVE WE ACHIEVED THE FINAL GOAL FOR THIS EXECUTION? — YES / PARTIALLY / NO**

`YES` requires every Child Goal Gate to be `YES`, integrated review to pass, and fresh final-state evidence to support the Execution Goal.

# FINAL REPORT CONTRACT

Produce a concise but evidence-rich final report containing:

- **Final Status:** YES / PARTIALLY / NO.
- **Execution Goal verdict.**
- **Task-by-task Goal verdicts.**
- **Repository baseline discovered.**
- **What changed:** canonical owners, schemas/contracts, migrations, adapters, integrations, deletions/supersessions.
- **Verification executed:** exact commands/checks and relevant outputs/exit status.
- **Negative/failure/recovery cases exercised.**
- **Architecture/product-boundary review.**
- **Dead-code / duplicate-ownership review.**
- **Known limitations and explicit UNKNOWNs.**
- **External blockers**, if any.
- **Recommended next Execution:** only if this Execution is `YES`, or explain why dependent work must stop.

Do not report completion from effort, file count, or agent narrative. Report only what the final repository and fresh verification prove.
