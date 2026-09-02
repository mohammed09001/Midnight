# Library Memory Engine — Context-Safe Memory Excerpts (v1.18.0)

Implemented in `src/engine/excerpts.ts`. Task 36, Phase VI.

## Principle

Returns BOUNDED excerpts or structured facts suitable for Context Packs
WITHOUT leaking restricted source payloads. Each excerpt is a structured fact:
`recordId`, `subject`, excerpted `content`, `tags`, `sourceKind`,
`authorityTier`, `currentlyValid`, `confidence`, `privacyClass`. Evidence
payloads are NEVER included (evidence stays by reference only).

## Pack

`engine.contextExcerpts(query)` / `memory.excerpts {action: pack}`:

```ts
interface ContextExcerptQuery {
  scope: string;
  at?: string;                // validity instant (default now)
  maxExcerpts?: number;       // 1–100 (default 20)
  maxContentChars?: number;   // per-excerpt bound (default 200, min 20)
  includeSensitive?: boolean; // privacy gate
  sourceKinds?: SourceKind[];
  kinds?: RecordKind[];
  minConfidence?: number;
  minAuthority?: AuthorityTier;
}
```

- Over-long content is ellipsized (`…`) and flagged `truncated`.
- Deterministic context ordering: currently valid → authority → recency.
- `skippedSensitive` reports how many records were excluded by the privacy
  gate; `diagnostics.totalMatches`/`truncated` report bounds.

## Single-record excerpt

`engine.memoryExcerpt(recordId, {maxContentChars?, includeSensitive?})`:

- Sensitive content is REDACted to `[sensitive content excluded]` by default
  (never leaked into a context pack); `includeSensitive: true` reveals it.
- Tombstoned records are refused (`MEMORY_PRIVACY_VIOLATION` — content is
  scrubbed).

## Failure / degradation

| Condition | Behavior |
|---|---|
| Unknown scope | `MEMORY_NOT_FOUND` |
| Invalid `at` / `minConfidence` | `MEMORY_VALIDATION_FAILED` |
| Unknown / tombstoned record | typed error (`MEMORY_VALIDATION_FAILED` / `MEMORY_PRIVACY_VIOLATION`) |

## Agent neutrality / game independence

Deterministic, provider-free, no game dependency. Terminal surface:
`excerpts --scope K [--max-excerpts N] [--max-content-chars N]
[--include-sensitive]`, `excerpts record --id R [--include-sensitive]`.