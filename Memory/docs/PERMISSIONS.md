# Midnight Memory — Mutation Authorization & Confirmation (v1.17.0)

Implemented in `src/engine/authorization.ts` (+ migration 11,
`memory_scopes.mutation_policy_json`). Task 35, Phase VI.

## Principle

Mutations (promote/revise/delete and related lifecycle operations) initiated
by agents REQUIRE an explicit project/user policy, and every mutation logs its
actor AND origin.

## Mutation policy (per scope)

```ts
interface MutationPolicy {
  mode: "open" | "restricted";
  allow: string[]; // canonical actor keys, e.g. "agent:worker-a", "human:kim"
}
```

- `open` (default): the structural rules apply — agents are blocked from
  promote/revise/supersede/lifecycle operations by the existing checks.
- `restricted`: mutations require the acting actor to be in `allow`; an
  unlisted actor (including an agent) is refused with
  `MEMORY_MUTATION_FORBIDDEN`. A specifically listed agent IS explicitly
  authorized (the project/user policy overrides the structural agent-block for
  revise/delete/etc.). `promote` remains structurally non-agent (AI can never
  self-promote, docs/PROMOTION.md).

Configure via `engine.setScopeMutationPolicy(scope, policy)` or
`scope mutation-policy --key K --mode open|restricted --allow agent:worker-a`.

## Origin logging

Every mutation event carries `actor` (who) AND `origin` (where the mutation
came from: `cli` / `contract` / `mcp` / `host` / `unknown`). The CLI passes
`origin: "cli"`, the contract dispatcher `origin: "contract"`, and the MCP
tool surface `origin: "mcp"` — so every mutation is fully attributable.

## Operations gated

promote, reject, revise, supersede, retract, archive, restore, delete, purge,
purge-by-privacy, resolve-contradiction, delete-scope (each with a typed
`assertMutationAuthorized` guard; structural agent-blocks still apply when the
actor is not explicitly authorized).

## Failure / degradation

| Condition | Behavior |
|---|---|
| `restricted` + unlisted actor | `MEMORY_MUTATION_FORBIDDEN` |
| `open` + agent mutation | structural `MEMORY_CORRECTION_FORBIDDEN` / `MEMORY_PROMOTION_FORBIDDEN` |
| Unknown scope | `MEMORY_NOT_FOUND` |
| Missing `origin` | omitted from the event (still actor-attributed) |

## Agent neutrality / game independence

Policies are generic actor keys — no agent product is privileged; the explicit
policy is the only override. No LLM, no game dependency.