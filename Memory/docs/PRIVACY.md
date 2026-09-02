# Midnight Memory — Field-Level Privacy & Project Isolation (v1.19.0)

Implemented in `src/engine/privacy.ts` (+ migration 12,
`memory_scopes.privacy_policy_json`). Task 37, Phase VII.

## Content-class policy (per scope)

```ts
interface ContentPolicy {
  exportable: Array<"public" | "internal">; // classes exportable WITHOUT opt-in
  forbidSensitive: boolean;                  // refuse sensitive entirely (even opt-in)
}
```

- Default: `exportable: ["public", "internal"]`, `forbidSensitive: false`.
- Applied to the EXCERPT gate (docs/EXCERPTS.md) and the EMBEDDING / derived
  index gate (docs/EMBEDDINGS.md): a record not exportable under the policy is
  excluded (`skippedSensitive` reported); `sensitive` requires opt-in unless
  `forbidSensitive` refuses it everywhere.
- Configure: `engine.setScopePrivacyPolicy(scope, policy)` or
  `privacy content-policy --scope K [--forbid-sensitive] [--exportable public,internal]`.

## Project / workspace isolation

Engine-level `strict` (default) / `open`:

- `strict`: read/query surfaces (`memory.search`, `memory.lexical`,
  `memory.semantic`, as-of, and their traced variants) REQUIRE a `scope`
  (project) — an unscoped query cannot silently read across projects
  (`MEMORY_VALIDATION_FAILED` with an explicit message).
- `open`: unscoped (cross-project) queries are allowed.
- Configure: `engine.setProjectIsolation("strict"|"open")` or
  `privacy isolation --mode strict|open`.

## Export restrictions

`checkExportable(record, policy, includeSensitive?)` is the single
deterministic export rule. The excerpt pack and the embedding projection both
apply it, so restricted content never leaks into Context Packs or derived
indexes.

## Local / self-hosted defaults

The engine is immutable `selfHosted: true` (zero external calls). `policyStatus()`
/ `memory.privacy` reports `{ selfHosted: true, projectIsolation, scopes:
[{projectKey, content}] }`.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Unscoped query under strict isolation | `MEMORY_VALIDATION_FAILED` (project isolation message) |
| Non-exportable record export | excluded (excerpts/embeddings report skips); single-record redaction (docs/EXCERPTS.md) |
| Unknown scope | `MEMORY_NOT_FOUND` |
| Invalid isolation mode | `MEMORY_VALIDATION_FAILED` |

## Agent neutrality / game independence

Policies are per-project, generic, and fully local — no LLM, no external
service, no game dependency.