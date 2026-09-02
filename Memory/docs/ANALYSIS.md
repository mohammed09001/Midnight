# Library Memory Engine — Analysis → Memory Proposals (v1.13.0)

Implemented in `src/engine/analysis.ts`. Task 29, Phase V.

## Principle

The Analysis engine proposes REUSABLE ARCHITECTURAL FINDINGS ONLY through
EVIDENCE-LINKED candidates in the intake stream (docs/INTAKE.md) via the
versioned contract (`memory.analysis.propose` / `engine.proposeAnalysis`) —
NEVER direct record insertion. Analysis records stay EXTERNAL, referenced only
by evidenceRef (`{engine: "analysis", ref}`).

## Finding shape

```ts
interface AnalysisFinding {
  subject: string;          // reusable architectural finding subject
  content: string;          // the finding — NOT the Analysis payload
  evidenceRefs: string[];   // Analysis record id(s), required + bounded
  note?: string;
  kind?: RecordKind;        // default "note"
  epistemicClass?: EpistemicClass; // default "derived" — never claimed observed
  confidence?: number;      // default 0.7
  tags?: string[];
  actor?: ActorInput;       // producer (default: the Analysis engine)
  method?: string;          // default "architectural_analysis"
  reason?: string;
}
```

## Evidence-linked + bounded

- **Evidence-linked**: every finding MUST reference ≥ 1 Analysis record
  (`evidenceRefs`); a finding without evidence is rejected
  (`MEMORY_VALIDATION_FAILED`).
- **Bounded evidence**: ≤ `MAX_ANALYSIS_EVIDENCE_PER_FINDING` (8) refs per
  finding.
- **Bounded batch**: ≤ `MAX_ANALYSIS_FINDINGS_PER_BATCH` (50) findings per
  submission; excess findings are explicitly rejected, never silently dropped.

## Epistemic honesty

`sourceKind analysis_evidence` (authority tier "analysis", docs/AUTHORITY.md)
with `epistemicClass derived` by default — an architectural finding is
intelligence derived from analysis evidence, never claimed as `observed`
(which would require direct observation). Promotion stays policy-gated: a
finding with ≥ 2 distinct Analysis refs matches
`repeated_evidence_backed_lesson`.

## Result + failures

`{accepted: MemoryCandidate[], rejected: Array<{finding, code, message}>}` — a
failed finding never aborts the batch; each rejection carries a typed code.
Intake authorization (allowlist) gates the submitting caller (default
`engine:analysis`).

## Agent neutrality / game independence

Pure transformation over the existing intake pipeline — no LLM, no Analysis-store
access (records stay external), no game dependency. Terminal surface:
`analysis propose --scope K --subject S --content T --evidence analysis:ID
[--evidence analysis:ID2 …]`.