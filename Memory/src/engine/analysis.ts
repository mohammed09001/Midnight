/**
 * Analysis → Memory proposal integration (Task 29).
 *
 * Allows the Analysis engine to propose REUSABLE ARCHITECTURAL FINDINGS only
 * through EVIDENCE-LINKED candidates in the intake stream — NEVER direct
 * record insertion. Analysis records stay EXTERNAL (referenced by evidenceRef
 * `{engine: "analysis", ref}` only, never embedded).
 *
 * - Evidence-linked: every finding MUST reference ≥ 1 Analysis record
 *   (bounded to ≤ MAX_ANALYSIS_EVIDENCE_PER_FINDING refs).
 * - sourceKind `analysis_evidence` (authority tier "analysis", docs/AUTHORITY.md),
 *   epistemicClass `derived` by default — an architectural finding is
 *   intelligence derived from analysis evidence, never claimed as observed.
 * - Bounded: a batch is capped at MAX_ANALYSIS_FINDINGS_PER_BATCH; excess
 *   findings are explicitly rejected, never silently dropped.
 * - Explicit failure: a finding that fails validation or intake authorization
 *   is reported in `rejected` with a typed code/message; the rest of the
 *   batch still succeeds.
 */
import type { ActorInput } from "./records.ts";
import type { EpistemicClass, MemoryCandidate, RecordKind } from "../contracts/types.ts";
import { addCandidateImpl } from "./records.ts";
import { LIMITS } from "./validation.ts";
import type { MemoryStore } from "./store.ts";

/** The Analysis engine's canonical evidence-engine name. */
export const ANALYSIS_ENGINE = "analysis" as const;

/** Default canonical caller key for the Analysis engine. */
export const ANALYSIS_DEFAULT_CALLER = { kind: "engine", name: "analysis" } as const;

/** Bounded batch: at most this many architectural findings per submission. */
export const MAX_ANALYSIS_FINDINGS_PER_BATCH = 50;

/** Bounded evidence: at most this many Analysis record refs per finding. */
export const MAX_ANALYSIS_EVIDENCE_PER_FINDING = 8;

export interface AnalysisFinding {
  /** Reusable architectural finding subject. */
  subject: string;
  /** The finding statement — NOT the Analysis payload. */
  content: string;
  /** Stable Analysis record id(s) backing the finding (required, bounded). */
  evidenceRefs: string[];
  note?: string;
  kind?: RecordKind;
  /** Default "derived" — a finding is intelligence derived from analysis. */
  epistemicClass?: EpistemicClass;
  confidence?: number;
  tags?: string[];
  /** Content producer (default: the Analysis engine). */
  actor?: ActorInput;
  method?: string;
  reason?: string;
}

export interface AnalysisRejection {
  finding: { subject: string; evidenceRefs: string[] };
  code: string;
  message: string;
}

export interface AnalysisProposalResult {
  accepted: MemoryCandidate[];
  rejected: AnalysisRejection[];
}

function validateFinding(
  finding: AnalysisFinding,
): { evidenceRefs: string[]; note?: string } | { error: string } {
  if (typeof finding.subject !== "string" || finding.subject.trim().length === 0) {
    return { error: "finding.subject is required" };
  }
  if (typeof finding.content !== "string" || finding.content.trim().length === 0) {
    return { error: "finding.content is required" };
  }
  if (!Array.isArray(finding.evidenceRefs) || finding.evidenceRefs.length === 0) {
    return { error: "finding.evidenceRefs is required: Analysis findings must be evidence-linked" };
  }
  if (finding.evidenceRefs.length > MAX_ANALYSIS_EVIDENCE_PER_FINDING) {
    return { error: `finding.evidenceRefs exceeds ${MAX_ANALYSIS_EVIDENCE_PER_FINDING} refs` };
  }
  const refs: string[] = [];
  for (const ref of finding.evidenceRefs) {
    if (typeof ref !== "string" || ref.trim().length === 0) {
      return { error: "finding.evidenceRefs entries must be non-empty Analysis record ids" };
    }
    if (ref.length > LIMITS.ref) {
      return { error: `finding.evidenceRefs entry exceeds ${LIMITS.ref} characters` };
    }
    refs.push(ref.trim());
  }
  return { evidenceRefs: refs, ...(finding.note !== undefined && finding.note.length > 0 ? { note: finding.note } : {}) };
}

/**
 * Transform bounded Analysis architectural findings into Memory candidates
 * through the canonical intake pipeline. Analysis records stay external
 * (referenced by evidenceRef engine "analysis"). Returns per-finding
 * accept/reject results — a failed finding never aborts the batch.
 */
export function proposeAnalysisImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  findings: AnalysisFinding[],
  options: { caller?: ActorInput } = {},
): AnalysisProposalResult {
  if (!Array.isArray(findings)) {
    throw new TypeError("findings must be an array");
  }
  const caller = options.caller ?? ANALYSIS_DEFAULT_CALLER;
  const accepted: MemoryCandidate[] = [];
  const rejected: AnalysisRejection[] = [];

  findings.slice(0, MAX_ANALYSIS_FINDINGS_PER_BATCH).forEach((finding) => {
    const validation = validateFinding(finding);
    if ("error" in validation) {
      rejected.push({
        finding: { subject: finding.subject, evidenceRefs: Array.isArray(finding.evidenceRefs) ? finding.evidenceRefs : [] },
        code: "MEMORY_VALIDATION_FAILED",
        message: validation.error,
      });
      return;
    }
    try {
      const candidate = addCandidateImpl(store, {
        scope: scopeOrProjectKey,
        kind: finding.kind ?? "note",
        subject: finding.subject,
        content: finding.content,
        actor: finding.actor ?? caller,
        method: finding.method ?? "architectural_analysis",
        epistemicClass: finding.epistemicClass ?? "derived",
        confidence: finding.confidence ?? 0.7,
        evidenceRefs: validation.evidenceRefs.map((ref) => ({
          engine: ANALYSIS_ENGINE,
          ref,
          ...(validation.note !== undefined ? { note: validation.note } : {}),
        })),
        tags: finding.tags,
        sourceKind: "analysis_evidence",
        reason:
          finding.reason ??
          `architectural finding backed by ${validation.evidenceRefs.join(", ")}`,
        caller,
      });
      accepted.push(candidate);
    } catch (err) {
      rejected.push({
        finding: { subject: finding.subject, evidenceRefs: validation.evidenceRefs },
        code: err instanceof Error && "code" in err ? String((err as { code: string }).code) : "MEMORY_ENGINE_UNEXPECTED",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  });

  // Excess findings beyond the bounded batch are explicitly rejected.
  for (const finding of findings.slice(MAX_ANALYSIS_FINDINGS_PER_BATCH)) {
    rejected.push({
      finding: { subject: finding.subject, evidenceRefs: Array.isArray(finding.evidenceRefs) ? finding.evidenceRefs : [] },
      code: "MEMORY_VALIDATION_FAILED",
      message: `batch exceeds ${MAX_ANALYSIS_FINDINGS_PER_BATCH} findings`,
    });
  }

  return { accepted, rejected };
}