# Midnight Memory — Study → Memory Proposals (v1.12.0)

Implemented in `src/engine/study.ts`. Task 28, Phase V.

## Principle

VERIFIED Study findings and USER ANNOTATIONS become Memory CANDIDATES in the
intake stream (docs/INTAKE.md) through the versioned contract
(`memory.study.propose` / `engine.proposeStudy`) — NEVER direct records — and
Study records stay EXTERNAL, referenced only by evidenceRef
(`{engine: "study_document", ref}`).

## Proposal shape

```ts
interface StudyProposal {
  type: "finding" | "annotation";   // verified Study finding, or user annotation
  subject: string;
  content: string;
  studyId: string;                  // external Study id
  version: string;                  // Study/version/source-revision provenance
  sourceRevision: string;           // Study/version/source-revision provenance
  note?: string;                    // e.g. finding id / section
  kind?: RecordKind;                // finding → "fact"; annotation → "note"
  epistemicClass?: EpistemicClass;  // default "observed"
  confidence?: number;
  tags?: string[];
  actor?: ActorInput;               // producer (set the user for annotations)
  method?: string;
  reason?: string;
}
```

## Provenance

Every proposal carries Study/version/source-revision provenance by reference:
`ref = "<studyId>#v<version>#rev<sourceRevision>"` on `{engine:
"study_document"}`. The Study payload itself is never embedded.

| type | sourceKind | promotion |
|---|---|---|
| `finding` | `study_finding` | eligible via `verified_study_fact` (observed + evidence) |
| `annotation` | `user_note` | retained in the stream (policy match or human approval) |

## Bounded + explicit failure

- Batch bounded at `MAX_STUDY_PROPOSALS_PER_BATCH` (50); excess explicitly
  rejected.
- Study/version/source-revision are REQUIRED — a proposal missing any is
  rejected (`MEMORY_VALIDATION_FAILED`).
- A failed proposal is reported in `rejected` with a typed code/message and
  never aborts the batch.

## Intake authorization

Under an allowlist intake policy the submitting caller (default
`engine:study_document`) must be authorized; otherwise the proposal is
rejected (`MEMORY_INTAKE_UNAUTHORIZED`).

## Agent neutrality / game independence

Pure transformation over the existing intake pipeline — no LLM, no Study-store
access (records stay external), no game dependency. Terminal surface:
`study propose --scope K --kind finding|annotation --study ID --version V
--source-revision R --subject S --content T [--note N]`.