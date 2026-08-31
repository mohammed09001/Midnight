"""Explainable, bounded change scope, dispersion, and impact projections."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import PurePosixPath
from .repository_capture import ChangeEvidence

@dataclass(frozen=True, slots=True)
class ChangeMetrics:
    files_touched:int; directories_touched:int; test_files:int; config_files:int; dependency_files:int; deleted_files:int; locality:float; potential_impacts:tuple[str,...]

def measure(changes: ChangeEvidence) -> ChangeMetrics:
    paths = tuple(changes.created + changes.modified + changes.deleted)
    dirs={str(PurePosixPath(p).parent) for p in paths}; names={PurePosixPath(p).name for p in paths}
    tests=sum(p.startswith("tests/") or PurePosixPath(p).name.startswith("test_") for p in paths)
    configs=sum(n in {"pyproject.toml","package.json","tsconfig.json","requirements.txt"} for n in names)
    deps=sum(n in {"package.json","requirements.txt","poetry.lock","package-lock.json"} for n in names)
    locality=1.0 if len(dirs)<=1 else round(1/len(dirs),3)
    impacts=[]
    if configs: impacts.append("configuration_or_dependency_consumers")
    if tests: impacts.append("test_surface")
    if any("api" in p or "interface" in p for p in paths): impacts.append("public_interface_candidates")
    return ChangeMetrics(len(paths),len(dirs),tests,configs,deps,len(changes.deleted),locality,tuple(impacts))
