# Library Memory Engine — Untrusted-Content Boundaries (v1.20.0)

Implemented in `src/engine/trust.ts`. Task 38, Phase VII.

## Principle

Stored external text (record content, subjects, tags, candidate content) is
treated as DATA — never as instructions. Retrieved memories cannot redefine
system policy, tool permissions, or promotion rules. Every policy surface
(promotion, mutation authorization, intake authorization, content-class export
rules) reads only STRUCTURAL fields (sourceKind, epistemicClass, evidenceRefs,
actor, privacyClass, content hash for repeat counting) and never interprets
content text.

## Boundary

- `engine.contentBoundaryStatus()` / `memory.trust` reports:
  - `trust: "untrusted-data"` (the invariant),
  - `contentSurfaces` (surfaces that RETURN content as data),
  - `policySurfaces` (surfaces that never read content text).
- Excerpts carry `trust: "untrusted-data"` on every `ContextExcerpt`, so a
  host/agent receiving context treats the content as data.
- `engine.contentAsData(value)` labels any value handed to a host.

## Verified guarantees

- A candidate whose content contains a prompt-injection attempt does NOT become
  automatically promotion-eligible (structural eligibility ignores content).
- Record content cannot alter the scope's mutation/intake/content policies.
- A human approver may still explicitly promote (explicit_user_decision) — the
  DECISION is a human's, never the content's.

## Agent neutrality / game independence

Structural, deterministic, provider-free, no game dependency. Terminal surface:
`trust status`.