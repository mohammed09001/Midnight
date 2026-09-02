# Library Memory Engine — Stable Identities and Scopes (v1.0.0)

Implemented in `src/engine/ids.ts`; migrations 2–3 in `src/engine/store.ts`.
Contract version: **1.0.0**.

## Identity inventory

| Entity | Identity form | Stability guarantee |
|---|---|---|
| Scope | `scp_` + 26 Crockford-base32 chars = first 128 bits of SHA-256(`projectKey`) | Deterministic from the caller-owned `projectKey`; identical across restarts, machines, and project-path moves |
| MemoryRecord | `mem_` + ULID (48-bit ms time + 80-bit randomness) | Generated once, immutable; time-sortable |
| MemoryCandidate | `cand_` + ULID | Immutable pre-promotion identity; promotion creates a NEW record identity |
| Contradiction group | `ctg_` + ULID | Stable grouping identity; membership is the group's `record_ids` |
| Engine event | `evt_` + ULID | Append-only event-log identity |
| Actor | Canonical string `"<kind>:<name>"` where kind ∈ `human\|agent\|engine\|tool` | Caller-owned; reusing the same name preserves identity. No agent product is special-cased |
| Source/evidence reference | `{engine, ref, note?}` — never embedded payload | The `ref` is stable in the OWNING engine's namespace |
| Validity interval | `validFrom` / `validUntil` ISO 8601 timestamps on the record | `validUntil ≤ validFrom` is rejected at write time |
| Revision | Monotonic integer per record + immutable row in `memory_record_revisions` | History is append-only; retraction and revision both advance it |
| Supersession chain | `supersedes_id` / `superseded_by_id` pair on the two records | Only `active` records can be superseded; chains form acyclically by construction |

## Invariants

1. **Path independence.** A project key must match `[\w][\w.-]*` — filesystem
   paths are rejected (`MEMORY_VALIDATION_FAILED`). The store never persists
   the project path, so identities survive project-path moves.
2. **Restart survival.** All identities are persisted in the canonical store;
   reopening the store yields identical identities (verified in
   `test/t2_identities.test.ts`).
3. **Uniqueness + monotonicity.** ULIDs use cryptographically secure
   randomness and in-process monotonic increment within a millisecond
   (per the ULID spec, `github.com/ulid/spec`, master, accessed 2026-08-30).
4. **No API bypass.** Identities are contracts for the versioned API/events —
   possessing an id confers no permission to read another engine's store.
5. **Idempotent scope creation.** Creating an existing scope with the identical
   projectKey + displayName returns the existing identity; a different display
   name for the same key is `MEMORY_CONFLICT`.

## Research note (ULID)

- **Source:** `github.com/ulid/spec` (master branch, fetched 2026-08-30).
- **Pattern extracted:** 26-char Crockford base32 (alphabet excluding
  I/L/O/U), 48-bit timestamp + 80-bit randomness, monotonic same-ms increment.
- **Decision: ADAPT.** Library-owned implementation (no dependency). Two
  documented deviations: (a) same-ms overflow advances the clock one
  millisecond instead of throwing (availability over strictness — Library
  requirement: identity generation must never fail a write); (b) scope ids
  are deterministic base32-encoded SHA-256 digests (128 bits), which satisfy
  the character shape but are hash-derived, not canonical ULIDs.
- **License concern:** none — the spec is documentation; no upstream code was
  copied.
