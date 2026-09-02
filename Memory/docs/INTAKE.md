# Library Memory Engine — Candidate Intake Pipeline (v1.2.0)

Implemented in `src/engine/records.ts` (candidate lifecycle),
`src/engine/scopes.ts` (intake policy), migration 5. Proposals enter a
candidate stream and NEVER become durable knowledge directly (Task 8).

## Intake contract

A proposal (`addCandidate` / `memory.propose`) records:

| Field | Meaning |
|---|---|
| `provenance.actor` | The **producer** of the content (agent, human, engine, tool) with method + source kind |
| `reason` | **Required** — why the proposal exists (≤ 1024 chars) |
| `caller` | The submitting engine/user (canonical actor key); required under allowlist intake |
| `evidenceRefs` | Evidence backing the proposal, **by reference only** |
| `scope` | The requested scope (project key or scope id) |
| `idempotencyKey` | Optional replay-safe intake (docs/PERSISTENCE.md) |

## Authorization (Task 8)

Per-scope intake policy:

```jsonc
{ "mode": "open",      "allow": [] }                    // default: anyone may propose
{ "mode": "allowlist", "allow": ["engine:repository_sync", "human:kim"] }
```

- Caller keys are canonical actor strings (`kind:name`).
- Under `allowlist`, an unknown or missing caller is refused with
  `MEMORY_INTAKE_UNAUTHORIZED` before any write.
- Configure via `engine.setScopeIntakePolicy(scope, policy)` or
  `memory-engine scope policy --key K --mode allowlist --allow engine:…`.
- Policy changes emit `memory.scope.intake_policy.updated` and persist.

## Stream lifecycle

`open → promoted | rejected`

- `listCandidates({scope?, status?, limit?})` / `memory.candidates` — the
  stream, oldest first.
- `promoteCandidate` — **policy-gated** (docs/PROMOTION.md).
- `rejectCandidate({actor, reason})` — explicit, attributed rejection;
  agents cannot reject.
- Rejected/promoted candidates are retained (append-oriented; no deletes).

## Events

`memory.candidate.created` (with caller), `memory.candidate.promoted`
(with policy + approver), `memory.candidate.rejected` (with reason).
