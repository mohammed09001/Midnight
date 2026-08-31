"""Bounded file/region resolution and inferred semantic change labels."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from .repository_capture import ChangeEvidence

@dataclass(frozen=True, slots=True)
class ResolvedChange:
    path: str; region: str | None; parser: str; parser_version: str; confidence: float; unresolved: bool=False

def resolve_change(path: str, *, region: str | None=None) -> ResolvedChange:
    suffix = PurePosixPath(path).suffix
    if suffix in {".py", ".js", ".ts", ".tsx"}: return ResolvedChange(path, region, "path-parser", "1", .6)
    return ResolvedChange(path, None, "none", "1", 0, True)

class ChangeKind(str, Enum): FEATURE="feature_addition"; BUGFIX="bug_fix"; REFACTOR="refactor"; CONFIGURATION="configuration"; DEPENDENCY="dependency"; TEST="test"; DELETION="deletion"; INTERFACE="interface_change"; DATA_MODEL="data_model_change"; SECURITY="security_related"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class ChangeClassification:
    kind: ChangeKind; method: str; version: str; confidence: float; uncertainty: str
def classify(changes: ChangeEvidence) -> tuple[ChangeClassification, ...]:
    paths = set(changes.created + changes.modified + changes.deleted)
    result=[]
    if changes.deleted: result.append(ChangeClassification(ChangeKind.DELETION,"path-heuristic","1",.8,"file purpose unknown"))
    if any(p.startswith(("tests/","test_")) for p in paths): result.append(ChangeClassification(ChangeKind.TEST,"path-heuristic","1",.7,"tests may include fixtures"))
    if any(PurePosixPath(p).name in {"pyproject.toml","package.json","requirements.txt"} for p in paths): result.append(ChangeClassification(ChangeKind.DEPENDENCY,"path-heuristic","1",.6,"configuration may be mixed"))
    return tuple(result) or (ChangeClassification(ChangeKind.UNKNOWN,"path-heuristic","1",0,"no deterministic semantic signal"),)
