# Midnight Memory — Performance → Memory Proposals (v1.14.0)

Implemented in `src/engine/performance.ts`. Task 27, Phase V.

## Principle

The Performance engine submits BOUNDED, EVIDENCE-BACKED lessons through the
versioned contract (`memory.performance.propose` / `engine.proposePerformanceLessons`).
Each lesson becomes a Memory CANDIDATE in the intake stream (docs/INTAKE.md) —
NEVER a direct record — and Performance records stay EXTERNAL, referenced only
by evidenceRef (`{engine: "performance", ref}`). Promotion remains
policy-gated (docs/PROMOTION.md).

Memory does not own Performance's raw records, prompt/tool/agent execution
history, or Episodes — only these bounded lesson statements plus references
into that history (docs/BOUNDARY.md Section 0).

## Lesson shape

```ts
interface PerformanceLesson {
  subject: string;          // durable statement subject
  content: string;          // the lesson — NOT the Performance payload
  evidenceRefs: string[];   // Performance record id(s), required + bounded
  note?: string;
  kind?: RecordKind;        // default "observation"
  epistemicClass?: EpistemicClass; // default "derived" (derived from evidence)
  confidence?: number;      // default 0.8
  tags?: string[];
  actor?: ActorInput;       // content producer (default: the Performance engine)
  method?: string;          // default "performance_lesson"
  reason?: string;          // why the proposal exists (default filled)
  idempotencyKey?: string;  // Task 7 (Execution 03): same key -> same candidate, no duplicate
}
```

## Bounded + evidence-backed

- **Evidence-backed**: every lesson MUST reference ≥ 1 Performance record
  (`evidenceRefs`); a lesson without evidence is rejected
  (`MEMORY_VALIDATION_FAILED`).
- **Bounded evidence**: ≤ `MAX_PERFORMANCE_EVIDENCE_PER_LESSON` (8) refs per
  lesson.
- **Bounded batch**: ≤ `MAX_PERFORMANCE_LESSONS_PER_BATCH` (50) lessons per
  submission; excess lessons are explicitly rejected, never silently dropped.

## Intake + authorization

Lessons go through the canonical candidate pipeline with `sourceKind:
"performance_evidence"` (authority: verified_source), `evidenceRefs` engine
`"performance"`, and the caller default `engine:performance`. Under an
allowlist intake policy the caller must be authorized — otherwise the lesson is
rejected (`MEMORY_INTAKE_UNAUTHORIZED`) and reported.

## Result + failures

`{accepted: MemoryCandidate[], rejected: Array<{lesson, code, message}>}` — a
failed lesson never aborts the batch; each rejection carries a typed code.

## Promotion

A Performance lesson backed by ≥ 2 DISTINCT evidence refs matches
`repeated_evidence_backed_lesson` (promotion still requires a non-agent
approver). A single-evidence lesson is retained in the stream awaiting a
policy match or human decision.

## Cross-language transport

`Performance/midnight_performance/memory_bridge.py` is the concrete
Python-side implementation of this contract: it builds
`memory.performance.propose` envelopes and calls Memory's CLI `contract
call` surface as a subprocess (`node --experimental-strip-types
src/cli/cli.ts contract call --operation memory.performance.propose
--request '<json>' --version <v>`), parsing the full versioned response
envelope from stdout. It never opens Memory's SQLite store directly. See
`Performance/README.md` for the bridge's typed failure modes
(`MemoryUnavailableError`, `MemoryContractError`).

## Delivery semantics (Task 9, Execution 03)

Duplicate delivery of the same lesson (e.g. a client-side retry) must not
create uncontrolled duplicate candidates: pass `idempotencyKey` and a
replayed proposal returns the SAME candidate identity (`addCandidateImpl`'s
existing replay-safe intake, `src/engine/records.ts`, including a
unique-index race guard for concurrent duplicate delivery). The Python
bridge's lesson builders (`lesson_from_sealed_envelope`,
`lesson_from_qualified_claim`) set a deterministic `idempotencyKey` by
default, so callers get this for free.

`Performance/midnight_performance/memory_bridge.py`'s
`call_memory_cli_with_retry` bounds retries to transient failures only
(`MemoryUnavailableError` — process/timeout/parse failure): a deterministic
rejection (`MemoryContractError`, e.g. `MEMORY_VALIDATION_FAILED`,
`MEMORY_INTAKE_UNAUTHORIZED`, `MEMORY_CONTRACT_MISMATCH`) is never retried,
since retrying it cannot succeed. Proven end to end (real subprocess calls,
not mocks) in `Performance/tests/test_memory_bridge.py`'s
`MemoryBridgeDeliverySemanticsTests`.

## Privacy backstop (Task 17, Execution 06)

Lesson `subject`/`content`/`note` are always caller-authored, never a copy
of Performance's raw payload — but as a structural backstop, not a
substitute for that discipline, `Performance/midnight_performance/memory_bridge.py`'s
lesson builders pass this text through `redact_sensitive_text` (the same
secret/email pattern `PrivacyGuard` applies to `Observation.payload` fields,
`Performance/midnight_performance/privacy.py`) before it ever crosses to
Memory. A stray secret or email that slips into caller-authored text is
caught here, before the propose call — verified end to end (a leaked
secret never appears in the resulting candidate's stored content or in
Memory's emitted events) in `Performance/tests/test_memory_bridge.py`'s
`MemoryBridgePrivacyRedactionTests`.

## Agent neutrality / game independence

The adapter is a pure transformation over the existing intake pipeline — no LLM,
no Performance store access (records stay external), no game dependency.
Terminal surface: `performance propose --scope K --subject S --content T
--evidence perf:ID [--evidence perf:ID2 …] [--idempotency-key K]`.