# Library Memory Engine — Project User Notes (v1.16.0)

Implemented in `src/engine/userNotes.ts` (+ `user_decision` source kind /
`user_decision` authority tier). Task 32, Phase V.

## Principle

EXPLICIT USER-AUTHORED notes and decisions are modeled as FIRST-CLASS MEMORY
RECORDS with STRONGER SUBJECTIVE AUTHORITY within their declared scope. The
user IS the authority — a user note/decision is written directly as a durable
record (no candidate gate, no promotion), unlike agent/engine output which must
flow through the candidate intake pipeline.

## Surface

`engine.addUserNote(input)` / `memory.user.note`:

```ts
interface UserNoteInput {
  scope: string;        // the declared project the note/decision applies to
  subject: string;
  content: string;
  kind?: "note" | "decision";
  actor: ActorInput;    // REQUIRED — must be kind "human"
  method?, epistemicClass?, confidence?, tags?, relationHints?,
  evidenceRefs?, privacyClass?, validFrom?, validUntil?, observedAt?,
  idempotencyKey?
}
```

## Authority

| kind | sourceKind | authority tier |
|---|---|---|
| `note` | `user_note` | `user_reported` |
| `decision` | `user_decision` | `user_decision` — STRONGER subjective authority (above `user_reported`, below `verified_source`) |

Both are scoped to the project the user declares (the record is created in that
scope).

## Epistemic honesty

Default `epistemicClass` is `derived` — the user's own subjective statement
requires no external evidence. A user may still declare `observed`, which then
requires evidence refs (the observed-requires-evidence authority rule stays
intact).

## Failure / degradation

| Condition | Behavior |
|---|---|
| Actor is agent/engine/tool | `MEMORY_VALIDATION_FAILED` (agents/engines must use `memory.propose`) |
| `kind` not note/decision | `MEMORY_VALIDATION_FAILED` |
| `observed` without evidence | `MEMORY_VALIDATION_FAILED` (authority rule) |
| Unknown scope | `MEMORY_NOT_FOUND` |

## Agent neutrality / game independence

Only the explicit user-authorship rule is enforced (agents use the candidate
pipeline — never a silent write). No LLM, no game dependency. Terminal surface:
`record user-note --scope K --subject S --content T [--kind note|decision]
[--actor-kind human --actor-name NAME]`.