# Midnight Memory — Backup, Restore & Integrity Checks (v1.20.0)

Implemented in `src/engine/backup.ts`. Task 39, Phase VII.

## Principle

Backs up CANONICAL Memory (scopes, records, immutable revisions, candidates,
contradiction groups, search-session history, and scope policies — intake /
mutation / privacy) plus the metadata needed to rebuild derived projections, as
a portable JSON bundle with a SHA-256 checksum. Derived projections (FTS,
embeddings, entity/graph) are NOT backed up — they are rebuildable from
canonical records.

## Bundle

```jsonc
{
  "format": "midnight-memory-backup",
  "schemaVersion": 1,
  "contractVersion": "1.20.0",
  "createdAt": "…",
  "checksum": "sha256 of data",
  "data": { "scopes": [], "contradictionGroups": [], "records": [],
            "revisions": [], "candidates": [], "searchSessions": [] }
}
```

Compatibility: bundles written with the pre-rename format string
(`library-memory-backup`) are still accepted by `verifyBackup`/`restoreBundle`
(read-only, with a deprecation notice) — new backups are always written as
`midnight-memory-backup`.

## API

- `engine.backup()` / `memory.backup` → bundle.
- `engine.backupToFile(path)` / `backup create --path F`.
- `engine.verifyBackup(bundle)` / `memory.backup {action: verify}` → recomputes
  the checksum and validates structural references (records → scopes /
  supersession, revisions → records, candidates → scopes, groups/sessions →
  scopes).
- `engine.restoreBundle(bundle)` / `backup restore --path F` → full snapshot
  into a FRESH store; refuses a non-empty store (`MEMORY_CONFLICT`).
- `engine.verifyStoreReferences()` / `memory.backup {action: verifyReferences}`
  → checks canonical foreign references in the live store.

## Failure / degradation

| Condition | Behavior |
|---|---|
| Corrupt / tampered backup | `verifyBackup` → `{valid: false, errors}`; restore refused (`MEMORY_VALIDATION_FAILED`) |
| Restore into a non-empty store | `MEMORY_CONFLICT` |
| Unreadable backup file | `MEMORY_VALIDATION_FAILED` |
| Orphaned foreign reference | `verifyStoreReferences` → `consistent: false` with issues |

## Agent neutrality / game independence

Local, deterministic, zero-dependency; no game dependency. Terminal surface:
`backup create [--path F] | restore --path F | verify --path F |
verify-references`.