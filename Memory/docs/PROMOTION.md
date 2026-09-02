# Midnight Memory — Deterministic Promotion Policies (v1.3.0)

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
| `repeated_evidence_backed_lesson` | `epistemicClass` is `observed` **or** `derived` (never `inferred`/`recommendation` — see below) **and** (≥ 2 **distinct** evidence refs on the candidate, OR the same normalized subject+content seen ≥ 2 times in the scope; re-proposals count) | any non-agent actor |

Thresholds are engine config (`PromotionConfig`, defaults 2/2). Evaluation
is a pure function of store state: same candidate + same store ⇒ same
`PromotionAssessment {eligible, matchedPolicies, reasons}` — stable across
processes and restarts (verified).

**v1.3.0 (Task 16, Execution 06):** `repeated_evidence_backed_lesson`
explicitly excludes `epistemicClass: "inferred"` and `"recommendation"` —
repetition or multi-sourcing cannot upgrade a claim that is structurally
speculative/predicted by its own epistemic class into promotion
eligibility, regardless of how many distinct sources or repeats accumulate.
Such a candidate remains promotable only via `explicit_user_decision`
(unconditional, genuine human review). This closes a gap where a Performance
lesson correctly classified as `recommendation` (e.g. exported via
`lesson_from_qualified_claim`'s `ClaimKind`→`epistemicClass` mapping, which
never upgrades claim strength) could still have been auto-promotion-eligible
purely by accumulating evidence refs — the label was honest but the
*promotion path* wasn't gated on it. `verified_study_fact` was already
unaffected (it requires `epistemicClass === "observed"`).

## No integration can self-promote (Task 18, Execution 06)

`Performance/midnight_performance/memory_bridge.py` never calls
`memory.promote` or any promotion/resolution operation — it only ever
proposes (`memory.performance.propose`) and reads (`memory.context`).
Contradiction resolution is not even exposed through the versioned
`contract call` envelope (`MEMORY_OPERATIONS` has no resolve operation) —
it is reachable only via the CLI or the direct engine method, both of which
still enforce the same agent-actor refusal. Adversarial round trips proving
self-promotion and self-resolution are both refused live through the real
integration are in `Performance/tests/test_memory_bridge.py`
(`MemoryPromotionAuthorityTests`).

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
