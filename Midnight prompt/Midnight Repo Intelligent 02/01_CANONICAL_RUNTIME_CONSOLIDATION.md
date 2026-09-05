# MIDNIGHT REPO INTELLIGENT 02 — EXECUTION 01

## Canonical Runtime Consolidation

**Mode:** investigate -> repair -> delete duplicates -> verify

## Goal

Turn the current Repo Intelligent implementation from a collection of capable modules into **one canonical production runtime** with one authoritative stage sequence and explicit ownership at every decision point.

Do not add features in this execution unless they are strictly required to connect existing capabilities.

## Repository-first investigation

Before editing, inspect the current implementations and tests for:

- `repo_intelligence_pipeline.py`
- `repo_intelligence_bridge.py`
- `repo_intelligence_store.py`
- `repo_intelligence_adapters.py`
- `learning_loop.py`
- `cost_quality.py`
- `federated_retrieval.py`
- `observability.py`
- `repo_intelligence_fusion.py`
- `attention.py`
- `terminal_learning.py`
- `analogy.py`
- `project_graph.py`
- relevant Performance query/read APIs and Memory bridge contracts

Build a machine-readable stage inventory:

`stage -> existing owner -> production caller -> persistence -> telemetry -> tests -> duplicate/unused path -> status`

Status is one of:

- `CANONICAL`
- `LIBRARY_ONLY`
- `DUPLICATE`
- `DEFERRED`
- `BROKEN`

## Required canonical flow

The production path must have one explicit orchestrated sequence equivalent to:

`OBSERVE -> DETECT SIGNAL -> COMPUTE LEARNING PRESSURE -> CHECK INTERNAL SUFFICIENCY -> PLAN RETRIEVAL -> ROUTE CHEAPEST QUALIFIED RESOLVER -> OPTIONAL EXTERNAL DISCOVERY -> VERIFY EVIDENCE -> SYNTHESIZE -> GRAPH/FUSION -> ATTENTION RANK -> EXPOSE -> RECORD OUTCOME -> LEARN`

Not every stage must execute on every run, but every skip must be explicit and observable.

## Required repairs

- Make one function/service the canonical orchestrator.
- Remove or deprecate alternate orchestration paths that can produce materially different decisions.
- Ensure all public entry points call the canonical orchestrator or an explicitly read-only query surface.
- Ensure stage outputs are typed and versioned where cross-module boundaries exist.
- Add explicit stop/skip reasons for every expensive stage.
- Add explicit Performance evidence coverage semantics; do not silently assume a fixed `limit=100` is complete.
- Use pagination or bounded window coverage with diagnostics showing truncation when hard limits apply.
- Ensure failures distinguish policy denial, absence, insufficiency, provider unavailable, budget stop, stale state, and internal error.
- Ensure a pipeline replay with identical immutable evidence is idempotent.

## Continuous-learning integration decision

Inspect whether `ContinuousLearningLoop` truly drives runtime work or only exists as an in-process utility.

Choose one of two valid outcomes:

1. wire it as the bounded durable scheduler/checkpoint owner for the canonical runtime; or
2. formally classify continuous background execution as deferred, remove misleading production claims, and keep explicit user-pull execution only.

Do not leave an ambiguous middle state.

## Duplicate-code rule

If old and new ranking/routing/retrieval paths overlap, do not keep both "for safety" unless there is a proven compatibility need. Prefer migration adapters with deprecation tests, then delete dead ownership.

## Verification

Add tests proving:

- every production entry point reaches the same canonical orchestration contract;
- duplicate stage owners cannot both decide the same concern;
- pipeline coverage reports truncated Performance evidence rather than silently treating it as complete;
- idempotent replay does not duplicate project-intelligence state;
- disabled optional providers do not break deterministic/local operation;
- a failed stage produces an explicit skip/failure reason and does not become a false success.

## Final report

Return:

- `GOAL: YES | PARTIAL | NO`
- stage inventory before/after
- duplicate paths removed or retained with reason
- canonical orchestrator name/path
- Performance evidence coverage semantics
- continuous-loop decision
- tests executed and actual results
- remaining disconnected modules
- exact blocker if not `YES`

Do not claim consolidation if any user-visible decision still has two competing production owners.