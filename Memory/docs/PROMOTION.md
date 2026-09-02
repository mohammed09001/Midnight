# Library Memory Engine — Deterministic Promotion Policies (v1.2.0)

Implemented in `src/engine/policies.ts`; enforced inside
`promoteCandidate` — every promotion is policy-driven (Task 9).

## The rule

**AI may assist classification but cannot self-promote.** An actor of kind
`agent` can never promote (or reject) a candidate — `MEMORY_PROMOTION_FORBIDDEN`.
This is structural, mirroring docs/AUTHORITY.md; it does not depend on the
agent's confidence, fluency, or the candidate's quality.

## The three built-in policies (deterministic)

| Policy | Match condition | Promoter |
|---|---|---|
| `explicit_user_decision` | A **human** approver decides at promotion time | `kind: "human"` only |
| `verified_study_fact` | `sourceKind === "study_finding"` **and** `epistemicClass === "observed"` **and** ≥ 1 evidence ref | any non-agent actor |
| `repeated_evidence_backed_lesson` | ≥ 2 **distinct** evidence refs on the candidate, OR the same normalized subject+content seen ≥ 2 times in the scope (re-proposals count) | any non-agent actor |

Thresholds are engine config (`PromotionConfig`, defaults 2/2). Evaluation
is a pure function of store state: same candidate + same store ⇒ same
`PromotionAssessment {eligible, matchedPolicies, reasons}` — stable across
processes and restarts (verified).

## Promotion flow

1. `evaluatePromotion(candidateId)` → deterministic assessment (also exposed
   on the candidate stream listing).
2. `promoteCandidate(candidateId, {actor, policy?})`:
   - agent actor → `MEMORY_PROMOTION_FORBIDDEN`;
   - `explicit_user_decision` requested by non-human → forbidden;
   - requested policy must have matched evaluation, else `MEMORY_CONFLICT`
     with the full deterministic reasons;
   - no policy requested: exactly one auto-match promotes; ambiguity or no
     match → `MEMORY_CONFLICT` with reasons (a human may then decide).
3. Promotion creates the canonical record via the normal validated path and
   emits `memory.candidate.promoted {recordId, policy, approvedBy}`.

## Relationship to intake

Proposals enter via the authorized intake pipeline (docs/INTAKE.md). Agents
propose freely — with authority caps (docs/AUTHORITY.md) — and humans,
verified study facts, or repeated evidence decide what becomes durable.
