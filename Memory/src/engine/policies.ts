/**
 * Deterministic promotion policies (Task 9).
 *
 * Promotion from candidate to durable knowledge is POLICY-DRIVEN and
 * fully deterministic: explicit user decision, verified Study fact,
 * repeated evidence-backed lesson, or another configured rule. AI may
 * assist classification, but an agent actor can never promote — that rule
 * is structural, mirroring the authority model (docs/AUTHORITY.md).
 *
 * Pattern note (mem0 research, main @ 2026-08-30): mem0 stores
 * agent-generated facts "with equal weight" via LLM-judged operations.
 * Library deliberately rejects that: agent output enters through the
 * candidate intake and needs a non-agent, deterministic policy match.
 */
import { ConflictError, PromotionForbiddenError } from "../contracts/errors.ts";
import type {
  MemoryCandidate,
  PromotionAssessment,
  PromotionConfig,
  PromotionPolicyName,
} from "../contracts/types.ts";
import { DEFAULT_PROMOTION_CONFIG } from "../contracts/types.ts";
import type { MemoryStore } from "./store.ts";

export const PROMOTION_POLICIES: readonly PromotionPolicyName[] = [
  "explicit_user_decision",
  "verified_study_fact",
  "repeated_evidence_backed_lesson",
];

export function isPromotionPolicy(value: unknown): value is PromotionPolicyName {
  return (
    typeof value === "string" &&
    (PROMOTION_POLICIES as readonly string[]).includes(value)
  );
}

/**
 * Deterministic evaluation of which promotion policies match a candidate.
 * Same store state + same candidate ⇒ same result, always.
 */
export function evaluatePromotionImpl(
  store: MemoryStore,
  candidate: MemoryCandidate,
  config: PromotionConfig = DEFAULT_PROMOTION_CONFIG,
): PromotionAssessment {
  const matched: PromotionPolicyName[] = [];
  const reasons: string[] = [];

  // 1. explicit_user_decision — matched at promotion time by a human
  //    approver; evaluation alone cannot match it (it needs the approver).
  reasons.push(
    "explicit_user_decision: matches when a human actor approves the promotion (agents never can)",
  );

  // 2. verified_study_fact — verified study finding, claimed as observed,
  //    with at least one evidence reference.
  if (
    candidate.provenance.sourceKind === "study_finding" &&
    candidate.epistemicClass === "observed" &&
    candidate.evidenceRefs.length >= 1
  ) {
    matched.push("verified_study_fact");
    reasons.push(
      `verified_study_fact: sourceKind='${candidate.provenance.sourceKind}', epistemicClass='${candidate.epistemicClass}', ${candidate.evidenceRefs.length} evidence ref(s)`,
    );
  } else {
    reasons.push(
      `verified_study_fact: not matched (needs sourceKind='study_finding' + epistemicClass='observed' + ≥1 evidence ref; got sourceKind='${candidate.provenance.sourceKind}', epistemicClass='${candidate.epistemicClass}', ${candidate.evidenceRefs.length} ref(s))`,
    );
  }

  // 3. repeated_evidence_backed_lesson — the same lesson proposed or known
  //    repeatedly: enough DISTINCT evidence refs on the candidate, or the
  //    same normalized subject+content seen often enough in this scope.
  const distinctEvidence = new Set(
    candidate.evidenceRefs.map((r) => `${r.engine}:${r.ref}`),
  ).size;
  if (distinctEvidence >= config.minDistinctEvidence) {
    matched.push("repeated_evidence_backed_lesson");
    reasons.push(
      `repeated_evidence_backed_lesson: ${distinctEvidence} distinct evidence ref(s) ≥ ${config.minDistinctEvidence}`,
    );
  } else {
    const repeats = countSameSubjectContent(store, candidate);
    if (repeats + 1 >= config.minRepeatCount) {
      matched.push("repeated_evidence_backed_lesson");
      reasons.push(
        `repeated_evidence_backed_lesson: same subject+content seen ${repeats + 1} time(s) in scope (≥ ${config.minRepeatCount})`,
      );
    } else {
      reasons.push(
        `repeated_evidence_backed_lesson: not matched (${distinctEvidence} distinct ref(s) < ${config.minDistinctEvidence}; same subject+content ${repeats + 1} time(s) < ${config.minRepeatCount})`,
      );
    }
  }

  return {
    candidateId: candidate.candidateId,
    eligible: matched.length > 0,
    matchedPolicies: matched,
    reasons,
  };
}

function countSameSubjectContent(store: MemoryStore, candidate: MemoryCandidate): number {
  const db = store.ensureOpen();
  const rows = db
    .prepare(
      `SELECT COUNT(*) AS n FROM memory_candidates
       WHERE scope_id = ? AND subject = ? AND content_hash = ? AND candidate_id != ?`,
    )
    .get(candidate.scopeId, candidate.subject, candidate.contentHash, candidate.candidateId) as Record<string, unknown>;
  const candidateCount = Number(rows["n"]);
  const recordRows = db
    .prepare(
      "SELECT COUNT(*) AS n FROM memory_records WHERE scope_id = ? AND subject = ? AND content_hash = ?",
    )
    .get(candidate.scopeId, candidate.subject, candidate.contentHash) as Record<string, unknown>;
  return candidateCount + Number(recordRows["n"]);
}

export interface PromotionDecision {
  actor: { kind: string; name: string };
  /** The policy the caller requested (optional). */
  requestedPolicy: PromotionPolicyName | null;
}

/**
 * Resolve the promotion policy for a candidate + approver. Deterministic:
 * - an agent actor can NEVER promote (MEMORY_PROMOTION_FORBIDDEN);
 * - explicit_user_decision requires a human approver;
 * - otherwise the requested policy must have matched evaluation;
 * - with no requested policy, exactly one matched policy must exist.
 */
export function resolvePolicy(
  assessment: PromotionAssessment,
  decision: PromotionDecision,
): PromotionPolicyName {
  if (decision.actor.kind === "agent") {
    throw new PromotionForbiddenError(
      "actors of kind 'agent' can never promote candidates: AI may assist classification but cannot self-promote",
    );
  }
  const humanApprover = decision.actor.kind === "human";
  if (decision.requestedPolicy === "explicit_user_decision" && !humanApprover) {
    throw new PromotionForbiddenError(
      "explicit_user_decision requires an actor of kind 'human'",
    );
  }
  if (decision.requestedPolicy !== null) {
    if (decision.requestedPolicy === "explicit_user_decision") {
      return decision.requestedPolicy;
    }
    if (!assessment.matchedPolicies.includes(decision.requestedPolicy)) {
      throw new ConflictError(
        `policy '${decision.requestedPolicy}' did not match this candidate: ${assessment.reasons.join("; ")}`,
      );
    }
    return decision.requestedPolicy;
  }
  const auto = assessment.matchedPolicies.filter((p) => p !== "explicit_user_decision");
  if (auto.length === 1) {
    return auto[0]!;
  }
  if (auto.length === 0 && humanApprover) {
    // A human decision is itself a policy match.
    return "explicit_user_decision";
  }
  throw new ConflictError(
    `promotion is ambiguous or unmatched (${auto.length} candidate policies); pass an explicit policy — ${assessment.reasons.join("; ")}`,
  );
}
