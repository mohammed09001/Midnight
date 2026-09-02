/**
 * Performance → Memory proposal integration (Task 27).
 *
 * Accepts BOUNDED, EVIDENCE-BACKED lessons from the Performance engine
 * through the versioned contract, keeping Performance records EXTERNAL
 * (referenced by evidenceRef `{engine: "performance_evidence", ref}` only —
 * never embedded). Each lesson becomes a Memory CANDIDATE in the intake
 * stream via the canonical candidate pipeline (docs/INTAKE.md) — never a
 * direct record. Promotion remains policy-gated (docs/PROMOTION.md): a lesson
 * backed by ≥ 2 distinct Performance evidence refs matches
 * `repeated_evidence_backed_lesson`.
 *
 * - Evidence-backed: every lesson MUST reference ≥ 1 Performance record
 *   (and is bounded to ≤ MAX_PERFORMANCE_EVIDENCE_PER_LESSON refs).
 * - Bounded: a batch is capped at MAX_PERFORMANCE_LESSONS_PER_BATCH; excess
 *   lessons are rejected explicitly, never silently dropped.
 * - Explicit failure: a lesson that fails validation or intake authorization
 *   is reported in `rejected` with a typed code/message; the rest of the
 *   batch still succeeds.
 */
import type {
  ActorInput,
} from "./records.ts";
import type {
  EpistemicClass,
  MemoryCandidate,
  RecordKind,
} from "../contracts/types.ts";
import { addCandidateImpl } from "./records.ts";
import { LIMITS } from "./validation.ts";
import type { MemoryStore } from "./store.ts";

/** The Performance engine's canonical evidence-engine name (evidence refs). */
export const PERFORMANCE_ENGINE = "performance" as const;

/** The Performance evidence SourceKind (authority: verified_source). */
export const PERFORMANCE_SOURCE_KIND = "performance_evidence" as const;

/** Default canonical caller key for the Performance engine. */
export const PERFORMANCE_DEFAULT_CALLER = { kind: "engine", name: "performance" } as const;

/** Bounded batch: at most this many lessons per submission. */
export const MAX_PERFORMANCE_LESSONS_PER_BATCH = 50;

/** Bounded evidence: at most this many Performance record refs per lesson. */
export const MAX_PERFORMANCE_EVIDENCE_PER_LESSON = 8;

export interface PerformanceLesson {
  /** Lesson subject (the durable statement's subject). */
  subject: string;
  /** Lesson content — the Memory-side statement, not the Performance payload. */
  content: string;
  /** Stable Performance record id(s) backing the lesson (required, bounded). */
  evidenceRefs: string[];
  /** Optional note attached to the evidence references. */
  note?: string;
  kind?: RecordKind;
  /** Default "derived" — a lesson is intelligence derived from evidence. */
  epistemicClass?: EpistemicClass;
  confidence?: number;
  tags?: string[];
  /** Content producer (default: the Performance engine). */
  actor?: ActorInput;
  method?: string;
  /** Why this proposal exists (default filled from the evidence refs). */
  reason?: string;
}

export interface PerformanceRejection {
  lesson: { subject: string; evidenceRefs: string[] };
  code: string;
  message: string;
}

export interface PerformanceProposalResult {
  accepted: MemoryCandidate[];
  rejected: PerformanceRejection[];
}

/** Validate a lesson's bounded, evidence-backed shape without writing. */
function validateLesson(
  lesson: PerformanceLesson,
): { evidenceRefs: string[]; note?: string } | { error: string } {
  if (typeof lesson.subject !== "string" || lesson.subject.trim().length === 0) {
    return { error: "lesson.subject is required" };
  }
  if (typeof lesson.content !== "string" || lesson.content.trim().length === 0) {
    return { error: "lesson.content is required" };
  }
  if (!Array.isArray(lesson.evidenceRefs) || lesson.evidenceRefs.length === 0) {
    return { error: "lesson.evidenceRefs is required: Performance lessons must be evidence-backed" };
  }
  if (lesson.evidenceRefs.length > MAX_PERFORMANCE_EVIDENCE_PER_LESSON) {
    return { error: `lesson.evidenceRefs exceeds ${MAX_PERFORMANCE_EVIDENCE_PER_LESSON} refs` };
  }
  const refs: string[] = [];
  for (const ref of lesson.evidenceRefs) {
    if (typeof ref !== "string" || ref.trim().length === 0) {
      return { error: "lesson.evidenceRefs entries must be non-empty Performance record ids" };
    }
    if (ref.length > LIMITS.ref) {
      return { error: `lesson.evidenceRefs entry exceeds ${LIMITS.ref} characters` };
    }
    refs.push(ref.trim());
  }
  return { evidenceRefs: refs, ...(lesson.note !== undefined && lesson.note.length > 0 ? { note: lesson.note } : {}) };
}

/**
 * Transform bounded Performance lessons into Memory candidates through the
 * canonical intake pipeline. Performance records stay external (referenced
 * by evidenceRef, engine "performance_evidence"). Returns per-lesson
 * accept/reject results — a failed lesson never aborts the batch.
 */
export function proposePerformanceLessonsImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  lessons: PerformanceLesson[],
  options: { caller?: ActorInput } = {},
): PerformanceProposalResult {
  if (!Array.isArray(lessons)) {
    throw new TypeError("lessons must be an array");
  }
  const caller = options.caller ?? PERFORMANCE_DEFAULT_CALLER;
  const accepted: MemoryCandidate[] = [];
  const rejected: PerformanceRejection[] = [];

  lessons.slice(0, MAX_PERFORMANCE_LESSONS_PER_BATCH).forEach((lesson) => {
    const validation = validateLesson(lesson);
    if ("error" in validation) {
      rejected.push({
        lesson: { subject: lesson.subject, evidenceRefs: Array.isArray(lesson.evidenceRefs) ? lesson.evidenceRefs : [] },
        code: "MEMORY_VALIDATION_FAILED",
        message: validation.error,
      });
      return;
    }
    try {
      const candidate = addCandidateImpl(store, {
        scope: scopeOrProjectKey,
        kind: lesson.kind ?? "observation",
        subject: lesson.subject,
        content: lesson.content,
        actor: lesson.actor ?? caller,
        method: lesson.method ?? "performance_lesson",
        epistemicClass: lesson.epistemicClass ?? "derived",
        confidence: lesson.confidence ?? 0.8,
        evidenceRefs: validation.evidenceRefs.map((ref) => ({
          engine: PERFORMANCE_ENGINE,
          ref,
          ...(validation.note !== undefined ? { note: validation.note } : {}),
        })),
        tags: lesson.tags,
        sourceKind: PERFORMANCE_SOURCE_KIND,
        reason:
          lesson.reason ??
          `performance lesson backed by ${validation.evidenceRefs.join(", ")}`,
        caller,
      });
      accepted.push(candidate);
    } catch (err) {
      rejected.push({
        lesson: { subject: lesson.subject, evidenceRefs: validation.evidenceRefs },
        code: err instanceof Error && "code" in err ? String((err as { code: string }).code) : "MEMORY_ENGINE_UNEXPECTED",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  });

  // Excess lessons beyond the bounded batch are explicitly rejected.
  for (const lesson of lessons.slice(MAX_PERFORMANCE_LESSONS_PER_BATCH)) {
    rejected.push({
      lesson: { subject: lesson.subject, evidenceRefs: Array.isArray(lesson.evidenceRefs) ? lesson.evidenceRefs : [] },
      code: "MEMORY_VALIDATION_FAILED",
      message: `batch exceeds ${MAX_PERFORMANCE_LESSONS_PER_BATCH} lessons`,
    });
  }

  return { accepted, rejected };
}