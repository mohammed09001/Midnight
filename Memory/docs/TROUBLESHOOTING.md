# Midnight Memory — Troubleshooting (v1.27.0)

Practical fixes for the failures a new contributor is most likely to hit,
operating Midnight Memory alone or together with Midnight Performance. Not
a spec — see docs/BOUNDARY.md, docs/CONTRACTS.md, docs/PERFORMANCE.md for
the canonical behavior each error enforces.

## Memory's typed error codes

Every Memory failure is a typed `{error:{code,message}}` on stdout with a
non-zero exit — never a hang, never a silent success (docs/BOUNDARY.md
Section 4). The ones you'll actually hit:

| Code | Cause | Fix |
|---|---|---|
| `MEMORY_STORE_UNAVAILABLE` | The SQLite store file is missing/corrupted, or its directory isn't writable | Run `doctor --store <path>` to confirm; if genuinely corrupted, restore from a `backup create` snapshot (docs/BACKUP.md) — never hand-edit the store file |
| `MEMORY_CONTRACT_MISMATCH` | Caller's `contractVersion` major segment doesn't match `MEMORY_ENGINE_CONTRACT_VERSION`'s major | Bump the caller's pinned version's major to match; a minor/patch mismatch is fine and intentionally tolerated (docs/CONTRACTS.md) |
| `MEMORY_INTAKE_UNAUTHORIZED` | The scope's intake policy is `allowlist` and the caller's actor isn't on it | Add the caller with `scope policy --key K --mode allowlist --allow <kind>:<name>`, or use `--mode open` for the scope |
| `MEMORY_PROMOTION_FORBIDDEN` | An `agent`-kind actor tried to promote a candidate or resolve a contradiction | Promotion/resolution requires a `human` actor or an explicit matched policy — this is enforced structurally (`src/engine/policies.ts`, `src/engine/contradictions.ts`), not a bug to work around |
| `MEMORY_VALIDATION_FAILED` | Malformed request (bad JSON, missing required field, unknown operation) | Check the error `message` — it names the exact field/operation |
| `MEMORY_CONFLICT` | Stale-state write (e.g. promoting an already-resolved candidate, restoring into a non-empty store) | Re-read current state before retrying; a restore always needs a fresh, empty target store |

## Performance bridge failures

`memory_bridge.py` distinguishes two failure classes — check `type(exc)`,
not just the message:

- **`MemoryUnavailableError`** — transient: `node`/`cli.ts` unreachable, the
  subprocess timed out, or stdout wasn't parseable JSON. `MEMORY_STORE_UNAVAILABLE`
  is included here too when it reaches the CLI boundary through a torn
  store, even though it isn't strictly a process-level failure — the bridge
  currently classifies it via `call_memory_cli`'s `ok:false` parsing path,
  so treat any `MemoryContractError(code="MEMORY_STORE_UNAVAILABLE")` the
  same way you'd treat unavailability. `call_memory_cli_with_retry` retries
  this class.
- **`MemoryContractError`** — Memory was reached and said no deterministically
  (validation, authorization, contract mismatch). Never retried — retrying
  cannot change a deterministic rejection.

`propose_lesson_or_degrade`/`read_memory_context_or_none` never raise
either of these into caller code — they return a typed degraded result
(`delivered=False`/`None`) instead. A degraded result is never a promotion;
only Memory's own accepted-and-promoted record is durable knowledge.

## "My bridge tests silently pass but never actually ran anything"

Every real (non-mocked) test in `Performance/tests/test_memory_bridge*.py`
is gated with `@unittest.skipUnless(_NODE_AVAILABLE, ...)`, where
`_NODE_AVAILABLE = shutil.which("node") is not None`. If `node` isn't on
`PATH` in the environment running the tests, these tests report as
**skipped**, not failed — a green run can mean "everything passed" or "the
real round trips never executed." Always confirm with `node --version`
first, and run with `-v` so skips are visible in the output rather than
folded into a bare dot.

## "`python -m unittest discover` reports fewer tests than I expect"

Several Performance test files use plain `assert`-based pytest-style
functions instead of `unittest.TestCase` classes (e.g.
`test_evaluation_memory_qualification.py`, `test_architecture_truth_gate.py`).
`unittest discover` silently collects **zero** tests from those files — no
error, no warning, just a lower total. Always use `python -m pytest tests/`
(the project's actual configured runner, per `pyproject.toml`) for a
verification claim that means anything. See `Performance/README.md`.

## Migrating from the pre-Midnight "Library" identity

The engine's public identity (package name, MCP `serverInfo.name`, backup
format string, event-source literal) was renamed from "Library" to
"Midnight" in an earlier execution — see docs/CONTRACTS.md's changelog
("Execution 01, Task 2 — reconcile Library-origin naming") for the exact
before/after mapping. What still says "library" today is deliberate,
read-only backward compatibility: the `LIBRARY_MEMORY_STORE` environment
variable (deprecated, still honored — prefer `MIDNIGHT_MEMORY_STORE`) and
the `library-memory-backup` legacy bundle format (accepted read-only by
`verifyBackup`/`restoreBundle`, never re-emitted). Neither is stale residue
to remove; both exist specifically so an old integration keeps working
during migration.
