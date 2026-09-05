"""Before/after filesystem evidence; agent reports are intentionally not input truth."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from pathlib import Path

@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    files: dict[str, str]
    @classmethod
    def capture(cls, root: Path) -> "RepositorySnapshot":
        return cls({p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts})

@dataclass(frozen=True, slots=True)
class ChangeEvidence:
    created: tuple[str, ...]; modified: tuple[str, ...]; deleted: tuple[str, ...]
    # (old_path, new_path) pairs with unambiguous 1:1 content-hash correlation
    # only (Execution 08, Section A) — never a guess. `created`/`deleted` keep
    # every path they already have; this is a strictly additive annotation so
    # every existing consumer's "complete touched-path set" assumption holds.
    renamed: tuple[tuple[str, str], ...] = ()

def compare(before: RepositorySnapshot, after: RepositorySnapshot) -> ChangeEvidence:
    created_keys = after.files.keys() - before.files.keys()
    deleted_keys = before.files.keys() - after.files.keys()
    deleted_by_hash: dict[str, list[str]] = {}
    for key in deleted_keys:
        deleted_by_hash.setdefault(before.files[key], []).append(key)
    created_by_hash: dict[str, list[str]] = {}
    for key in created_keys:
        created_by_hash.setdefault(after.files[key], []).append(key)
    renamed = tuple(sorted(
        (deleted_paths[0], created_by_hash[content_hash][0])
        for content_hash, deleted_paths in deleted_by_hash.items()
        if content_hash in created_by_hash and len(deleted_paths) == 1 and len(created_by_hash[content_hash]) == 1
    ))
    return ChangeEvidence(
        tuple(sorted(created_keys)),
        tuple(sorted(k for k in before.files.keys() & after.files.keys() if before.files[k] != after.files[k])),
        tuple(sorted(deleted_keys)),
        renamed,
    )
