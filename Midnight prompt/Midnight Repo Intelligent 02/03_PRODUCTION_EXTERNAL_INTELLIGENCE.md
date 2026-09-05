# MIDNIGHT REPO INTELLIGENT 02 — EXECUTION 03

## Production External Intelligence Engine

**Mode:** wire real providers + preserve trust boundaries + bounded research

## Goal

Make external intelligence a real production capability rather than a fixture-only architecture, while keeping it optional, privacy-bounded, provider-neutral, and strictly downstream of an established internal knowledge gap.

## Repository-first investigation

Inspect:

- current external discovery/fetch ports;
- `repo_intelligence_adapters.py` production providers;
- discovery, fetch/parse, source normalization, security, provenance, and synthesis modules;
- privacy/export policy;
- cost/budget meter;
- current GitHub/search/web integrations if any;
- tests that currently use fake or fixture providers.

Do not assume a new provider is needed if the repository already contains a compatible adapter.

## Provider-neutral architecture

Define capability contracts, not vendor contracts.

Minimum capabilities:

- `search_external(query, source_classes, budget, authorization)`
- `fetch_external(source_ref, budget, authorization)`
- `normalize_external(raw_source)`
- `verify_external(normalized_source)`

Provider adapters may represent GitHub, official documentation search, papers, standards, or general web search. The user or deployment policy must remain able to choose providers.

## Required research flow

External work may begin only after:

1. a valid project learning pressure or explicit user request exists;
2. a concrete research question exists;
3. internal sufficiency has been evaluated;
4. privacy/export policy approves the minimum outbound query;
5. budget policy approves the request.

Then:

`abstract query -> search -> rank candidates -> fetch minimum needed -> normalize -> hostile-content screening -> provenance capture -> evidence verification -> synthesis`

## Privacy minimization

Queries sent externally must prefer abstracted technical concepts over private project identifiers.

Never export by default:

- source code;
- secrets;
- raw prompts/transcripts;
- private repository names or proprietary entity names when abstraction is sufficient;
- Memory record content outside explicit policy.

Record the transformed outbound query and the policy decision so behavior is auditable.

## External text is inert evidence

README text, issues, papers, websites, repository files, comments, and generated text are untrusted content.

Prove that external content cannot:

- alter tool policy;
- request secrets;
- cause additional fetches outside the research plan;
- become executable agent instructions;
- bypass project scope;
- elevate its own trust class.

## Bounded discovery

Implement hard limits for:

- search requests;
- fetched documents;
- bytes/content size;
- retries;
- elapsed time;
- per-source-class budget;
- total job cost.

Use early stopping when marginal evidence gain becomes low or internal answer confidence reaches the required threshold.

## Cache strategy

Use separate semantics for:

- exact content-addressed cache;
- normalized-source cache with freshness/ETag/hash semantics where available;
- search-result cache;
- semantic reuse candidates.

Semantic similarity must never be treated as exact equivalence. A semantically reused result must preserve source/freshness constraints and can be rejected when entity, version, or time scope differs.

## Real-production qualification

At least one production-capable external provider path must be proven in an integration test or controlled qualification environment. If credentials/network access are unavailable in CI, use a contract test plus an opt-in live qualification command and report the live test status separately.

Do not claim production external intelligence merely because fake adapters pass.

## Final report

Return:

- `GOAL: YES | PARTIAL | NO`
- production-capable external adapters wired
- outbound-data minimization rules
- real vs fixture qualification status
- prompt-injection/adversarial test result
- cost/request limits
- cache behavior
- unsupported source classes
- exact reason if live external qualification remains unavailable

Core Repo Intelligent operation must remain usable when every external provider is disabled.