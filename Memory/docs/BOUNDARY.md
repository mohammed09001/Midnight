# Midnight Memory — Frozen Product Boundary (v1.26.0)

Contract version: **1.26.0** (`MEMORY_ENGINE_CONTRACT_VERSION`, `src/contracts/version.ts`).
This document freezes the Memory Engine product boundary. The code enforces it;
this document is the canonical statement of it. Versioning: additive changes
bump minor, breaking changes bump major.

## 0. Canonical Ownership Statement

Memory is the **canonical owner of durable, accepted, cross-session/project
knowledge**: MemoryRecords and their evidence, provenance, authority tier,
epistemic class, temporal validity, contradiction/supersession lineage, and
retention state — all admitted and retained only under Memory's own evidence,
authority, privacy, temporal, contradiction, supersession, retention, and
promotion rules (docs/AUTHORITY.md, docs/INTAKE.md, docs/PROMOTION.md).

Memory explicitly does **not** own raw Performance evidence or generic agent
execution history. Prompt runs, agent runs, tool/command observations,
repository changes, verification results, feedback, outcomes, Performance
Episodes, and agent transcripts remain canonical to Midnight Performance's own
evidence ledger. Memory only ever holds bounded, evidence-backed **lessons**
derived from that history, referencing the originating Performance evidence
by id — never a copy of the raw evidence itself (docs/PERFORMANCE.md). The
full missing/malformed/expired/duplicated/inaccessible/retired evidence-
reference behavior matrix is frozen in docs/EVIDENCE_REFERENCES.md.

## 1. What the Memory Engine IS

- The **canonical owner of durable Midnight knowledge**: validated MemoryRecords
  (statements with provenance, scope, epistemic class, confidence, temporal
  validity, privacy class), MemoryCandidates, contradiction groups, and
  supersession chains.
- The **only** canonical persistent state of the Memory Engine is the SQLite
  store (`data/memory-engine.db` by default, WAL mode, versioned migrations).
  Records keep immutable revision rows; the record row points at the current
  revision.
- A **versioned contract surface**: `MemoryEngine` API (`src/engine/memoryEngine.ts`),
  the eight named inter-engine operations dispatched through the versioned
  envelope (`memory.search/get/propose/promote/revise/related/history/explain`,
  docs/CONTRACTS.md), engine events (`memory.*`), and the CLI
  (`src/cli/cli.ts`). Sibling engines and tool surfaces interact only through
  these — **no caller may read the Memory store directly** (`MemoryStore` is
  not exported from `src/index.ts`).
- **Typed Memory relationships** (docs/RELATIONS.md): a bounded relation
  vocabulary (`related | depends_on | supports | contradicts | derived_from |
  applies_to | learned_from`) with **provenance** on every relation, and a
  derived **entity projection** (docs/ENTITIES.md) over `applies_to`
  `entity:<kind>:<name>` links — a rebuildable, versioned projection, never
  canonical truth.
- **Optional semantic embedding projection** (docs/EMBEDDINGS.md): provider-
  neutral embeddings behind an interface and a privacy gate. OPTIONAL —
  Memory fully functions without embeddings. Provider/model/version recorded,
  completely rebuildable, derived tables only (never canonical truth).
- **Optional relationship-graph projection** (docs/GRAPH.md): Memory
  relationships projected into a graph (records/entities/external refs as
  nodes; typed relations, supersession chains, contradiction membership as
  edges) for traversal/history experiments — a DERIVED, rebuildable
  projection, never a canonical graph database.
- **Hybrid retrieval + index recovery** (docs/RETRIEVAL.md Task 25,
  docs/PROJECTIONS.md Task 26): hybrid lexical + semantic + relation
  retrieval with retrieval-path explanations (semantic fused only after the
  deterministic baseline, optionally), and unified index rebuild / corruption
  recovery proving derived projections never corrupt Memory truth.
- **Producer integration — Performance → Memory proposals**
  (docs/PERFORMANCE.md): bounded, evidence-backed Performance lessons enter
  the candidate intake stream through the versioned contract
  (`memory.performance.propose`); Performance records stay EXTERNAL
  (referenced by evidenceRef engine `"performance"`), never embedded.
- **Producer integration — Study → Memory proposals** (docs/STUDY.md):
  verified Study findings and user annotations become Memory candidates with
  Study/version/source-revision provenance through
  `memory.study.propose`; Study records stay EXTERNAL (referenced by
  evidenceRef engine `"study_document"`), never embedded.
- **Producer integration — Analysis → Memory proposals** (docs/ANALYSIS.md):
  reusable architectural findings are proposed ONLY as evidence-linked
  candidates through `memory.analysis.propose`; Analysis records stay
  EXTERNAL (referenced by evidenceRef engine `"analysis"`), never embedded,
  and findings are never direct inserts.
- **Consumer integration — Search → Memory history** (docs/SEARCH_HISTORY.md):
  search intent/session history is stored as retrieval context
  (`memory.search.session`) WITHOUT promoting candidate repositories as
  durable knowledge; results and candidates are recorded by reference only.
- **Consumer integration — Context → Memory retrieval** (docs/CONTEXT.md):
  a bounded context-oriented query (`memory.context`) with explicit
  size/time/project filters and provenance-rich results; Memory returns
  bounded, provenance-attributable records for the Context Engine to
  assemble — it never assembles packs itself.
- **Project user notes** (docs/USER_NOTES.md): explicit user-authored
  notes/decisions are FIRST-CLASS memory records with stronger subjective
  authority (`user_decision` tier) within their declared scope; the producing
  actor must be human (agents/engines use the candidate pipeline).
- **Terminal & tool surface + permissions** (docs/TOOLS.md,
  docs/PERMISSIONS.md): a complete Memory CLI with stable JSON output; MCP /
  host-native Memory read tools (mutations separately permissioned); and
  explicit per-scope mutation authorization with actor + origin logging.
- **Context-safe memory excerpts** (docs/EXCERPTS.md): bounded excerpts /
  structured facts for Context Packs that never leak restricted source
  payloads (sensitive records excluded/redacted by default; evidence by
  reference only).
- **Field-level privacy & project isolation** (docs/PRIVACY.md): per-scope
  content-class policy (export restrictions applied to excerpts and derived
  indexes), strict project isolation (read/query requires a scope), and an
  immutable local/self-hosted default.
- **Untrusted-content boundaries, backup, and health** (docs/TRUST.md,
  docs/BACKUP.md, docs/HEALTH.md): stored content is DATA (never policy);
  canonical backup/restore/integrity with checksums and foreign-reference
  verification; and operational health + retrieval-quality instrumentation.
- An **authority model** (docs/AUTHORITY.md): provenance source kinds and
  authority tiers; agent-generated summaries are structurally capped and can
  never ground `observed` records, regardless of fluency.
- An **authorized candidate intake pipeline** (docs/INTAKE.md): proposals
  enter a candidate stream with producer, reason, caller, evidence and
  requested scope — never directly into durable knowledge; per-scope
  allowlist authorization.
- **Deterministic promotion policies** (docs/PROMOTION.md): explicit user
  decision, verified study fact, repeated evidence-backed lesson; agents can
  propose but can never promote.
- **Append-oriented persistence** (docs/PERSISTENCE.md): idempotent writes,
  immutable revision log as truth with rebuildable projections, transactions,
  restart-safe migrations.
- **Contradiction handling** (docs/CONTRADICTIONS.md): deterministic
  detection of incompatible claims (same subject, different content,
  overlapping time), grouping that preserves BOTH claims, and attributed
  resolution (user/policy — agents refused).
- **Non-destructive supersession** (docs/SUPERSESSION.md) with explicit
  required reasons, and **revision/correction semantics**
  (docs/REVISIONS.md) where historical provenance is never mutated.
- **Retention, archival, and deletion semantics** (docs/RETENTION.md):
  active/archived/tombstone states, privacy-driven hard purge as the only
  true deletion, project deletion propagation with identity retirement, and
  source-evidence expiry that degrades verifiability without silently
  invalidating records.
- **Deterministic retrieval baseline** (docs/RETRIEVAL.md): structured
  filters (project, kind, subject, source engine, tags, validity,
  confidence, actor, time), BM25 lexical search over a **rebuildable FTS5
  derived index** with exact-term explanations and diagnostics, temporal
  retrieval (current / as-of / timeline), **provenance-aware ranking**
  (authority/directness/currency — low-confidence and contradicted records
  exposed, never hidden), **deduplication and near-duplicate handling**
  (exact hash + token/Jaccard; duplicates distinguished from independently
  corroborating evidence), **explainable multi-signal fusion** (lexical +
  structured + temporal + provenance + relation with visible per-signal
  contributions), **retrieval traces** (`memory.search`/`memory.current`
  return which filters applied and why each record matched), and an
  **enriched `memory.explain`** (validity at a chosen instant, contradiction
  status, and evidence gaps). Zero embedding/LLM provider dependency.
- **Bi-temporal validity** (docs/TEMPORAL.md): valid time (`observedAt`,
  `validFrom`/`validUntil`) separated from transaction time
  (`createdAt`/`revisedAt`, `supersededAt`), with current/historical queries
  that never overwrite the past.

## 2. What the Memory Engine is NOT (explicit non-goals)

Memory is explicitly **not**:

- **A Performance ledger** — Performance's evidence ledger (prompt runs, agent
  runs, tool/command observations, verification, feedback, outcomes,
  Episodes) is canonical to Performance alone (Section 0); Memory holds only
  bounded, evidence-backed lessons referencing it by id.
- **A raw transcript store** — agent transcripts, prompts, model outputs,
  diffs, and command output are never copied into Memory; source evidence is
  owned by source engines (Repository_Sync, Study_Document, Performance, …)
  and stored **by reference only** (`{engine, ref, note?}`); unknown fields in
  evidence refs are rejected, so payload bodies cannot be embedded.
- **A context-pack assembler** — packs are assembled downstream by the
  Context Engine from Memory records via the versioned API; Memory never
  assembles packs itself.
- **A vector database** — the semantic embedding projection (docs/EMBEDDINGS.md)
  is a derived, rebuildable artifact computed on demand from canonical
  records; it never becomes canonical truth, and Memory functions fully
  without it.
- **A graph database** — the relationship-graph projection (docs/GRAPH.md)
  and the entity projection (docs/ENTITIES.md) are likewise derived,
  rebuildable artifacts, never canonical truth. All three projections'
  integrity is checkable and repairable without ever touching canonical
  truth (docs/PROJECTIONS.md); a corrupted projection is rebuilt from
  canonical records, never treated as a source of truth in its own right. If
  a future derived store is built, it must be rebuildable from this store and
  must never become canonical truth.
- **An agent orchestrator** — Memory never dispatches, sequences, or manages
  agent/tool execution; it has no concept of an agent run or session
  lifecycle beyond the actor attribution on its own records (Section 5).
  Orchestration is out of scope for every surface (API, CLI, MCP tools).
- **A generic cache** — no cache semantics, no TTL-based truth, no silent
  expiry of truth; retention/expiry is an explicit, attributed policy
  (docs/RETENTION.md), never an implementation-detail eviction.
- **A sibling-database reader** — Memory never reads Performance's, Study's,
  or any other sibling engine's private store directly (Section 3); it holds
  only stable references and calls sibling engines, when it calls them at
  all, through their own versioned surfaces — never their storage.
- **Repository truth, Studies, or Performance records** — owned by their
  source engines (see Section 0's canonical ownership statement for the
  Performance boundary specifically). Memory records may *reference* them.

## 3. Interaction rules (Engine Isolation Invariants)

- Sibling engines call Memory only through the versioned API/events — never by
  reading the SQLite file or another engine's private store. Memory likewise
  never reads sibling stores; it holds references.
- Events (`engine_events` table + `events` CLI command) carry **references and
  metadata only — never content bodies** — so sensitive content stays in the
  record store under its privacy class.
- Epistemic discipline: `observed | derived | inferred | recommendation | unknown`
  remain distinguishable on every record. Event/derivation provenance is kept
  in `provenance` (actor, method, capturedAt, derivedFrom).
- Stable identities (record ids, scope ids, actors) are **contracts, not
  permission to bypass APIs** (see `docs/IDENTITIES.md`).

## 4. Failure and degraded behavior

- **No silent in-memory fallback.** Store open/migration failures surface as
  typed errors (`MEMORY_STORE_UNAVAILABLE`, `MEMORY_MIGRATION_FAILED`) with
  machine-readable codes; CLI exits non-zero with `{error:{code,message}}`.
- `doctor` reports health (journal mode, `PRAGMA integrity_check`, applied
  migrations, event count) without throwing — degraded state is observable.
- Privacy: `privacyClass: "secret"` is **refused before any write**
  (`MEMORY_PRIVACY_VIOLATION`). Secrets belong to the secure credential layer.
- Validation failures (`MEMORY_VALIDATION_FAILED`), stale-state conflicts
  (`MEMORY_CONFLICT`), and missing identities (`MEMORY_NOT_FOUND`) are typed.

## 5. Agent neutrality and game independence

- Actors are generic `{kind: human|agent|engine|tool, name, agentType?}`. No
  agent product is hard-coded anywhere in the engine.
- The engine is fully usable from terminal/tool surfaces (`npm run cli -- …`).
  No game client is required for any backend behavior.

## 6. Boundary change policy

Any change to the API surface, event vocabulary, canonical schema fields, or
identity rules requires a contract version bump and an update to this document
plus `docs/SCHEMA.md` / `docs/IDENTITIES.md`.

`package.json`'s `"version"` field is deliberately left at pre-1.0 (`0.1.0`)
and does not track `MEMORY_ENGINE_CONTRACT_VERSION`: the package is
`"private": true` and unpublished, so its version tracks packaging maturity,
not the public API contract. `MEMORY_ENGINE_CONTRACT_VERSION` remains the
sole authoritative surface-versioning signal.
