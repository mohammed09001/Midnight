# Midnight Performance

## Improvement analysis model

Performance treats raw prompt, repository, and executed-verification evidence as
authoritative for their respective observations. Intent, structural change,
behavior, traces, trajectories, outcomes, profiles, and decision stories are
versioned derived projections with explicit evidence and uncertainty. Passing
tests are scoped evidence, not a generic correctness claim; optional AI remains
policy-gated and non-authoritative. Performance observes work and does not host
coding agents, rewrite prompts, or own sibling-product data stores.

Midnight Performance is a development-history intelligence core. It records
evidence observed during normal developer and coding-agent work; it does not
host coding agents, modify prompts, or own repository truth.

The package is deliberately stdlib-only and file-backed so its contracts can be
used before a product persistence layer exists. The append-only ledger is the
canonical owner of accepted raw and normalized Performance observations.
Repository/VCS captures and verification observations remain separate evidence
types, while episodes and analysis are rebuildable projections over that ledger.

## Contract boundaries

* Every record has a versioned, typed Performance identity and an explicit
  claim qualification (`observed`, `derived`, `inferred`, `statistical`,
  `predicted`, `recommended`, or `unknown`).
* External systems are represented only by versioned references. The contract
  grants no database access and does not copy sibling-product authority.
* A `ChangeSet` is Performance's durable observation of repository changes; it
  is not a universal source-code graph.
* Episodes correlate prompt runs, agent runs, changes, verifications, feedback,
  and outcomes. Rebuilding the projection is deterministic and does not alter
  raw evidence.
* A provider-neutral observation envelope preserves raw, normalized, and
  derived layers, with narrow OpenTelemetry GenAI import/export mappings.
* Durable writes are project-isolated and policy-gated. Field-level categories
  independently control prompts, model output, source/diff content, commands,
  tools, transcripts, repository metadata, sibling references, PII, secrets,
  and credentials. Unclassified fields fail closed; recognised secrets and PII
  are locally redacted. Export is disabled unless the policy explicitly allows
  it; transcript/debug content should use the `transcript` category.
* Coding-harness adapters are observation declarations, not launchers. The
  Codex adapter only normalizes supplied approved-hook, app-server, or SDK
  event dictionaries; unsupported fields remain explicit evidence gaps.

## Memory bridge

`midnight_performance.memory_bridge` maps Performance PROJECT/WORKSPACE
identities to Midnight Memory scope identities, and builds versioned JSON
envelopes for Memory's `memory.performance.propose` (write) and
`memory.context` (read) contract operations, exchanging them by calling
Memory's CLI subprocess (`contract call`) — the only supported cross-process
path; this module never opens Memory's SQLite store. Failures are typed:
`MemoryUnavailableError` (Memory/node unreachable — a process-level failure)
and `MemoryContractError` (a typed `ok:false` response, e.g.
`MEMORY_CONTRACT_MISMATCH`). Evidence handed to Memory must come from a
sealed, verified `ObservationEnvelope` (`lesson_from_sealed_envelope`) —
never raw payloads; an unsealed or tampered envelope is refused before any
call to Memory is attempted. `lesson_from_qualified_claim` exports a real
Performance `QualifiedClaim` (evidence-authority-checked, never raw agent
prose) grounded in one or more sealed envelopes as a bounded, evidence-backed
lesson, deriving Memory's `epistemicClass` from the claim's `ClaimKind`
without ever upgrading claim strength.

Delivery is replay-safe by default: lesson builders set a deterministic
`idempotencyKey`, so re-proposing the same lesson (e.g. after a retry) always
resolves to the same Memory candidate, never a duplicate.
`call_memory_cli_with_retry` bounds retries to transient failures
(`MemoryUnavailableError`) only — a deterministic `MemoryContractError`
(validation, authorization, contract-version mismatch) is never retried.

Lesson text also carries a structural privacy backstop (Task 17, Execution
06): `subject`/`content`/`note` pass through `redact_sensitive_text`
(`privacy.py` — the same secret/email pattern `PrivacyGuard` applies to
`Observation.payload`) before crossing to Memory, so a stray secret in
caller-authored text is caught even though the lesson was never supposed
to carry payload text in the first place.

`Memory/docs/CROSS_ENGINE_LINEAGE.md` (Task 19) walks one identity through
the full loop — evidence, lesson, candidate, promoted/contradicted record,
later retrieval, later Performance analysis — proven end to end in
`tests/test_memory_bridge.py`'s `CrossEngineLineageTests`. Bridge-boundary
recovery/restart/backup/evidence-expiry behavior (Task 21) is qualified in
`tests/test_memory_bridge_recovery.py`; see `Memory/docs/PERFORMANCE.md`'s
"Recovery, restart, and backup semantics across the boundary" section.

## Memory ownership migration (Execution 04, Tasks 10-12)

`memory.py`/`memory_retrieval.py`/`evaluation_memory_qualification.py`
previously carried a second, competing durable-knowledge authority. A
caller-graph audit across the whole package (every real import site, not
just the obvious files) found this classification and migration map:

| Symbol | Classification | Disposition |
|---|---|---|
| `MemoryDomain`, `MemoryEvidence` (`memory.py`) | Performance-local, non-durable evidence-candidate shapes — no status field, no persistence, no store | Kept as-is |
| `KnowledgeRecord`, `promote()`, `supersede()` (`memory.py`) | Duplicate durable-memory ownership — a second record lifecycle (`status`/`supersedes`/`contradicts`) and a second multi-source promotion policy, mirroring what Midnight Memory already owns canonically | Removed. Turning Performance evidence into durable knowledge now requires an explicit proposal through `memory_bridge.py` |
| `MemoryHit`, `retrieve_memory()`, `retain()` (`memory_retrieval.py`) | Performance-local, stateless — operates only on a caller-supplied in-process tuple; never reads a store, never touches canonical Memory | Kept as-is |
| `qualify_evaluators`/`EvaluationQualification` (`evaluation_memory_qualification.py`) | Unrelated to Memory — evaluator-ensemble qualification | Untouched |
| `qualify_memory`/`MemoryQualification` (`evaluation_memory_qualification.py`) | Duplicate durable-memory ownership (transitively) — existed solely to qualify the removed `promote()`/`KnowledgeRecord` | Replaced by `qualify_memory_integration`/`MemoryIntegrationQualification`, which qualifies the real bridge instead: a machine-checked "no local duplicate authority" structural invariant, plus (when an envelope is supplied) a real delivery-or-truthful-degradation check |

At audit time, the only real consumers of `KnowledgeRecord`/`promote`/`supersede`
were `evaluation_memory_qualification.py` and two test methods — nothing in
Performance's actual capability surface (`query_api.py`, `orchestration.py`,
`read_tools.py`, `relationship_graph.py`) touched any of it. All consumers
were migrated in this same change, so removal (not a deprecation shim) was
the correct, smallest-footprint move.

## Standalone operation

Performance's evidence ledger, repository/VCS capture, verification,
feedback, and analysis workflows have zero dependency on Midnight Memory
being installed, running, or reachable — none of that code imports
`memory_bridge`. The only Memory-touching surface is `memory_bridge.py`
itself, and its orchestration helpers (`propose_lesson_or_degrade`,
`read_memory_context_or_none`) degrade truthfully: unavailability,
contract-version mismatch, and policy denial all return a typed, honest
"not delivered" result rather than raising into unprepared caller code or
silently fabricating success. A degraded result is never treated as a
promotion — only Memory's own accepted candidate is durable knowledge.

Run the verification suite with `python -m pytest tests/ -v`. Use pytest,
not `python -m unittest discover` — several test files (including
`test_evaluation_memory_qualification.py`, the Memory-integration
qualification tests) use plain `assert`-based pytest-style functions rather
than `unittest.TestCase` classes, and `unittest discover` silently collects
**zero** tests from those files (no error, no warning) rather than failing
loudly. `python -m pytest tests/` is the project's actual configured test
runner (see `pyproject.toml`) and is the only command that exercises the
full suite.

## Provider capture qualification (Midnight Execution 04)

Before this pass, `claude_adapter.py`/`codex_adapter.py`/`opencode_adapter.py`
only NORMALIZED an already-supplied hook payload into an in-memory
dataclass — none of them wrote anything durable, and the one real write path
(`prompt_capture.py`) was completely disconnected from all three. "Performance
runs invisibly in the background" wasn't actually true yet. This pass:

* **Built one real hook entrypoint**: `claude_hook_capture.py`'s
  `UserPromptSubmit` observer, held to a machine-verified contract confirmed
  against the live Claude Code hooks reference (code.claude.com/docs/en/hooks,
  2026-09): zero stdout bytes ever (any stdout on exit 0 is injected as
  context Claude can act on), exit code always 0 (exit 2 erases the user's
  prompt entirely), a bounded internal timeout well under the hook's own 30s
  default, and diagnosable-but-never-blocking failure. `tests/test_claude_hook_capture.py`
  proves this via real subprocess invocation across valid, garbage, empty,
  missing-field, unwritable-path, and adversarial-payload inputs.
* **Corrected the Codex adapter** against the current, live App Server
  protocol (`openai/codex` `codex-rs/app-server/README.md`, 2026-09): the
  repo's dot-separated event names (`thread.started`, `item.diff_updated`,
  `turn.usage`, `item.verification`) were stale — the current protocol uses
  slash-separated notifications (`thread/started`, `turn/started`,
  `turn/completed`, `item/started`, `item/completed`, ...) with items
  carrying a `type` discriminator. `Capability.PROMPT` was added (backed by
  the confirmed `userMessage` item + `turn/started`'s `input` array, with
  `codex_prompt_run_identity()` deriving a deterministic correlation key from
  native `clientUserMessageId`/`thread.id:turn.id:item.id` only — never
  prompt text). `Capability.VERIFICATION`/`Capability.NATIVE_DIFF` were
  removed — research found no confirmed backing event for either, and an
  unproven positive capability claim is itself an invisible-capture bug.
  `CODEX_ADAPTER.version` bumped 1→2 for this real vocabulary break.
* **Hardened the OpenCode adapter** against its own documented
  mutation-capable hooks (`tool.execute.before`, `shell.env`,
  `experimental.chat.system.transform`, `experimental.session.compacting`,
  `stop` — opencode.ai/docs/plugins/, 2026-09): `OpenCodeObserver.normalize`
  now refuses to observe any of them outright (a caller integration mistake,
  not a data gap), and its docstring names `ctx.event.subscribe` as the only
  correct, purely-observational real integration point.
* **Closed the cross-process idempotency gap**: `EvidenceLedger`'s
  check-then-append critical section was guarded only by an in-process
  `threading.Lock` — insufficient, since Claude Code's own docs confirm
  concurrent hook processes for the same event are normal, expected
  behavior. A cross-platform advisory file lock (`msvcrt`/`fcntl`) now
  guards it; `tests/test_ledger_concurrency.py` proves no silent duplicate
  canonical identity under real concurrent `subprocess` writers (not
  threads), and that a hard-killed writer's torn line is detected and
  rejected by `replay()` rather than silently accepted — full crash
  atomicity (a temp-file-then-rename redesign) remains open, deferred to a
  future execution.
* **Formalized occurrence vs. full Prompt evidence**: `prompt_capture.py`'s
  empty-payload Prompt Run records now carry an explicit
  `attributes={"occurrence_only": True}` marker (`is_occurrence_only()`) so
  the `PROMPT_VERSION` subject's role as a bare correlation anchor — never
  proof a full PromptVersion was observed — is machine-checkable, not just
  documented.
* **`provider_capability_matrix.py`** is the resulting capability matrix
  (Section A): `build_capability_matrix()` diffs each adapter's implemented
  capabilities against `CURRENT_PROVIDER_MANIFESTS` (this execution's
  research snapshot, refreshable) via the existing `drift.probe()`
  machinery — and separately surfaces `unconfirmed_by_research` capabilities
  honestly (not silently stripped) where research couldn't positively
  confirm or deny a claim, distinct from Codex's `VERIFICATION`/`NATIVE_DIFF`
  which were removed on positive evidence of absence.

No live Claude `settings.json` wiring, live Codex app-server client, or live
OpenCode Node plugin exists in this repo — out of scope by design (Codex's
app-server is Codex's own engine process; a passive observer would need to
attach to a connection some other host already holds, never launch it
itself).

## Rebuildable read projection (Midnight Execution 05)

Real benchmarks showed every Performance read doing a full O(n) file
replay: `desktop_bridge.prompt_run_activity` re-read and re-sorted the
*entire* ledger on every single call. Measured before this execution
(Windows, Python 3.14.6):

| N | file size | append (1 op) | full replay | activity query (limit=100) |
|---|---|---|---|---|
| 1,000 | 668,890 B | 39.40 ms | 29.54 ms | 30.89 ms |
| 10,000 | 6,698,890 B | 328.45 ms | 307.04 ms | 321.20 ms |
| 100,000 | 67,088,890 B | 3,317.62 ms | 3,664.62 ms | 3,865.51 ms |

`Performance/midnight_performance/projection_store.py` adds a local SQLite
(stdlib `sqlite3`, version 3.50.4 on this machine) read projection —
indexed, rebuildable, and **disposable**. It is never a second source of
truth: `EvidenceLedger`/`evidence.jsonl` remains the sole canonical
authority (Section B), and every row in the projection is derived,
byte-for-byte, from what `EvidenceLedger.replay()` — the ledger's own
authoritative parser — accepted. If the projection file is ever deleted,
corrupted, or simply wrong, the only fix is `rebuild()`; there is no repair
path for it, because none is needed.

**Why SQLite, not something else**: the measured numbers above are the
textbook case for an indexed B-tree — linear O(n) scaling on every read,
eliminated by an index. Measured after (`scripts/benchmark_evidence_reads.py`,
same machine, same methodology):

| N | query BEFORE (ms) | query AFTER median (ms) | query AFTER p95 (ms) |
|---|---|---|---|
| 1,000 | 32.38 | 3.42 | 5.08 |
| 10,000 | 327.04 | 5.73 | 7.00 |
| 100,000 | 3,895.80 | 26.12 | 35.01 |

A ~9x speedup at 1k, ~57x at 10k, ~149x at 100k. `desktop_bridge`'s CLI
contract, cursor/keyset semantics, and JSON response shape are unchanged —
every pre-existing `tests/test_desktop_bridge.py` assertion still passes
against the projection-backed implementation unmodified; the response gains
one additive `checkpoint` field (`schemaVersion`, `ledgerByteOffset`,
`ledgerRecordCount`, `generation`).

**Checkpoint algorithm**: resuming incrementally never re-trusts the whole
ledger prefix. `update()` re-hashes *only* the single last-consumed line
(a direct seek+read, O(1) — not the whole file) and checks the file size
against the recorded offset; on any mismatch it fails closed and falls back
to a full `build()`, which reuses the real, untouched `ledger.replay()` for
all parsing — so genuine corruption always raises the exact same
`ValueError` it always has, never a bespoke error from the fast path.
Accepted, documented limitation: a hand-edit of an OLDER line, made after
the checkpoint has already moved past it, is not re-detected by this O(1)
check — a full Merkle-style chain would catch that too, but is
over-engineering for what this execution asks; `ledger_doctor.py`'s full
scan is the tool for that concern when it actually matters.

**Concurrency**: real multi-process testing
(`tests/test_projection_concurrency.py`, real `subprocess.Popen` writers —
not threads) found a genuine race the design hadn't anticipated: two
processes concurrently deciding "no projection exists, I must build one"
both call `discard()`, and on Windows an `unlink()` racing another
process's still-open SQLite handle on the same file raises a native
sharing-violation `PermissionError`. Fixed with a projection-specific
cross-process lock (reusing Execution 04's `_cross_process_lock` mechanism,
on its own sibling `.lock` file — deliberately separate from the ledger's
append lock, so a rebuild never blocks unrelated ledger appends) around the
whole build/update decision. **WAL was measured and NOT selected**: with
the above lock already serializing all projection writers against each
other, a real concurrent-load comparison showed no benefit (DELETE-mode
1.823s vs. WAL-mode 1.951s for the same scenario) — WAL's extra sidecar
files and checkpoint-management complexity would have bought nothing.
`PROJECTION_JOURNAL_MODE = "DELETE"` (the default rollback journal) stays
the default; `busy_timeout` is set on every connection regardless.

**Append-path cost is measured and reported, not fixed**: the ~3.3s@100k
append cost above comes from `EvidenceLedger.append`'s own O(n) duplicate
check, a *separate* problem from the read path this execution addresses.
Canonical-ledger write correctness must never depend on this disposable,
sometimes-momentarily-behind projection being fresh — folding a write-path
optimization into the single most safety-critical code path in the package,
in the same execution that's about read infrastructure, would be exactly
the over-engineering the mission warns against. Tracked as an open,
separately-scoped follow-up risk, not silently ignored.

**Corruption detection** (`ledger_doctor.py`): a collect-all scanner —
unlike `replay()`, which must stop at the first bad line, this finds every
invalid-JSON line, truncated final record, checksum mismatch, unexpected
project, and duplicate canonical identity in one pass. Detection only, by
design: Section E requires any future repair to be explicit, back up first,
and produce an audit result, and building that machinery before any real
incident has ever needed it would itself be over-engineering. Its CLI
(`python -m midnight_performance.ledger_doctor --data-dir ... --project
...`) is the dev/diagnostic command demonstrating canonical ledger record
count, projection checkpoint, indexed record count, and
healthy/rebuild-required in one JSON document — a manual tool, deliberately
**not** wired into any product UI as a KPI card.

## Actual Performance graph materializer (Midnight Execution 06)

Before this pass, `build_graph`/`compose_graph`/`build_performance_visual_map`
existed, were tested, and worked — but nothing in production code called
them. There was no path from a real Prompt Run identity to a graph document
Desktop could read. Along the way, direct inspection of the existing graph
code found two real bugs and one real gap:

* **Isolated root bug**: `PerformanceGraph.nodes` was entirely edge-derived
  (`frozenset(edge.source ...) | frozenset(edge.target ...)`) — a Prompt Run
  with zero edges (no version, no agent runs, nothing) never appeared in
  `.nodes` at all. Fixed with an explicit `roots: frozenset[Identity]` field
  (new, defaulted, backward compatible with every existing construction
  site) — `build_graph` always registers the requested Prompt Run as a root,
  never via a fake self-edge or placeholder relationship. `merge()` and
  `compose_graph()` correctly union/collect roots too, so a merged or
  multi-run graph never silently drops a previously-registered isolated
  node. Confirmed via the existing graph test in `test_contracts.py`: it
  always builds a `PromptRun` with a real version, so it never exercised
  the true zero-edge case — this fix is purely additive against it.
* **Undifferentiated edges**: every reference edge — PromptRun→AgentRun,
  AgentRun→ToolObservation, PromptRun→ChangeSet, everything — carried the
  same generic `EdgeKind.REFERENCE`, so the only way to tell them apart was
  inspecting the target's entity kind. A new `EdgeSemanticRole` enum (15
  values: `prompt_version`, `executed_by`, `agent_session`, `agent_turn`,
  `used_tool`, `executed_command`, `produced_change`, `changed_file`,
  `contains_symbol`, `verified_by`, `feedback_for`, `outcome_reference`,
  `episode_membership`, `analysis_lineage`, `cites_memory`, plus
  `dataset_membership`/`experiment_reference`/`repository_entity` for edges
  the doc's examples didn't name) is assigned explicitly at the one place
  each relationship's true meaning is known — `build_graph`/`compose_graph`
  — never guessed from an edge's target afterward. Threaded through to a new
  `semantic_role` field on `VisualEdge`/`GraphEdge` (both new, defaulted,
  backward compatible with every existing 9-positional-argument test call).
* **Raw text in "safe" evidence**: `VerificationEvidence.output` (raw
  command output) and `FeedbackRecord.free_text` (raw human commentary) are
  real fields on real domain types that would otherwise land in
  `GraphEdge.evidence` unfiltered. `evidence_citation.py`'s
  `EvidenceCitation` (stable reference id, evidence kind, project, optional
  observed time/source, `detail_available`, and a bounded ≤280-char
  structural-only `summary`) is the only shape allowed into the default
  Desktop graph; its per-domain builders (`verification_citation`,
  `feedback_citation`, `outcome_citation`) explicitly whitelist safe fields
  and never touch either raw-text field — proven by dedicated tests that
  assert the raw content never appears anywhere in a built citation or a
  full graph document.

**Evidence qualification** (Section D): `VisualNode.claim_kind` already
unambiguously meant "the projection's own claim strength" (already enforced
by `VisualNodeMetadata` banning `ClaimKind.OBSERVED` there) — the missing
concept was the underlying SOURCE evidence's claim kind, a genuinely
different thing. New `source_claim_kind`/`source_layer` fields (both new,
defaulted) are populated only where real evidence supports it: a real
Prompt Run node gets `source_claim_kind=OBSERVED`, `source_layer=normalized`
(exactly what `prompt_capture.py` actually writes); every other domain
stays `None` today, since nothing durably captures that evidence yet —
"unknown source qualification stays unknown," never guessed.

**The materializer** (`graph_bridge.py`, `prompt_run_graph()` +
`python -m midnight_performance.graph_bridge` CLI, mirroring
`desktop_bridge.py`'s exact pattern): resolves the requested Prompt Run's
real existence via Execution 05's `projection_store` (catching the
projection up first, exactly like `desktop_bridge.prompt_run_activity`
does) — this is the one thing it independently resolves from real evidence.
Everything else (AgentRun, ChangeSet, Verification, Feedback, Outcome,
Episode, Analysis, Memory citations) comes from a caller-supplied
`known_evidence` `PromptRun` plus the same caller-supplied-evidence
parameters `build_graph` has always accepted — never invented. Today's real
system has no durable capture for any of those domains (confirmed:
Execution 04 only ever wired Prompt Run occurrence + repository-change
capture), so a bare, real Prompt Run materializes as one root node with
honest gaps for everything else — not a shortfall, the literal truth of
what Performance currently knows.

**Bounds** (Section I): `graph.getPromptRun`'s default is one Prompt-scoped
slice — this bridge only ever calls `build_graph` (one run), never
`compose_graph` (many runs), so it structurally cannot default to a
full-project graph. `maxDepth` filters via the existing `traverse()`
reachability helper; `maxNodes`/`maxEdges`/`allowedLayers` filter and cap
the deterministically-ordered node/edge lists `build_performance_visual_map`
already produces; any capping sets `truncated: true` explicitly, with an
opaque, project-and-root-bound continuation cursor (same
encode/decode-cursor pattern as `desktop_bridge.py`) for node pagination.
Edges beyond `maxEdges` are cut, not separately paginated — a deliberate V1
simplification for what's meant to stay a small, single-Prompt-Run slice,
not a general graph browser.

**Integrity** (`graph_integrity.py`, Section J): reuses
`link_integrity.py`'s `IntegritySeverity`/`IntegrityMode` convention, not
its checks (an unrelated domain — requirement traceability). Two required
invariants — no invalid self-edge, confidence in range — are already
structurally impossible to violate (`GraphEdge.__post_init__` rejects both
at construction) and are not re-checked. New checks: root exists; every
node's project context matches the request; every edge's endpoints are
represented nodes; no canonical identity claimed under two different entity
kinds; truncation is explicit.

Out of scope, deliberately: TypeScript/Desktop Host wiring.
`desktop/host/operations/registry.ts` already has a reserved comment for a
future graph-read operation family; nothing in this execution's own scope
mentions `desktop/` — this is Performance-side plumbing, ready for that
wiring in a future execution.

## Repo Intelligent foundation contracts (Execution RI-01)

`midnight_performance/repo_intelligence/` is the canonical foundation for
**Midnight Repo Intelligent** — a project-scoped intelligence extension of
Performance. It owns only derived project-intelligence state. Performance
remains canonical owner of Performance evidence, the live repository
remains canonical owner of source-code truth, Midnight Memory remains the
only durable-memory authority (reached exclusively through
`memory_bridge`), and external source records remain evidence, never
automatically trusted knowledge.

* **Identity namespaces.** Derived records carry `ri:v{N}:{kind}:{uuid}`
  identities (`RepoIdentity`, `identities.py`) derived deterministically
  via `uuid5(NAMESPACE_URL, "midnight-repo-intelligent:v{N}:{kind}:{key}")`.
  Performance entities are referenced by their existing `mp:` canonical
  identities and are never duplicated; Memory references stay
  `ExternalReference` pointers. Twelve record kinds are defined:
  ProjectIntelligenceJob, InternalSignal, ProjectEntityRef,
  ExternalSourceRef, ResearchQuestion, EvidenceBundle, ProjectInsight,
  LineageReceipt, GraphLink, Exposure, LearningOutcome, CostRecord.
* **Claim discipline.** Claim strength reuses Performance's `ClaimKind`
  with no upgrades: signals/insights/graph links can never carry
  `observed`; insights can never claim `observed` and external-only
  evidence supports only weak kinds (`validate_insight_against_bundle`);
  one-sided external insights additionally require authoritative trust
  classes plus explicit disclosure; `LearningOutcome` may only claim
  `statistical`/`unknown` — later improvement is association, never
  causality; recommended insights must require an explicit user action.
* **Provenance and lineage.** Every record is project-scoped and carries
  capture times, trust/freshness windows (`Freshness` evaluated against an
  injected clock), content digests, derivation method+version, gaps, and
  uncertainty. A `LineageReceipt` (Performance Lineage Receipt) records
  the evidence/snapshot/Memory pointers, derivation, privacy decision, and
  cost linkage behind each derived artifact — an insight with no lineage
  receipt is never eligible for proactive exposure
  (`ProjectInsight.proactively_exposable()`).
* **Research questions.** The question contract forces the compiler
  fields (why-now, trigger evidence, known/unknown, what external evidence
  would change the answer, stop condition, budget) and refuses questions
  marked internally answered — Memory/internal sufficiency structurally
  blocks external research.
* **Authorization.** `authorization.py` fails closed on cross-project
  access (`CrossProjectAccessError`), isolates state directories per
  project identity, and bakes the project identity into every
  content-addressed cache key so byte-identical content from two projects
  can never collide. External/model access is denied unless explicitly
  granted.
* **Ports.** `ports.py` defines provider-neutral protocols for repository
  intelligence, Performance reads, Memory bridge, external discovery,
  fetch/parse, embeddings, model generation, graph projection, clock, and
  budget meter — each with honest `PortAvailability`. The bare core runs
  with zero providers configured (all report unavailable with reasons,
  including `budget_meter`, whose absence denies all spend), performs no
  network/model/storage work, and imports no database, network, or
  subprocess modules (`tests/test_repo_intelligence_architecture.py`
  proves this structurally, along with no duplicate durable-memory
  authority and no sibling storage access).
* **Fail-closed serialization.** Every record serializes deterministically
  (`to_dict`/`from_dict`) and rejects unknown fields and unsupported
  `schema_version`s on read (`UnsupportedSchemaVersionError`).

Verification: `python -m pytest tests/test_repo_intelligence_contracts.py
tests/test_repo_intelligence_authorization.py
tests/test_repo_intelligence_ports.py
tests/test_repo_intelligence_architecture.py -v`.

## Repo Intelligent signal engine (Execution RI-02)

`scan_signals` turns the current project plus Performance history into
**signals of learning need** — deterministically, locally, and without a
model.  Performance evidence remains canonical: the engine joins the
exact `ObservationEnvelope` stream `EvidenceLedger.replay()` yields
(repository-change observations with path payloads, verifications,
episode-correlated Prompt Run occurrences), attributes evidence to
entity paths, and reports everything it could not attribute as an
explicit gap — never reconstructed.

* **Incremental entity resolution** (`entity_resolution.py`): reuses
  Performance's `RepositorySnapshot`/`resolve_file_change` and adds a
  content-independent `ProjectEntityRef` rollup (repository → package →
  file/module → test/config/doc, plus symbols/regions from the canonical
  per-change resolver).  `upsert_entity_refs` processes only touched
  paths; identity survives content edits, `first_seen_at` is preserved,
  and freshness moves forward.
* **Explainable learning pressure** (`signals.py`): six inspectable,
  replaceable factors — activity × friction × recurrence × impact ×
  knowledge deficit × freshness — with per-factor evidence ids, basis
  text, configurable weights, and an explicit decay half-life so old
  hotspots cannot dominate.  Missing evidence yields missing factors and
  lower confidence, never invented values; a single observation can
  never reach high confidence (evidence-diversity gate).  Co-change
  evidence without partners leaves impact *unknown*, not zero.
* **Churn is activity, not defect**: repeated edits with passing
  verification produce a neutral churn signal and evidenced zero
  friction; friction requires failure evidence (failures, flaky flips,
  rollbacks).  Signal kinds: churn, rework, verification_failure,
  flaky_verification, recurring_intent, rollback, coupling, evidence_gap,
  unfamiliar_subsystem, recurring_task.
* **Lineage and cost**: every signal ships with a Performance Lineage
  Receipt (source evidence/change refs, derivation method+version,
  window, gaps, confidence, `local_only` privacy decision) and, when a
  job is supplied, a `LOCAL_COMPUTE` cost record measured by an injected
  monotonic clock.  Cross-project evidence in the stream fails closed.
* **Question compiler** (`question_compiler.py`): compiles abstract,
  privacy-minimized `ResearchQuestion` candidates from signals only —
  churn alone never compiles; every compiler field (why-now, trigger
  evidence, known/unknown, what external evidence would change the
  answer, stop condition, budget) is produced or the question is
  refused; private identifiers stay out of the text unless the
  authorization explicitly allows them; deterministic dedup keys collapse
  semantically equivalent questions before any external call; an
  internally/Memory-sufficient answer closes the question as
  `ANSWERED_INTERNAL`.  Compilation involves no model and no network, so
  it can never spend external budget.

Verification: `python -m pytest
tests/test_repo_intelligence_entity_resolution.py
tests/test_repo_intelligence_signals.py
tests/test_repo_intelligence_question_compiler.py -v` (includes the
required synthetic-history distinctions: healthy iteration vs repeated
failure, one large refactor vs chronic rework, recently hot vs
historically hot, and identical filenames across two isolated projects).

## Repo Intelligent project knowledge graph (Execution RI-03)

`project_graph.py` builds a **federated overlay, not a mega-graph**:
Performance entities and Memory records appear only as typed reference
nodes owned by their canonical products, repository structure comes from
resolved `ProjectEntityRef`s, external sources stay untrusted-evidence
anchors with trust provenance, and Repo Intelligent's own artifacts
(signals, evidence bundles, insights, questions, exposures, outcomes)
link through stable `GraphLink` edges.  A deterministic generation
digest covers the whole graph: the same authoritative inputs always
rebuild the same graph.

* **Node families** cover the required model: repository structure
  (repository → package → file/module → test/config/doc → symbol/region
  via `CONTAINS`), Performance evidence references, Memory references
  (additive `MEMORY_REF` identity kind), concepts (additive `CONCEPT`
  kind with `ConceptRole` topic/concept/technology/dependency/pattern/
  failure-mode), research questions, external knowledge, and
  intelligence artifacts.  `ABOUT` edges from entities and signals to
  concepts come from the deterministic token abstraction — marked
  structural because it is exactly reproducible, with uncertainty text
  saying so.
* **Edge families** derive from evidence: `CHANGED_IN`, `VERIFIED_BY`/
  `FAILED_IN` (by parsed pass state), `DISCUSSED_IN` (episode-correlated
  occurrences), `DERIVED_FROM`, `SUPPORTED_BY` (insight → bundle items),
  `RELEVANT_TO` (question → concept by deterministic label match),
  `EXPOSED_AS`, `LEARNED_FROM` (uncertainty: association is not
  causality), `SUPERSEDES` (from recorded insight supersession), plus
  caller-supplied `SIMILAR_TO`/`RELATED_TO`/`EXTERNAL_ANALOGUE_OF`
  links — probabilistic edges stay `EdgeClass.SEMANTIC` and must carry
  confidence, keeping exact structure separate from model output.
* **Integrity** (`validate_overlay`) fails closed on dangling endpoints
  (no orphan cross-project edges — every anchor is auto-materialized as
  a typed reference node), project mixtures, and generation-digest
  drift.  Cross-project inputs raise `CrossProjectAccessError`.
* **Incremental updates** (`update_project_graph`) recompute only the
  changed-path subgraph and splice; tests prove the result equals a full
  rebuild for the same inputs.  Temporal semantics are honored:
  `active_links`/`stale_links` filter superseded and expired edges, and
  event edges carry real observation timestamps.
* **Traversal** (`graph_traversal.py`) is deterministic, cycle-safe, and
  budget-aware: `neighbors`, `traverse` (explicit `max_hops`/`max_nodes`
  caps with an honest `truncated` flag), `explain_path` (every hop cites
  its underlying evidence ids), and deterministic `communities`
  (connected components over a selectable relation subset).

## Memory Temporal Lineage Overlay (Midnight Execution 09)

The key distinction this execution makes legible, in code and in the UI, not
just in `Memory/docs/CROSS_ENGINE_LINEAGE.md`'s prose: a Memory citation
inside a historical Performance graph is a **pinned historical revision**;
current Memory state is a **separate, explicitly refreshed read**. Building
a graph from a citation never contacts Memory again, and refreshing never
rewrites a graph already built.

**`memory_temporal_lineage.py`** (new): `MemoryCitationState` carries the
minimum Section D requires — `pinnedRevision` (always known, parsed from the
citation), and `currentStatusKnown`/`currentRevision`/`currentStatus`/
`superseded`/`supersededByRecordId`/`contradictionGroupId`/
`contradictionStatus`/`contradictionGroupSize`/`newerRevisionAvailable`/
`refreshedAt`, all `None` until a real refresh happens. `pinned_state()` is
pure parsing (the inverse of `memory_bridge.citation_from_memory_record`'s
`<recordId>#rev<revision>` format, via the new `memory_bridge.
parse_pinned_reference`) — zero Memory contact. `refresh_state()` is the
ONLY function that talks to Memory, and only through the existing
`memory.context` operation (`read_performance_context` — no new Memory-side
contract). It never mutates its input; every branch (Memory unreachable,
contract mismatch, record outside the bounded read window) returns a brand
new, gap-annotated state instead of raising — the truthful degraded mode
Section E requires. `newerRevisionAvailable`/`superseded` are only ever set
from an actual revision comparison, never from elapsed time — "stale" is
discovered, never assumed.

**`memory_lineage_bridge.py`** (new): `graph.refreshMemoryCitation`'s
read-only Desktop bridge — a pure function, project-scoped, self-validated
JSON on stdout, mirroring `graph_bridge.py`'s exact pattern. Deliberately
independent of `graph_bridge.py`/`prompt_run_graph()`: refreshing one
citation's current state has nothing to do with Performance's own evidence
ledger (no `--data-dir` at all), and never re-fetches or re-validates a
`PromptRunGraphDocument`.

**`graph_bridge.py`'s build-time overlay**: `_build_memory_lineage()` turns
every `memory_references` citation into a `MemoryCitationState` via
`pinned_state()` (parsing only, still zero Memory contact at graph-build
time) and a new `memoryLineage` array on the response document, keyed by
node id — parallel to the existing `citations` array, never embedded on the
node itself. It also fixed a real, previously-latent gap: before this, a
cited Memory node's `VisualNode.label` fell back to its opaque hashed
canonical identity, because no caller ever supplied `node_metadata` for it;
`_build_memory_lineage()` now labels it `memory:<recordId>#rev<revision>`.

**Desktop wiring** (`getPromptRunGraph.ts`'s sibling `refreshMemoryCitation.ts`,
registered as `graph.refreshMemoryCitation` in `registry.ts` — now
`{"activity.listPromptRuns", "graph.getPromptRun",
"graph.refreshMemoryCitation"}`): same strict request-field allow-list,
`execFile`-spawned bridge, schema-validated stdout pattern as every other
operation. `PerformanceGraph.tsx` owns one small piece of client state — a
`nodeId -> MemoryCitationState` map of refreshed results, overriding the
build-time `memoryLineage` entry ONLY for the refreshed node, never mutating
`document` itself. `GraphInspector`'s new "Memory lineage" section shows the
pinned revision, an honest "unknown — not yet refreshed" until a real
refresh happens, and — once refreshed — current status/revision, whether a
newer revision exists, supersession, and contradiction group/status;
`GraphHoverPanel` shows a one-line summary. The "Refresh current state"
button only ever appears on a node this can actually refresh.

**Visible Verification**: `scripts/generate_memory_lineage_fixture.py`
writes a real, schema-validated graph document with one pinned Memory
citation to `desktop/public/fixtures/memory-lineage-demo.json`, loadable via
`App.tsx`'s existing `?fixtureUrl=` dev escape hatch (Execution 08's
precedent). Proven live end to end against a real Memory store during this
execution: pinned-only view ("unknown — not yet refreshed") → refresh →
`active (rev 1)` → a real `record revise` in Memory → refresh again →
`active (rev 2)`, `newerRevisionAvailable: yes` — all through the real
Desktop Host, the real `memory_lineage_bridge.py`, and the real Memory CLI,
in a real browser.

Tests: `test_memory_temporal_lineage.py` (pure-logic: pinned parsing, every
Section E failure mode, evidence-backed-not-time-based staleness) and
`test_memory_lineage_bridge.py` (real Memory CLI subprocess: live pinned
revision, newer revision, superseded, open/resolved contradiction, Memory
unreachable, project isolation, old-graph-immutable-after-refresh, and a
static source scan proving no direct SQLite access anywhere in this path).
TypeScript: `refreshMemoryCitation.test.ts` (real end-to-end host operation),
plus `GraphHoverPanel`/`GraphInspector`/`PerformanceGraph` component tests
for the click-to-refresh flow and its inline error handling.

## Prompt-Scoped Graph Slicing, Projection Identity, Scale, and Accessibility (Midnight Execution 10)

Section A's server-side slice (`maxDepth`/`allowedLayers`/`maxNodes`/
`maxEdges`/continuation cursor) already existed from Execution 06; this
execution added the two pieces it was missing:

* **Stable truncation reasons.** `truncated: bool` alone couldn't say WHY —
  a new `truncationReasons` array (`"max_depth"`/`"layer_filter"`/
  `"max_nodes"`/`"max_edges"`) is populated at each of the four places
  `prompt_run_graph` already cuts the graph, in a fixed, machine-readable
  vocabulary a client can branch on without guessing.
* **Neighborhood expansion.** `focus_node` (Python param, `--focus-node`
  CLI flag, `focusNode` Host/wire field) EXPANDS the `maxDepth` window
  rather than re-centering it — the returned node set is the union of
  root's own reachability and `focus_node`'s, so a client that already
  rendered a truncated view can ask "show me more around this node"
  without losing what it had. `root` never changes away from the Prompt
  Run itself. Validated closed (`InvalidGraphFocusError`, exit code 5) for
  a malformed or foreign node id, independent of whether `maxDepth` was
  even supplied.

**Projection identity** (Section B): a new `projectionIdentity` object
(`project`, `root`, `graphSchemaVersion`, `graphAlgorithmMethod`/`Version`
— now publicly exported from `relationship_graph.py` rather than staying
module-private, `evidenceCheckpoint`) bundles everything a cache key needs
into one self-contained descriptor. `evidenceCheckpoint` is
`projection_store.ProjectionCheckpoint.generation` — Execution 05's
existing O(1)-verifiable ledger fingerprint, propagated up through
`_resolve_prompt_run` rather than discarded as it was before. Proven to
actually change when new evidence is appended (and stay stable when it
isn't) in `GraphProjectionIdentityTests`. This value is a lookup
fingerprint only, never treated as evidence itself.

**Cache** (Section C, `desktop/src/graph/graphCache.ts`): caches
LAYOUT COORDINATES only, not graph documents — a document-level cache was
considered and rejected, because a document's own `evidenceCheckpoint` is
only knowable AFTER the fetch that would populate the cache, so it can
never validate its own key without the same round-trip it exists to avoid.
Layout has no such problem: once a document is in hand, its
`projectionIdentity` is already known, so `buildGraphCacheKey()` (project,
root, graph schema/algorithm version, evidence checkpoint, slice, and an
optional Memory-checkpoint slot for a future cache whose value embeds live
Memory state) plus the exact visible node-id set is a safe, immediate cache
key. `GraphCache<T>` is a small bounded LRU with project isolation
structural in the key, not a filter. Wired into `PerformanceGraph.tsx`'s
layout effect: toggling a layer filter (or the on-demand tier) back to a
previously-seen exact node/edge set is a cache hit — no elk recomputation —
proven by a spy-counted `layoutGraph` call in
`PerformanceGraph.test.tsx`. `graphCache.test.ts` covers deterministic
keys, checkpoint-change invalidation, zero cross-project bleed, and LRU
eviction.

**Scale measurements** (Section D): `layoutGraph()` (elkjs, main thread,
layered/Sugiyama) measured at 50 / 200 / 1,000 / 5,000 synthetic nodes.
50 and 200 run automatically in `layoutBenchmark.test.ts` (~0.5-2s).
1,000 and 5,000 were measured manually (not run automatically — see below)
via `generate_graph_fixtures.py --graph-sizes 50 200 1000 5000`:

| Nodes | Edges | Layout time |
|---|---|---|
| 50 | 97 | ~0.5-1.1s |
| 200 | 397 | ~1-1.7s |
| 1,000 | 1,997 | **~34s** |
| 5,000 | 9,997 | **OOM — crashes even at an 8GB heap** |

This is a real, reproduced finding, not a projection: elkjs's layered
algorithm blows up non-linearly well before 1,000 nodes and cannot complete
at 5,000 regardless of available memory. It directly validates Section D's
premise ("the product does not need to show 5,000 by default") and its
escalation order — server-side slicing (`maxNodes=200` default, already in
place since Execution 06) and progressive disclosure (Section E's on-demand
tier, below) are doing real, necessary work today; a worker would only move
the 1,000-node slowness off the main thread, not fix the 5,000-node OOM;
a renderer/layout-algorithm swap (Sigma.js + a force-directed layout, per
Section D's step 4) is the honest next lever if the product ever needs
that scale, not attempted in this execution. `layoutBenchmark.test.ts`
deliberately does NOT run the 1,000/5,000 cases automatically — a 34s,
heap-exhausting case has no place in a suite run on every `npm test`.

**Default information priority** (Section E, display policy only — no
evidence is ever deleted): a new `priority_tier` field
(`visual_intelligence._priority_tier`, `"primary"` for Prompt Run/Agent
Run/ChangeSet/FileChange/Verification/Episode/Outcome, `"on_demand"` for
everything else — Session/Turn, Tool, Command, Symbols, Analysis, Memory,
similarity/history) is orthogonal to `layer` (a causal-domain grouping) and
computed structurally from entity kind, never caller-suppliable.
`PerformanceGraph.tsx` hides `on_demand`-tier nodes by default; a new
"Show on-demand evidence" toggle in `GraphControls.tsx` reveals them
instantly (the document already has them — this is rendering only).

**Evidence Inspector** (Section F): `GraphInspector`'s new "Relationships"
section (backed by `desktop/src/graph/relationships.ts`) lists every
inbound edge into the selected node — source label, semantic role, claim
kind, confidence, and uncertainty — answering "why is this node here,"
"why are these two connected," "is the source observed/derived/inferred,"
"what evidence reference," and "how certain" directly, without requiring
the reader to interpret the canvas. An "Expand neighborhood around this
node" button appears only when the view is actually truncated and the
caller can re-fetch with `focusNode` (`App.tsx`'s live path — never in the
dev `?fixtureUrl=` preview, which has no live Host to ask).

**Accessibility** (Section G): keyboard zoom (`+`/`-`/`0` on the
canvas, independent of React Flow's own mouse-driven zoom buttons — the
canvas is `tabIndex={0}`/`role="application"` with its own `aria-label`);
a screen-reader-only relationship list (`.visually-hidden`, never
`display:none`) narrating every visible edge as prose, since React Flow's
SVG edges carry no accessible text of their own; visible focus
(`:focus-visible` outlines, already present on nodes from Execution 07,
extended to the canvas); non-color distinction (node kind is always shown
as text, never color-only); reduced motion (`usePrefersReducedMotion`,
Execution 07, unchanged — zero-duration transitions); nothing hover-only
(`GraphHoverPanel`'s content, Memory lineage summary included, is always
also available via click on `GraphInspector`, by construction).

Tests: `test_graph_bridge.py`'s new `GraphProjectionIdentityTests` /
`GraphTruncationReasonTests` / `GraphNeighborhoodExpansionTests` (checkpoint
change/stability, all four truncation reasons, expansion union semantics,
malformed/foreign/inert focus handling, CLI flag wiring); `getPromptRunGraph
.test.ts`'s new real end-to-end `INVALID_FOCUS` and `projectionIdentity`
cases; `graphCache.test.ts` (14 cases: deterministic keys, checkpoint/
project/slice differentiation, LRU behavior); `PerformanceGraph.test.tsx`'s
new on-demand-default, relationships/expand-neighborhood, keyboard-zoom,
screen-reader-list, and layout-cache-reuse cases; `layoutBenchmark.test.ts`
(50/200 automated, 1,000/5,000 manual — see the scale table above).

Visible verification: the `?fixtureUrl=` dev escape hatch (same precedent
as Execution 08/09) proved, in a real browser, that a Memory citation node
is hidden by default and revealed by the on-demand toggle, and that
clicking it shows both the new "Relationships" section (the real inbound
`cites_memory` edge, its claim kind and uncertainty) and Execution 09's
"Memory lineage" section together, correctly, on the same node.

Gaps: the live Desktop Host path cannot yet demonstrate `focusNode`
end-to-end, because today's real capture pipeline (Executions 04-06,
unchanged) produces only bare, single-node Prompt Run graphs — there is
nothing beyond the root to expand into yet, the same structural limitation
Execution 08's `resolved_entities` already had. 1,280×800/1,440×900
window-size comparison and a live keyboard-zoom capture were not completed
in-browser (the Chrome extension disconnected mid-session); keyboard zoom
is instead covered by a real component test asserting the handler is wired
and does not throw, and the CSS uses no fixed viewport-width layout, so
both window sizes are expected, but not confirmed, to render equivalently.

## Repo Intelligent Performance-native fusion (Execution RI-13)

RI-01 through RI-12 already built almost everything this execution asks
for — `LineageReceipt` (RI-01) *is* the Performance Lineage Receipt,
`LearningPressure`/`score_path_pressure` (RI-02) *is* the learning-pressure
engine, `compile_question` (RI-02) *is* the question compiler, and
`repo_intelligence_pipeline.run_pipeline` (RI-12) *is* the canonical fusion
path (OBSERVE → SIGNAL → QUESTION → DISCOVER → SYNTHESIZE → GRAPH → EXPOSE
→ LEARN), reusing every stage function with no new domain logic of its own.
This execution closed the remaining gaps rather than rebuilding any of it:

* **The critical invariant is now enforced at the function boundary, not
  just by pipeline convention.** `discover()` (`repo_intelligence/discovery.py`)
  takes an optional `lineage_receipt` and raises `PermissionError` if one
  is missing on any job whose `trigger` is not `JobTrigger.USER_PULL` — "a
  proactive external research job cannot exist without a valid
  project-scoped Performance lineage receipt, except when the user
  explicitly asks." `run_pipeline` always supplies the originating signal's
  own receipt; `_build_job` now tags `USER_PULL` on an explicit user pull
  instead of always `MAINTENANCE` (mirroring `learning_loop.py`'s own
  trigger derivation), so the carve-out is meaningful.
* **Jobs are persisted** (`RepoIntelligenceStore.upsert_job`/`get_job`/
  `list_jobs`), plus two small link tables — `signal_receipts` (a signal's
  evidence, upserted independently of its receipt, is now look-up-able) and
  `question_jobs` (which job(s) a compiled question was opened/reopened
  under). Pure store-layer bookkeeping; no `repo_intelligence/contracts.py`
  schema changed.
* **Fusion query surfaces** (`repo_intelligence_query_api.RepoIntelligenceQueryAPI`,
  mirroring `query_api.PerformanceQueryAPI`'s read-facade shape):
  `active_learning_pressures`, `why_this_topic_now`, `evidence_behind_pressure`,
  `internal_knowledge_sufficiency`, `research_jobs_for_pressure`, and
  `exposure_outcomes` — each composes records the pipeline already
  persisted, never a new derived fact.
* **Anomaly and personal-learning reuse** (`repo_intelligence_fusion.py`,
  the integration layer alongside `repo_intelligence_pipeline.py` --
  outside the `repo_intelligence/` foundation package's own
  architecture-tested, narrower Performance-import allowlist):
  `classify_unusualness` calls straight into `anomaly.build_baseline`/
  `detect_anomalies` (the same median/MAD robust-z baseline used for
  prompt-run anomalies) so "this is unusual" stays a separate, honestly
  degrading judgment from "this is friction" (`unusual ≠ bad`);
  `match_prior_internal_answer` calls straight into
  `personal_learning.match_history` so "a prior internally-answered
  question already covers this component" reuses the canonical matcher
  instead of a second one. `why_this_topic_now` wires both in as
  best-effort annotations — `None` means "not enough history to say,"
  never an invented value.
* **Recommendation/outcome and AI-accounting reuse confirmed, not
  duplicated**: RI-01's `LearningOutcome`/`AssociationKind` already mirror
  `recommendation.evaluate_recommendation`'s associative-never-causal
  discipline; `CostRecord`/`CostResourceKind` already unify model, search,
  and fetch spend under one typed ledger, reconciled through
  `AIAccountingBudgetMeter` (`repo_intelligence_adapters.py`, itself backed
  by `ai_accounting.py`'s shared accounting vocabulary).

Verification: `python -m pytest tests/test_repo_intelligence_discovery.py
tests/test_repo_intelligence_store.py tests/test_repo_intelligence_fusion.py
tests/test_repo_intelligence_query_api.py
tests/test_repo_intelligence_fusion_scenarios.py -v` — the last file drives
the doc's own nine verification scenarios (active healthy refactor, chronic
repeated failure, unusual-but-successful one-off, recurring component with
a fresh vs. a stale internal answer, degraded/no-Performance bridge,
cross-project attack, rerun/restart idempotency, cost-accounting
reconciliation) end-to-end through the real pipeline and fixture ports.

## Repo Intelligent temporal knowledge, cross-repository analogy & attention (Execution RI-14)

RI-01 through RI-13 had already built most of the temporal and attention
machinery this execution asks for. `GraphLink` and `ProjectInsight`
(`repo_intelligence/contracts.py`) already carry `first_seen`/`last_seen`,
`valid_from`/`valid_to`, `superseded_by`, and `is_stale`/`is_superseded`;
`project_graph.active_links`/`stale_links` already honor temporal decay
without deleting anything; `evidence_ids`/`performance_evidence_ids`/
`repository_change_refs` already anchor to arbitrary Performance identity
kinds, including `EntityKind.EPISODE`, `CHANGE_SET`, and
`REPOSITORY_SNAPSHOT` — so "preserve association to Performance episodes/
change sets and repository snapshots" needed no new plumbing. Attention
gating — quiet queue, cooldown, dismiss suppression, protected focus, and
user-pull override — is fully implemented by
`terminal_learning.decide_terminal_card`/`TerminalContext`/`Exposure`
(RI-06); this execution reuses that gate rather than rebuilding it. This
execution closed the three capabilities that genuinely did not exist yet:

* **`AnalogyRecord` and a structural comparison engine that cannot be fed
  keyword-only similarity** (`repo_intelligence/contracts.py`'s new
  `AnalogyDimension`/`DimensionComparison`/`AnalogyRecord`,
  `repo_intelligence/analogy.py`'s new `RepositoryProfile`/
  `compare_repositories`/`build_analogy_record`). `RepositoryProfile` has
  no description/README field — only typed structural facts (architectural
  role, dependencies, protocols, data-flow patterns, failure modes, test
  strategy, scale class) — so the engine has nothing to match keywords
  against; a fact neither side reports comes back `comparable=False` with
  an honest reason, never a fabricated similarity score. `AnalogyRecord`
  fails closed unless every one of the six spec dimensions is addressed
  exactly once, at least one is comparable, and at least one meaningful
  difference is stated. Its identity is content-addressed on the verdict
  (mirroring `project_insight_identity`'s statement digest), so re-running
  the same comparison is idempotent but a genuinely different verdict for
  the same (project, external repository, internal entity) gets its own
  identity and can be `superseded_by`-linked instead of silently
  overwritten. `project_graph._add_analogies` wires `AnalogyRecord`s into
  the overlay as `EXTERNAL_ANALOGUE_OF` edges (previously-defined
  `GraphRelation` members with zero producers before this execution), and
  links two analogies for the *same* internal entity `CONTRADICTS` when
  their comparable-dimension verdicts diverge by more than a threshold —
  both stay in the overlay; neither is deleted.
* **The exact attention-ranking formula and a real, finite attention
  ledger separate from compute budget** (`repo_intelligence/attention.py`'s
  new `AttentionFactors` — `learning_pressure × evidence_strength ×
  novelty × expected_learning_value × timing_fit − (redundancy +
  interruption_cost + uncertainty + stale_risk)`, exactly as specified —
  plus `rank_attention_candidates`, and `AttentionBudgetLimits`/
  `AttentionSpend`/`attention_spend`/`attention_budget_allows`).
  `attention_spend` computes spend from durable `Exposure` history alone
  (never the cost ledger): only exposures that actually reached the user
  on an interrupting channel count, so `QUIET_QUEUE`/`SUPPRESSED` events
  — never having reached the user — cost nothing. This is a genuinely
  separate, consumable ceiling from `cost_quality.BudgetLedger`, not a
  second bool flag.
* **The unique release metric** (`repo_intelligence/release_metric.py`'s
  new `useful_project_learning`/`user_attention_cost`/
  `normalized_compute_cost`/`ReleaseMetric`/`compute_release_metric`) —
  `useful_project_learning / (user_attention_cost + normalized_compute_cost)`,
  composed entirely from already-persisted `LearningOutcome`/`Exposure`/
  `CostRecord` history. A dismissed exposure still costs attention; an
  undefined ratio (nothing spent yet) returns `None`, never a fabricated
  zero or infinity — so it can never be gamed by raising exposure count
  alone.
* **Store and query-API wiring**: `RepoIntelligenceStore.upsert_analogy_record`/
  `list_analogy_records`/`analogies_for_entity` (a new rebuildable-cache
  table, cleared by `discard_rebuildable_state` alongside signals/receipts/
  graph links); `RepoIntelligenceQueryAPI.active_analogies`/
  `attention_budget_status`/`release_metric`.
* **A latent `validate_overlay` bug, fixed as a prerequisite**: it compared
  `GraphLink.project` (an `Identity` object) directly against
  `ProjectKnowledgeGraph.project` (its canonical string), so every graph's
  integrity check reported a false "cross-project link" violation on every
  link, for every execution back through RI-03. The existing tests only
  asserted `.ok` was not `None`, so this went unnoticed. Fixed to compare
  `link.project.canonical`; the two pre-existing assertions were tightened
  to `assertTrue(...)` to prove it.

Not done in this execution, left as an honest gap: wiring `AnalogyRecord`
generation into `repo_intelligence_pipeline.run_pipeline`'s own OBSERVE→
...→LEARN stages (today `build_analogy_record` is a pure function a caller
invokes directly, the same way RI-02's `score_path_pressure` was before
RI-12 wired it into the pipeline) — a `RepositoryProfile` still has to be
supplied from outside; nothing here fetches or profiles an external
repository on its own. `_analogies_contradict`'s divergence threshold
(0.5) is a first cut, not calibrated against real data.

Verification: `python -m pytest tests/test_repo_intelligence_analogy.py
tests/test_repo_intelligence_attention.py
tests/test_repo_intelligence_release_metric.py
tests/test_repo_intelligence_project_graph.py
tests/test_repo_intelligence_store.py tests/test_repo_intelligence_query_api.py
tests/test_repo_intelligence_temporal_analogy_attention_scenarios.py -v` — the
last file drives the doc's own eight named verification scenarios (temporal
supersession, contradictory external sources, structurally similar
repository with a different language, keyword-similar but structurally
irrelevant repository, stale insight, repeated dismissal, quiet mode, and a
later Performance association that stays statistical/associative, never
causal) end-to-end through the real contracts.

**GOAL: YES.** All three requirement groups (temporal graph, external
analogy, attention budget) plus the unique release metric are implemented
and verified against the spec's own eight named scenarios; the one honest
gap is pipeline auto-wiring for analogy generation, called out above rather
than silently left implicit.
