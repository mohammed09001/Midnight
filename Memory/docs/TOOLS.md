# Midnight Memory — CLI & MCP / Host-Native Tools (v1.17.0)

Tasks 33–34, Phase VI.

## Terminal surface (Task 33)

`npm run cli -- <command>` — stable machine-readable JSON on stdout, typed
error envelopes on failure:

| Command | Purpose |
|---|---|
| `doctor` | store health (integrity, journal, migrations, events) |
| `record search/get/history/related` | retrieval + relations |
| `record current/timeline/ranked/fused/hybrid/lexical` | retrieval views |
| `record explain` | provenance-rich explanation |
| `record add` / `record user-note` | durable records |
| `candidate add/list/evaluate/promote/reject` | intake stream |
| `record revise/supersede/retract/archive/restore/delete` | lifecycle |
| `record contradictions` | contradiction pairs + open groups |
| `scope create/get/policy/mutation-policy/delete` | scope + policies |
| `relation`, `entities`, `embeddings`, `semantic`, `graph`, `dedup`, `projections`, `search-session`, `context` | derived/optional surfaces |
| `mcp [--allow-mutations]` | MCP stdio server (Task 34) |

## MCP / host-native read tools (Task 34)

`src/tools/memoryTools.ts` registers host-native tools; `src/tools/mcpServer.ts`
is a bounded, dependency-free MCP stdio adapter speaking the JSON-RPC subset
(initialize, tools/list, tools/call) per the current MCP spec line (2026-07-28).

- **READ tools** (always exposed): `memory_search`, `memory_get`,
  `memory_history`, `memory_related`, `memory_explain`, `memory_current`,
  `memory_lexical`, `memory_timeline`, `memory_context`, `memory_health`.
- **MUTATION tools** (separately permissioned): `memory_propose`,
  `memory_promote`, `memory_revise`, `memory_delete`. They are LISTED/CALLED
  only when the host opts in (`--allow-mutations` / `allowMutations: true`),
  and each call flows through the mutation authorization surface (docs/PERMISSIONS.md)
  with `origin: "mcp"`. A mutation call without the opt-in is a protocol error.

Run: `npm run cli -- mcp [--allow-mutations]` (stdio server). The tool registry
is also importable host-natively via `MEMORY_TOOLS` / `readTools` /
`findTool` from `src/index.ts`.