# Library Memory Engine — Versioned Inter-Engine Contracts (v1.6.0)

Implemented in `src/contracts/operations.ts` (registry), `src/engine/dispatcher.ts`
(single envelope owner), `src/engine/relations.ts` (related/explain),
`src/index.ts` (public module surface).

## The rule

**No caller may read the Memory store directly.** Sibling engines, agents,
and tool surfaces call Memory only through:

1. the versioned contract dispatcher (`dispatch(engine, envelope)`), or
2. the `MemoryEngine` API, or
3. the CLI (`memory-engine contract call …`).

The canonical SQLite store is private to this engine; `MemoryStore` is
deliberately NOT exported from `src/index.ts`, and in deployment the store
file is not shared.

## Envelope

```json
// request
{ "contractVersion": "1.1.0", "operation": "memory.get",
  "request": { "recordId": "mem_…" } }

// response (success)
{ "ok": true,  "contractVersion": "1.1.0", "operation": "memory.get",
  "result":   { "record": { … } } }

// response (failure — never throws)
{ "ok": false, "contractVersion": "1.1.0", "operation": "memory.get",
  "error":    { "code": "MEMORY_NOT_FOUND", "message": "…" } }
```

## Versioning policy

The envelope carries `contractVersion`. A call is accepted while the **major**
matches the engine's contract; additive changes bump minor, breaking changes
bump major and reject callers with `MEMORY_CONTRACT_MISMATCH`.

## The nine operations

| Operation | Request (essentials) | Result |
|---|---|---|
| `memory.search` | `{scope?, subjectContains?, contentContains?, tag?, kind?, status?, asOf?, includeRetracted?, limit?}` | `{records: MemoryRecord[], trace}` — `asOf` switches to historical belief view (docs/TEMPORAL.md); `trace` is 1.6.0 additive (docs/RETRIEVAL.md) |
| `memory.get` | `{recordId}` | `{record}` |
| `memory.propose` | candidate core (scope, kind, subject, content, actor, method, epistemicClass, confidence, sourceKind, evidenceRefs?, tags?) **+ `reason` (required) + `caller` + `idempotencyKey?`** | `{candidate}` — enters the authorized intake stream (docs/INTAKE.md) |
| `memory.promote` | `{candidateId, actor (required), policy?}` | `{record}` — **policy-gated** (docs/PROMOTION.md); agents are refused |
| `memory.revise` | `{recordId, content, actor, reason (all required), method}` | `{record}` — attributed correction, agents refused (docs/REVISIONS.md) |
| `memory.related` | `{recordId, direction?: out\|in\|both}` | `{outgoing, incoming, contradictionGroup}` |
| `memory.history` | `{recordId}` | `{chain, revisions}` — supersession chain (+`supersededReason`) + revision rows |
| `memory.explain` | `{recordId, at?}` | full provenance + **authority assessment** + evidence refs/gaps + validity + contradiction status + lifecycle events *(`at`/gaps/validity/contradiction: 1.6.0 additive)* |
| `memory.candidates` | `{scope?, status?, limit?}` *(1.2.0 additive)* | `{candidates}` — the intake stream, oldest first |
| `memory.contradictions` | `{scope}` *(1.3.0 additive)* | `{pairs, openGroups}` — deterministic detection + pending sets (docs/CONTRADICTIONS.md) |
| `memory.lifecycle` | `{action: archive\|restore\|delete\|purge\|purgeByPrivacy\|deleteScope, actor, reason, …}` *(1.4.0 additive)* | `{record}` / `{purged}` / `{purgedCount, recordIds}` / `{scope}` — retention semantics (docs/RETENTION.md); agents refused |
| `memory.lexical` | `{query, scope?, status?, limit?}` *(1.5.0 additive)* | BM25-ranked hits with per-hit field explanations + query diagnostics (docs/RETRIEVAL.md) |
| `memory.current` | `{scope, subject?, at?, limit?}` *(1.5.0 additive)* | `{records, trace}` — validity-aware current view; `trace` is 1.6.0 additive (docs/RETRIEVAL.md) |
| `memory.timeline` | `{scope, subject}` *(1.5.0 additive)* | `{timeline}` — decision evolution with retirement reasons |
| `memory.ranked` | `{query, scope?, limit?, at?}` *(1.5.0 additive)* | provenance-aware ranked hits with explicit per-record provenance breakdowns (Task 17, docs/RETRIEVAL.md) |
| `memory.duplicates` | `{scope, subject, content, evidenceRefs?}` *(1.5.0 additive)* | `{analysis}` — exact/near-duplicate detection and duplicate-vs-corroboration classification (Task 18) |
| `memory.fused` | `{query, scope?, exactSubject?, tag?, kind?, limit?, at?, weights?}` *(1.5.0 additive)* | explainable multi-signal fusion with visible per-signal contributions (Task 19, docs/RETRIEVAL.md) |
| `memory.relation` | `{action: add\|remove, recordId, type, target, method, actor, note?}` *(1.7.0 additive)* | `{related}` — attributed add/remove of a typed relation with provenance (Task 21, docs/RELATIONS.md) |
| `memory.entities` | `{scope, rebuild?}` *(1.7.0 additive)* | `{projection}` — derived, versioned entity projection (Task 22, docs/ENTITIES.md) |
| `memory.embeddings` | `{scope, action?: status\|build\|rebuild, includeSensitive?}` *(1.8.0 additive)* | `{status}` / `{projection}` — optional, privacy-gated semantic embedding projection (Task 23, docs/EMBEDDINGS.md) |
| `memory.semantic` | `{query, scope?, limit?}` *(1.8.0 additive)* | cosine-ranked semantic search over the built projection (Task 23) |
| `memory.graph` | `{scope, action?: get\|rebuild\|traverse, start?, direction?, relationTypes?, maxDepth?}` *(1.9.0 additive)* | `{projection}` / `{traversal}` — derived relationship-graph projection + bounded traversal (Task 24, docs/GRAPH.md) |
| `memory.hybrid` | `{query, scope?, exactSubject?, tag?, kind?, limit?, at?, weights?}` *(1.10.0 additive)* | hybrid lexical + semantic + relation retrieval with per-signal contributions AND a retrieval-path explanation (Task 25) |
| `memory.projections` | `{scope?, action?: check\|rebuild\|repair, includeSensitive?}` *(1.10.0 additive)* | `{report}` / `{rebuilt, report}` / `{repaired, report}` — unified index integrity, rebuild, and corruption recovery (Task 26) |
| `memory.performance.propose` | `{scope, lessons: PerformanceLesson[], caller?}` *(1.11.0 additive)* | `{accepted, rejected}` — bounded, evidence-backed Performance lessons into the intake stream (Task 27, docs/PERFORMANCE.md) |
| `memory.study.propose` | `{scope, proposals: StudyProposal[], caller?}` *(1.12.0 additive)* | `{accepted, rejected}` — verified Study findings + user annotations into the intake stream with Study/version/source-revision provenance (Task 28, docs/STUDY.md) |
| `memory.analysis.propose` | `{scope, findings: AnalysisFinding[], caller?}` *(1.13.0 additive)* | `{accepted, rejected}` — reusable architectural findings into the intake stream, evidence-linked only (Task 29, docs/ANALYSIS.md) |
| `memory.search.session` | `{action?: record\|list\|get, scope?, intent?, actor?, observedAt?, resultRefs?, candidateRefs?, note?, limit?, searchSessionId?}` *(1.14.0 additive)* | `{session}` / `{sessions}` — search intent/session history as retrieval context (Task 30, docs/SEARCH_HISTORY.md) |
| `memory.context` | `{scope, query?, size?, at?, time?, kinds?, sourceKinds?, minAuthority?, minConfidence?, includeRetracted?}` *(1.15.0 additive)* | `{result}` — bounded context-oriented retrieval with explicit size/time/project filters and provenance-rich results (Task 31, docs/CONTEXT.md) |
| `memory.user.note` | `{scope, subject, content, actor (human), kind?, method?, epistemicClass?, confidence?, tags?, evidenceRefs?, validFrom?, validUntil?, observedAt?, idempotencyKey?}` *(1.16.0 additive)* | `{record}` — explicit user-authored note/decision as a first-class record with stronger subjective authority (Task 32, docs/USER_NOTES.md) |
| `memory.excerpts` | `{action?: pack\|record, scope?, recordId?, maxExcerpts?, maxContentChars?, at?, includeSensitive?, sourceKinds?, kinds?, minConfidence?, minAuthority?}` *(1.18.0 additive)* | `{pack}` / `{excerpt}` — bounded, context-safe memory excerpts for Context Packs (Task 36, docs/EXCERPTS.md) |
| `memory.privacy` | `{action?: status\|setProjectIsolation\|setScopeContentPolicy, mode?, scope?, policy?}` *(1.19.0 additive)* | `{status}` — field-level privacy + project isolation posture (Task 37, docs/PRIVACY.md) |
| `memory.trust` | `{}` *(1.20.0 additive)* | `{status}` — content-trust boundary (stored content is untrusted data, never policy) (Task 38, docs/TRUST.md) |
| `memory.backup` | `{action?: create\|verify\|verifyReferences, bundle?}` *(1.20.0 additive)* | `{bundle}` / `{verified}` / `{report}` — canonical backup (checksum), verification, reference integrity (Task 39, docs/BACKUP.md) |
| `memory.health` | `{}` *(1.20.0 additive)* | `{metrics}` — operational health + retrieval-quality report (Task 40, docs/HEALTH.md) |

## 1.25.0 contract notes (additive)

- Task 46 (Phase VIII — V1 gate): the product-truth gate. `gate run`
  (CLI) / `runProductTruthGate` executes a machine-verifiable audit of the
  eight product-truth clauses — ownership, contracts, standalone operation,
  terminal usability, evidence provenance, privacy, retrieval explanations,
  and future extensibility — with fresh evidence per clause on disposable
  scratch stores (docs/PRODUCT_TRUTH_GATE.md). The gate module stands
  outside the audited public surface (nothing in the engine imports it).
  No new contract-dispatch operations; purely additive, existing callers
  unaffected.

## 1.24.0 contract notes (additive)

- Task 45 (Phase VIII): crash/rebuild/deletion qualification plus deletion
  propagation hardening. `engine.qualifyRecovery` exercises torn stores,
  partial-write repair from the append log, projection corruption and
  rebuild, backup/restore into a fresh store, source-deletion and
  privacy-purge propagation, and scope deletion on disposable scratch
  stores (docs/RECOVERY_QUALIFICATION.md). CLI: `qualify recovery`.
  Behavior hardening in existing owners: tombstone and privacy purge now
  remove the record's derived embedding rows, `memory.semantic` never ranks
  deleted records, and an embedding rebuild removes orphan rows (a purge
  can no longer leave permanent projection corruption). Purely additive to
  the public surface; existing callers unaffected.

## 1.23.0 contract notes (additive)

- Task 43 (Phase VIII — qualification and V1 gate): retrieval evaluation.
  `engine.evaluateRetrieval` measures frozen-judgment precision/recall/MRR
  for exact, lexical, temporal, hybrid-baseline, semantic and
  hybrid-semantic strategies over the qualification corpus, with per-query
  transparent results and a frozen semantic gate (beat-or-complement,
  docs/EVALUATION.md). CLI: `evaluate retrieval`.
- Task 44 (Phase VIII): contradiction/supersession qualification.
  `engine.qualifyContradictionSupersession` proves lineage invariants —
  chain integrity, predecessor immutability, resolution
  non-destructiveness, historical queryability, current-truth resolution,
  and corpus-wide no-destructive-overwrite (docs/LINEAGE_QUALIFICATION.md).
  CLI: `qualify lineage`. No new contract-dispatch operations; purely
  additive, existing callers unaffected.

## 1.22.0 contract notes (additive)

- Task 42 (Phase VIII — qualification and V1 gate): frozen Memory
  qualification corpora. `engine.buildQualificationCorpus` materializes the
  deterministic `qualification-v1` corpus (current/historical facts,
  contradictions, supersession, duplicates, privacy restrictions,
  provenance) through the public API only — replay-safe via idempotency keys
  and a marker record; `engine.verifyQualificationCorpus` freezes expected
  outcomes into a subject-keyed report with stable check names
  (docs/CORPORA.md). New event `memory.corpus.built`. CLI:
  `corpus build|verify`. No new contract-dispatch operations; purely
  additive, existing callers unaffected.

## 1.21.0 contract notes (additive)

- Task 41 (Phase VII — privacy, reliability, operations): graceful degradation
  hardening. A CONFIGURED embedding provider that FAILS at runtime (error or
  contract violation, e.g. wrong vector count) now surfaces as the stable
  typed code `MEMORY_EMBEDDINGS_UNAVAILABLE` (original error preserved as
  `cause`) instead of an untyped provider exception; hybrid retrieval
  (`memory.hybrid`) degrades the semantic signal (path reason explains it)
  and always keeps the deterministic lexical baseline; corrupt derived vector
  rows are skipped during `memory.semantic` ranking and reported via the new
  additive `diagnostics.skippedCorrupt` field (restored by the next
  embedding rebuild). Structured/lexical Memory works with embeddings
  absent, failing, or corrupt (docs/EMBEDDINGS.md, docs/PROJECTIONS.md).
- Purely additive; existing callers unaffected.

## 1.20.0 contract notes (additive)

- Task 38 (prompt-injection / untrusted-content boundaries): stored external
  text is treated as DATA — `memory.trust` reports the boundary; retrieved
  content carries `trust: "untrusted-data"`; policy surfaces (promotion,
  mutation, intake, export) read structural fields only and never interpret
  content text.
- Task 39 (backup/restore/integrity): `memory.backup` exports canonical Memory
  + projection-rebuild metadata as a checksummed JSON bundle; `verify`
  detects tampering/structural errors; `verifyReferences` checks canonical
  foreign references. Restore is a full snapshot into a fresh store (via the
  engine API / CLI, not a contract op).
- Task 40 (health): `memory.health` measures intake/promotion/rejection,
  stale/contradicted records, missing evidence, index freshness, rebuild
  health, and a sampled retrieval latency.
- Purely additive; existing callers unaffected.

## 1.19.0 contract notes (additive)

- Task 37 (Phase VII — privacy, reliability, operations): field-level privacy and
  project isolation.
  - **Content-class policy (per scope)**: `exportable` classes (default
    `public`+`internal`) and `forbidSensitive` control what may be
    exported/excerpted/embedded — applied to the excerpt and embedding
    (derived index) gates.
  - **Project isolation**: default `strict` — read/query surfaces
    (`memory.search`, `memory.lexical`, `memory.semantic`, as-of) require a
    `scope`; `setProjectIsolation open` allows cross-project queries.
  - **Export restrictions** and **local/self-hosted defaults**: the engine is
    immutable `selfHosted: true` (zero external calls), surfaced via
    `memory.privacy {action: status}`.
- Purely additive; existing callers unaffected under the default strict
  posture as long as they pass a scope (the established convention).

## 1.18.0 contract notes (additive)

- Task 36 (Phase VI — Context-safe memory excerpts): `memory.excerpts` returns
  BOUNDED excerpts / structured facts suitable for Context Packs WITHOUT
  leaking restricted source payloads. `pack` caps `maxExcerpts` (1–100) and
  bounds each excerpt's content (`maxContentChars`, ellipsized + `truncated`);
  `record` returns a single record excerpt. Privacy gate: `sensitive` records
  are EXCLUDED by default (`skippedSensitive` reported; `includeSensitive`
  opt-in); a single sensitive excerpt is REDACTED (`[sensitive content
  excluded]`) unless opted in; evidence payloads are never included (by
  reference only); tombstoned records are refused. Purely additive.

## 1.17.0 contract notes (additive)

- Phase VI (terminal / tool surface / permissions): the Memory CLI (Task 33)
  now covers search/get/history/related/propose/promote/revise/contradictions/
  health with stable JSON output. MCP / host-native Memory read tools (Task 34)
  expose authorized read/query tools; MUTATION tools are separately
  permissioned (only listed when the host opts in) and flow through the
  mutation authorization surface (Task 35). New error code
  `MEMORY_MUTATION_FORBIDDEN`: under a `restricted` scope mutation policy,
  promote/revise/delete (and other mutations) require an explicit
  project/user policy — an unlisted actor (including an agent) is refused.
  Mutation events log `actor` AND `origin` (cli/contract/mcp/host).
- Purely additive; existing callers unaffected (default mutation policy is
  `open` = prior structural rules).

## 1.16.0 contract notes (additive)

- Task 32 (Phase V — Project user notes): `memory.user.note` models EXPLICIT
  USER-AUTHORED notes and decisions as FIRST-CLASS memory records (the user is
  the authority — no candidate gate, no promotion). The producing actor MUST
  be `human` (agents/engines use `memory.propose`). A user DECISION carries the
  new `user_decision` source kind → `user_decision` authority tier (STRONGER
  subjective authority — above `user_reported`, below `verified_source`); a
  note carries `user_note` → `user_reported`. Both are scoped to the declared
  project. Default `epistemicClass derived` (no external evidence required);
  `observed` still requires evidence refs per the authority model.
- Purely additive; existing callers unaffected.

## 1.15.0 contract notes (additive)

- Task 31 (Phase V — Context → Memory retrieval): `memory.context` gives the
  Context Engine a BOUNDED context-oriented query surface with EXPLICIT
  SIZE/TIME/PROJECT filters. `scope` (project), `size` (hard cap 1–100),
  `at` (validity-window containment) + `time.from/until` (observed window),
  and provenance filters (`kinds`, `sourceKinds`, `minAuthority`,
  `minConfidence`, `includeRetracted`). Every result record is PROVENANCE-RICH:
  structural authority, source kind, validity-at-instant, evidence count,
  confidence. Reports `totalMatches`/`truncated`. Deterministic context
  ordering (currently valid → authority → recency). Purely additive.
- Memory never assembles context packs itself — it returns bounded,
  provenance-attributable records for the Context Engine to assemble.

## 1.14.0 contract notes (additive)

- Task 30 (Phase V — Search → Memory history): `memory.search.session` stores
  USEFUL SEARCH INTENT / SESSION HISTORY as retrieval context in an
  append-only, scoped log (`memory_search_sessions`, migration 10). Recording
  a session NEVER creates a durable record or a promotable candidate — the
  history is context, and candidate repositories surfaced by a search are
  recorded BY REFERENCE only and never promoted. Bounded (intent ≤ 1024 chars,
  ≤ 32 result refs, ≤ 32 candidate refs); scope deletion purges the sessions.
- Purely additive; existing callers unaffected.

## 1.13.0 contract notes (additive)

- Task 29 (Phase V — Analysis → Memory proposals): `memory.analysis.propose`
  lets the Analysis engine propose REUSABLE ARCHITECTURAL FINDINGS ONLY as
  EVIDENCE-LINKED candidates (never direct insertion). `sourceKind
  analysis_evidence`, `epistemicClass derived` (a finding derived from
  analysis is never claimed observed), evidenceRefs engine `"analysis"` —
  Analysis records stay external. Batches are bounded (≤ 50 findings, ≤ 8
  evidence refs each); excess/malformed findings are returned in `rejected`
  with typed codes. A finding with ≥ 2 distinct Analysis refs matches
  `repeated_evidence_backed_lesson`. New `EvidenceEngine` value `"analysis"`.
- Purely additive; existing callers unaffected.

## 1.12.0 contract notes (additive)

- Task 28 (Phase V — Study → Memory proposals): `memory.study.propose` lets
  VERIFIED Study findings (`sourceKind study_finding`, `epistemicClass
  observed` — promotion-eligible via `verified_study_fact`) and USER
  ANNOTATIONS (`sourceKind user_note`) become Memory CANDIDATES. Every
  proposal carries Study/version/source-revision provenance by reference
  (`evidenceRef {engine: "study_document", ref: "<studyId>#v<version>#rev<revision>"}`)
  — Study records stay external. Batches are bounded (≤ 50); excess/malformed
  proposals are returned in `rejected` with typed codes, never silently
  dropped.
- Purely additive; existing callers unaffected.

## 1.11.0 contract notes (additive)

- Task 27 (Phase V — Performance → Memory proposals): the Performance engine
  submits BOUNDED, EVIDENCE-BACKED lessons through
  `memory.performance.propose`; each becomes a Memory CANDIDATE in the intake
  stream (never a direct record), referencing Performance records ONLY by
  evidenceRef (`{engine: "performance", ref}`) — Performance records stay
  external. Lessons are bounded (≤ 50 per batch, ≤ 8 evidence refs each) and
  evidence-backed (≥ 1 ref required); excess/failed lessons are returned in
  `rejected` with typed codes, never silently dropped. Promotion stays
  policy-gated: a lesson with ≥ 2 distinct Performance refs matches
  `repeated_evidence_backed_lesson`. New `EvidenceEngine` value `"performance"`.
- Purely additive; existing callers unaffected.

## 1.10.0 contract notes (additive)

- Task 25 (hybrid retrieval): the deterministic Task-19 signal set plus an
  OPTIONAL semantic signal (Task 23), fused ONLY when an embedding provider is
  configured AND the scope's projection is built ("only after baseline
  evaluation"). `memory.hybrid` returns per-hit signal availability/value/
  weight/contribution and a `path` explaining the retrieval path (which
  signals participated; the semantic provider/model or why it was unavailable).
  Degrades gracefully to the deterministic baseline; never silently assumes
  semantics.
- Task 26 (index rebuild + corruption recovery): `memory.projections` unifies
  rebuild/corruption recovery. `check` verifies every derived projection
  (lexical FTS, embedding tables, on-demand graph/entity) against canonical
  records; `rebuild` rebuilds all from canonical records (recovery path);
  `repair` detects corrupted projections and rebuilds only those. Corrupted
  derived projections NEVER corrupt Memory truth (canonical records untouched).
- Purely additive; existing callers unaffected.

## 1.9.0 contract notes (additive)

- Task 24 (Phase IV — optional relationship-graph projection): projects Memory
  relationships into a graph for traversal/history experiments WITHOUT making
  a graph database canonical. Nodes are records, entities
  (`entity:<kind>:<name>`), and external refs (`engine:<name>:<ref>`); edges
  are typed relations (with provenance), supersession (`supersedes` /
  `superseded_by`), and contradiction-group membership (`contradicts`). The
  graph is a DERIVED, REBUILDABLE projection computed from canonical records
  (`memory.graph {action:'rebuild'}` → `memory.graph.projection.rebuilt`).
  `memory.graph {action:'traverse'}` runs a bounded BFS with direction /
  relation-type / depth filters. Purely additive; existing callers unaffected.

## 1.8.0 contract notes (additive)

- Task 23 (Phase IV — optional semantic embedding projection): embeddings are
  OPTIONAL and provider-neutral. The engine defines a sync `EmbeddingProvider`
  interface; a host injects a provider (`engine.setEmbeddingProvider`). With no
  provider, `memory.embeddings` reports `status: unavailable` and
  `memory.semantic` returns `MEMORY_EMBEDDINGS_UNAVAILABLE` — Memory functions
  fully without embeddings. Privacy gate: `sensitive` records are excluded
  unless `includeSensitive: true`; tombstoned content is never embedded.
  The projection records provider/model/version (`rebuildRecommended` when the
  current provider's model differs) and is completely rebuildable
  (`memory.embeddings {action:'rebuild'}` → `memory.embeddings.projection.rebuilt`).
  Purely additive; existing callers unaffected.

## 1.7.0 contract notes (additive)

- Task 21 (Phase IV — typed Memory relationships): `RelationType` is a
  bounded vocabulary `related | depends_on | supports | contradicts |
  derived_from | applies_to | learned_from`; every `RelationHint` may carry
  `provenance {actor, method, capturedAt}`. New op `memory.relation` adds or
  removes a single attributed relation. `memory.related` now also returns
  `supersedes`/`supersededBy` (the canonical supersession chain surfaced
  through the relations view — never duplicated as hints).
- Task 22 (Phase IV — entity linking as a derived projection): entities are
  expressed as `applies_to` relations targeting `entity:<kind>:<name>`
  (`component | repository | technology | decision | other`). New op
  `memory.entities` builds a VERSIONED, REBUILDABLE entity projection from
  canonical records (never canonical truth); `rebuild: true` forces a fresh
  build and emits `memory.entities.projection.rebuilt`.
- Purely additive: existing callers are unaffected.

## 1.6.0 contract notes (additive)

- Task 20 (Phase III — deterministic retrieval baseline, retrieval traces):
  - `memory.explain` gains `validFrom`/`validUntil`, `validity: {at,
    currentlyValid}` (validity window evaluated at `at`, default now),
    `contradiction: {groupId, status, groupSize}` (open/resolved group
    membership, if any), and `evidenceGaps: string[]` (deterministic
    findings: zero evidence refs, or refs whose `expiresAt` has lapsed by
    `at`). Optional new request field `at` (ISO 8601, defaults to now).
  - `memory.search` (both the structured-filter and `asOf` branches) and
    `memory.current` responses gain a `trace` field alongside the existing
    `records`: which filters were actually applied, and — per matched
    record — the concrete reason it satisfied each applied filter (docs/RETRIEVAL.md).
  - Purely additive: existing callers reading only `records`/`{record}`
    fields are unaffected.

## 1.5.0 contract notes (additive)

- Six new retrieval ops; `memory.search` additionally accepts the Task 14
  structured filters (`exactSubject`, `sourceEngine`, `actor`,
  `confidenceMin/Max`, `validAt`, `createdAfter/Before`,
  `observedAfter/Before`).
- The lexical index is a rebuildable derived artifact
  (`memory.index.rebuilt` event); canonical truth is untouched.
- Tasks 17–19 (deterministic retrieval baseline, Phase III):
  - `memory.ranked` — provenance-aware ranking (authority/directness/
    currency/confidence/contradiction), never hiding low-confidence or
    contradicted records.
  - `memory.duplicates` — exact + normalized/near-duplicate detection via
    content hash + token Jaccard; idempotency preserved by existing
    `idempotencyKey` machinery; duplicates distinguished from independently
    corroborating evidence.
  - `memory.fused` — lexical + structured + temporal + provenance +
    relation signals with visible per-signal contributions (never an opaque
    score).

## 1.4.0 contract notes (additive)

- New op `memory.lifecycle` covering archive/restore/tombstone-delete/purge/
  purge-by-privacy/delete-scope — every action attributed + reasoned,
  agents refused.
- `EvidenceRef` gains optional `expiresAt` (ISO 8601): source-evidence
  expiry is visible via `memory.search` results and the
  `memory.evidence.expired` event; records are never silently invalidated.
- `RecordStatus` gains `archived` and `deleted`; default `memory.search`
  view excludes tombstones (request `"all"` to include).

## 1.3.0 contract notes (additive)

- New error code `MEMORY_CORRECTION_FORBIDDEN`: agents cannot directly
  revise or supersede records — their corrections flow through
  `memory.propose` + policy-gated `memory.promote`.
- `memory.revise` now requires `request.reason` and rejects agent actors.
- Supersession (via the API, not a contract op) records a required
  `supersededReason` visible through `memory.history` and `memory.get`.

## 1.2.0 contract notes (additive)

- Two new error codes: `MEMORY_INTAKE_UNAUTHORIZED` (allowlist intake),
  `MEMORY_PROMOTION_FORBIDDEN` (agent promotion attempt).
- `memory.promote` now requires `request.actor` (attributed decision) —
  callers that previously omitted it must pass their actor identity.
- `memory.propose` now requires `request.reason`.
- Failure envelopes for intake/promotion rules carry the new codes above.

## Events (versioned notification surface)
`memory.scope.created`, `memory.scope.intake_policy.updated`,
`memory.record.created`, `memory.record.revised`, `memory.record.superseded`
(with reason), `memory.record.retracted`, `memory.records.expired`,
`memory.record.repaired`, `memory.contradiction.registered`,
`memory.contradiction.resolved`, `memory.candidate.created`,
`memory.candidate.promoted`, `memory.candidate.rejected`,
`memory.relation.added`, `memory.relation.removed`,
`memory.entities.projection.rebuilt` (Tasks 21–22, 1.7.0),
`memory.embeddings.projection.built`, `memory.embeddings.projection.rebuilt`
(Task 23, 1.8.0), `memory.graph.projection.rebuilt` (Task 24, 1.9.0).
`memory.index.rebuilt` also fires for the lexical projection on a unified
`memory.projections` rebuild/repair (Task 26),
`memory.candidate.created` (per accepted Performance lesson, Task 27),
`memory.candidate.created` (per accepted Study proposal, Task 28),
`memory.candidate.created` (per accepted Analysis finding, Task 29),
`memory.search.session.recorded` (Task 30). Events carry
references and metadata only — never content bodies. Reads emit no events.

## Failure behavior

All failures are typed envelopes (`MEMORY_VALIDATION_FAILED`,
`MEMORY_NOT_FOUND`, `MEMORY_CONFLICT`, `MEMORY_CONTRACT_MISMATCH`,
`MEMORY_STORE_UNAVAILABLE`, `MEMORY_PRIVACY_VIOLATION`, …). The dispatcher
never throws across the boundary.
