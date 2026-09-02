/**
 * Study → Memory proposal integration (Task 28).
 *
 * Allows VERIFIED Study findings and USER ANNOTATIONS to become Memory
 * CANDIDATES in the intake stream, carrying Study / version / source-revision
 * provenance — while Study records stay EXTERNAL (referenced by evidenceRef
 * `{engine: "study_document", ref}` only, never embedded).
 *
 * - Verified Study finding: sourceKind `study_finding`, epistemicClass
 *   `observed` by default, referencing the study finding's Study id + version
 *   + source revision. Promotion-eligible via `verified_study_fact`
 *   (docs/PROMOTION.md).
 * - User annotation: sourceKind `user_note`, referencing the same Study
 *   provenance (an annotation annotates a specific study version/source
 *   revision). A user note observed → evidence-backed.
 * - Bounded: a batch is capped at MAX_STUDY_PROPOSALS_PER_BATCH; excess
 *   proposals are explicitly rejected, never silently dropped.
 * - Explicit failure: a proposal that fails validation or intake
 *   authorization is reported in `rejected` with a typed code/message; the
 *   rest of the batch still succeeds.
 */
import type { ActorInput } from "./records.ts";
import type { EpistemicClass, MemoryCandidate, RecordKind } from "../contracts/types.ts";
import { addCandidateImpl } from "./records.ts";
import { LIMITS } from "./validation.ts";
import type { MemoryStore } from "./store.ts";

/** The Study engine's canonical evidence-engine name. */
export const STUDY_ENGINE = "study_document" as const;

/** Default canonical caller key for the Study engine. */
export const STUDY_DEFAULT_CALLER = { kind: "engine", name: "study_document" } as const;

/** Bounded batch: at most this many Study proposals per submission. */
export const MAX_STUDY_PROPOSALS_PER_BATCH = 50;

export type StudyProposalKind = "finding" | "annotation";

export interface StudyProposal {
  /** "finding" = verified Study finding; "annotation" = user annotation. */
  type: StudyProposalKind;
  subject: string;
  content: string;
  /** Stable Study id (external, referenced by evidenceRef). */
  studyId: string;
  /** Study version (Study/version/source-revision provenance). */
  version: string;
  /** Source revision (Study/version/source-revision provenance). */
  sourceRevision: string;
  /** Optional note on the evidence ref (e.g. the finding id / section). */
  note?: string;
  kind?: RecordKind;
  epistemicClass?: EpistemicClass;
  confidence?: number;
  tags?: string[];
  /** Content producer (default: the Study engine; set for user annotations). */
  actor?: ActorInput;
  method?: string;
  reason?: string;
}

export interface StudyRejection {
  proposal: { type: StudyProposalKind; subject: string; studyId: string };
  code: string;
  message: string;
}

export interface StudyProposalResult {
  accepted: MemoryCandidate[];
  rejected: StudyRejection[];
}

/**
 * Canonical evidence ref carrying the Study/version/source-revision
 * provenance, by reference to the external Study engine.
 */
export function studyEvidenceRef(
  studyId: string,
  version: string,
  sourceRevision: string,
  note?: string,
): { engine: typeof STUDY_ENGINE; ref: string; note?: string } {
  const ref = `${studyId}#v${version}#rev${sourceRevision}`;
  return note !== undefined && note.length > 0
    ? { engine: STUDY_ENGINE, ref, note }
    : { engine: STUDY_ENGINE, ref };
}

function validateProposal(
  proposal: StudyProposal,
): { evidenceRef: ReturnType<typeof studyEvidenceRef>; reason: string } | { error: string } {
  if (proposal.type !== "finding" && proposal.type !== "annotation") {
    return { error: "proposal.type must be 'finding' or 'annotation'" };
  }
  if (typeof proposal.subject !== "string" || proposal.subject.trim().length === 0) {
    return { error: "proposal.subject is required" };
  }
  if (typeof proposal.content !== "string" || proposal.content.trim().length === 0) {
    return { error: "proposal.content is required" };
  }
  for (const [field, value] of [
    ["studyId", proposal.studyId],
    ["version", proposal.version],
    ["sourceRevision", proposal.sourceRevision],
  ] as const) {
    if (typeof value !== "string" || value.trim().length === 0) {
      return { error: `proposal.${field} is required (Study/version/source-revision provenance)` };
    }
    if (value.trim().length > LIMITS.ref) {
      return { error: `proposal.${field} exceeds ${LIMITS.ref} characters` };
    }
  }
  const evidenceRef = studyEvidenceRef(
    proposal.studyId.trim(),
    proposal.version.trim(),
    proposal.sourceRevision.trim(),
    proposal.note,
  );
  if (evidenceRef.ref.length > LIMITS.ref) {
    return { error: `proposal study evidence ref exceeds ${LIMITS.ref} characters` };
  }
  const reason =
    proposal.reason ??
    `Study ${proposal.type} from ${evidenceRef.ref}`;
  return { evidenceRef, reason };
}

/**
 * Transform bounded Study findings + user annotations into Memory candidates
 * through the canonical intake pipeline. Study records stay external
 * (referenced by evidenceRef engine "study_document"). Returns per-proposal
 * accept/reject results — a failed proposal never aborts the batch.
 */
export function proposeStudyImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  proposals: StudyProposal[],
  options: { caller?: ActorInput } = {},
): StudyProposalResult {
  if (!Array.isArray(proposals)) {
    throw new TypeError("proposals must be an array");
  }
  const caller = options.caller ?? STUDY_DEFAULT_CALLER;
  const accepted: MemoryCandidate[] = [];
  const rejected: StudyRejection[] = [];

  proposals.slice(0, MAX_STUDY_PROPOSALS_PER_BATCH).forEach((proposal) => {
    const validation = validateProposal(proposal);
    if ("error" in validation) {
      rejected.push({
        proposal: { type: proposal.type, subject: proposal.subject, studyId: proposal.studyId },
        code: "MEMORY_VALIDATION_FAILED",
        message: validation.error,
      });
      return;
    }
    try {
      const isFinding = proposal.type === "finding";
      const candidate = addCandidateImpl(store, {
        scope: scopeOrProjectKey,
        kind: proposal.kind ?? (isFinding ? "fact" : "note"),
        subject: proposal.subject,
        content: proposal.content,
        actor: proposal.actor ?? caller,
        method: proposal.method ?? (isFinding ? "study_finding" : "user_annotation"),
        epistemicClass: proposal.epistemicClass ?? "observed",
        confidence: proposal.confidence ?? (isFinding ? 0.9 : 0.8),
        evidenceRefs: [validation.evidenceRef],
        tags: proposal.tags,
        sourceKind: isFinding ? "study_finding" : "user_note",
        reason: validation.reason,
        caller,
      });
      accepted.push(candidate);
    } catch (err) {
      rejected.push({
        proposal: { type: proposal.type, subject: proposal.subject, studyId: proposal.studyId },
        code: err instanceof Error && "code" in err ? String((err as { code: string }).code) : "MEMORY_ENGINE_UNEXPECTED",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  });

  // Excess proposals beyond the bounded batch are explicitly rejected.
  for (const proposal of proposals.slice(MAX_STUDY_PROPOSALS_PER_BATCH)) {
    rejected.push({
      proposal: { type: proposal.type, subject: proposal.subject, studyId: proposal.studyId },
      code: "MEMORY_VALIDATION_FAILED",
      message: `batch exceeds ${MAX_STUDY_PROPOSALS_PER_BATCH} proposals`,
    });
  }

  return { accepted, rejected };
}