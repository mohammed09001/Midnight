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

def compare(before: RepositorySnapshot, after: RepositorySnapshot) -> ChangeEvidence:
    return ChangeEvidence(tuple(sorted(after.files.keys() - before.files.keys())), tuple(sorted(k for k in before.files.keys() & after.files.keys() if before.files[k] != after.files[k])), tuple(sorted(before.files.keys() - after.files.keys())))
