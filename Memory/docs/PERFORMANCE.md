# Library Memory Engine — Performance → Memory Proposals (v1.11.0)

Implemented in `src/engine/performance.ts`. Task 27, Phase V.

## Principle

The Performance engine submits BOUNDED, EVIDENCE-BACKED lessons through the
versioned contract (`memory.performance.propose` / `engine.proposePerformanceLessons`).
Each lesson becomes a Memory CANDIDATE in the intake stream (docs/INTAKE.md) —
NEVER a direct record — and Performance records stay EXTERNAL, referenced only
by evidenceRef (`{engine: "performance", ref}`). Promotion remains
policy-gated (docs/PROMOTION.md).

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

## Agent neutrality / game independence

The adapter is a pure transformation over the existing intake pipeline — no LLM,
no Performance store access (records stay external), no game dependency.
Terminal surface: `performance propose --scope K --subject S --content T
--evidence perf:ID [--evidence perf:ID2 …]`.