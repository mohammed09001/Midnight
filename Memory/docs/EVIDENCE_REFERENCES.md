# Midnight Memory — External Evidence References (v1.0.0)

Standardizes how Memory handles evidence references sourced from sibling
engines — primarily Performance (docs/PERFORMANCE.md) today, but the same
rules apply to any `EvidenceEngine` value (docs/SCHEMA.md). Performance
records stay EXTERNAL; Memory stores only a stable reference
(`{engine, ref, note?, expiresAt?}`) plus bounded metadata allowed by
policy — never the referenced payload (docs/BOUNDARY.md Section 0).

## The six-case behavior matrix

| Case | What Memory enforces | Where | Proven by |
|---|---|---|---|
| **Missing** | A lesson/record with zero `evidenceRefs` is rejected before it becomes evidence-backed content — `MEMORY_VALIDATION_FAILED` | `src/engine/performance.ts` `validateLesson` | `test/t27_performance.test.ts` |
| **Malformed** | Unknown fields, a bad `engine` value, or an oversized `ref`/`note` are rejected — `MEMORY_VALIDATION_FAILED` | `src/engine/validation.ts` `validateEvidenceRef` | `test/t3_schema.test.ts` |
| **Expired** | `expiresAt` (optional, ISO 8601) marks when SOURCE evidence lapses. Expiry degrades verifiability — surfaced in `memory.explain`'s `evidenceGaps` and via `sweepExpiredEvidence` — but never silently invalidates the record | `src/engine/retention.ts` (`evidenceAllExpired`, `listEvidenceExpiredImpl`, `sweepExpiredEvidenceImpl`), `src/engine/relations.ts` `evidenceGapsOf` | `test/t13_retention.test.ts`, `test/t20_explain_traces.test.ts` |
| **Duplicated** | An exact-duplicate `{engine, ref}` pair within one `evidenceRefs` array is rejected — `MEMORY_VALIDATION_FAILED`. Keyed on the PAIR, never `ref` alone: two different engines legitimately sharing the same literal `ref` string is NOT a duplicate | `src/engine/validation.ts` (the `evidenceRefs` loop inside the shared record/candidate validator) | `test/t51_evidence_reference_hardening.test.ts` |
| **Inaccessible** | Memory structurally CANNOT verify this itself — reading a sibling engine's store to check reachability would violate the no-direct-sibling-store-access invariant. This is a Performance-side precondition instead: `Performance/midnight_performance/memory_bridge.py`'s `lesson_from_sealed_envelope` refuses to build a lesson from any `ObservationEnvelope` that is not sealed-and-verified (`provenance.verify(...) is True`) — an unsealed or tampered envelope never reaches Memory at all. Memory's own contribution is refusing anything malformed on arrival (see Malformed), never confirming reachability | `memory_bridge.py` (Performance side) | `Performance/tests/test_memory_bridge.py` |
| **Retired** | No new mutation path exists for evidenceRefs, and none is added. Retirement is communicated by proposing a NEW evidence-backed lesson/record that supersedes the old one (`engine.supersedeRecord`) — the superseding record carries the PRIOR record's `evidenceRefs` forward verbatim (never a silently different set); new evidence only ever enters via a genuinely new record | `src/engine/records.ts` `supersedeRecordImpl` (existing, Task 11) | `test/t51_evidence_reference_hardening.test.ts` |

## Honest limits (documented, not closed here)

`lesson_from_sealed_envelope`'s sealed-check proves the envelope was produced
through Performance's real `provenance.seal()` API and hasn't been tampered
with in transit — it does **not** prove the observation is genuinely present
in a specific `EvidenceLedger` (that would require a `ledger.replay()` scan,
deliberately out of scope for this pure, I/O-free helper). A future,
stricter variant could accept an explicit `ledger` argument and check
ledger membership; this execution does not build that.

## Cross-references

docs/BOUNDARY.md Section 0 (ownership statement: evidence by reference only)
· docs/PERFORMANCE.md (the Performance→Memory proposal pipeline this matrix
governs) · docs/RETENTION.md (expiry/retention policy detail)
· docs/INTAKE.md (the candidate pipeline every evidence-backed proposal
passes through) · docs/SCHEMA.md (the canonical `evidenceRefs` field shape).
