# Library Memory Engine — Search → Memory History (v1.14.0)

Implemented in `src/engine/searchHistory.ts` (+ migration 10,
`memory_search_sessions`). Task 30, Phase V.

## Principle

USEFUL SEARCH INTENT / SESSION HISTORY is stored as RETRIEVAL CONTEXT in an
append-only, scoped log — WITHOUT promoting every candidate repository as
durable knowledge. A recorded search session NEVER creates a durable record or
a promotable candidate; candidate repositories surfaced by a search are
recorded BY REFERENCE only and are never promoted.

## Session shape

```ts
interface SearchSessionInput {
  scope: string;
  intent: string;             // the search intent/query (≤ 1024 chars)
  actor?: ActorInput;         // who searched
  observedAt?: string;        // when the search occurred (default now)
  resultRefs?: EvidenceRef[]; // search results, by reference (≤ 32)
  candidateRefs?: EvidenceRef[]; // candidate repositories surfaced — by ref, never promoted (≤ 32)
  note?: string;
}
```

## Context, not durable knowledge

- `recordSearchSession` appends to `memory_search_sessions` and emits
  `memory.search.session.recorded` — it creates NO record and NO candidate.
  Verified: after recording, `searchRecords` and `listCandidates` are empty.
- Candidate repositories surfaced by the search are stored as refs
  (e.g. `{engine: "repository_search", ref: "acme/gateway"}`) — context for
  later investigation, explicitly not promoted.

## Bounded + append-only

- `intent` ≤ 1024 chars; `resultRefs` ≤ 32; `candidateRefs` ≤ 32.
- Sessions accumulate (no delete, no TTL truth). Scope deletion purges its
  sessions (retrieval context for a deleted project is meaningless).

## API

- `engine.recordSearchSession(input)` → `SearchSession`.
- `engine.listSearchSessions({scope?, limit?})` → newest first.
- `engine.getSearchSession(id)` → typed `MEMORY_NOT_FOUND` if absent.
- Contract `memory.search.session {action: record|list|get}`.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Empty intent / too long | `MEMORY_VALIDATION_FAILED` |
| Invalid `observedAt` / bad evidence ref | `MEMORY_VALIDATION_FAILED` |
| Unknown scope | `MEMORY_NOT_FOUND` |
| Unknown session id | `MEMORY_NOT_FOUND` |

## Agent neutrality / game independence

Storing search history is a pure Memory-side append — no LLM, no Search-store
access (results/repositories stay by reference), no game dependency. Terminal
surface: `search-session record --scope K --intent Q [--evidence engine:ref …]
[--arg candidate=engine:ref …]`, `search-session list [--scope K]`. Intents are
stored as context; callers must not place secrets in intent text (secrets
belong to the secure credential layer).