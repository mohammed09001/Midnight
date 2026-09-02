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

Run the verification suite with `python -m unittest discover -s tests -v`.
