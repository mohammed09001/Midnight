"""Whether requested verification actually occurred and exercised changed behavior."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Mapping
from .contracts import ClaimKind
from .repository_capture import ChangeEvidence
from .verification import VerificationEvidence, VerificationSource

_METHOD = "verification-coverage"
_VERSION = "1"
_PASSED = frozenset({"passed", "pass", "ok", "success", "succeeded", "green"})

class VerificationKind(str, Enum):
    TESTS = "tests"; BUILD = "build"; LINT = "lint"; TYPECHECK = "typecheck"; RUNTIME = "runtime"

_KEYWORDS: tuple[tuple[VerificationKind, tuple[str, ...]], ...] = (
    (VerificationKind.TESTS, ("test", "unittest", "pytest", "spec")),
    (VerificationKind.BUILD, ("build", "compile", "wheel", "package")),
    (VerificationKind.LINT, ("lint", "ruff", "flake", "eslint", "pylint")),
    (VerificationKind.TYPECHECK, ("mypy", "pyright", "tsc", "typecheck")),
    (VerificationKind.RUNTIME, ("runtime", "smoke", "probe", "watch", "healthcheck")),
)

@dataclass(frozen=True, slots=True)
class VerificationQuality:
    requested: tuple[VerificationKind, ...]; verified: tuple[VerificationKind, ...]; failed: tuple[VerificationKind, ...]; weakly_reported: tuple[VerificationKind, ...]; missing: tuple[VerificationKind, ...]; coverage: float; behavior_exercised: bool; unexercised: tuple[str, ...]; gaps: tuple[str, ...]; uncertainties: tuple[str, ...]; method: str; method_version: str; claim_kind: ClaimKind
    def __post_init__(self):
        if not 0 <= self.coverage <= 1: raise ValueError("coverage must be between zero and one")

    @property
    def sufficient(self) -> bool:
        return not self.gaps and self.coverage >= 1 and self.behavior_exercised

def _kind_of(evidence: VerificationEvidence, kinds: Mapping[str, VerificationKind] | None) -> tuple[VerificationKind | None, str | None]:
    if kinds is not None:
        if evidence.identity not in kinds:
            raise ValueError(f"verification kind mapping lacks evidence {evidence.identity}")
        return kinds[evidence.identity], None
    text = f"{evidence.identity} {evidence.output}".lower()
    for kind, words in _KEYWORDS:
        if any(word in text for word in words):
            return kind, "kind inferred from evidence text"
    return None, "kind could not be determined from evidence text"

def _ordered(kinds: set[VerificationKind]) -> tuple[VerificationKind, ...]:
    return tuple(kind for kind in VerificationKind if kind in kinds)

def assess_verification(requested: tuple[VerificationKind, ...], changes: ChangeEvidence, verifications: tuple[VerificationEvidence, ...], *, kinds: Mapping[str, VerificationKind] | None = None) -> VerificationQuality:
    """Measure executed, reported, failed, and missing verification against the request."""
    if not requested:
        raise ValueError("requested verification kinds are required")
    changed = set(changes.created + changes.modified + changes.deleted)
    test_files = {p for p in changed if p.startswith("tests/") or PurePosixPath(p).name.startswith("test_")}
    sources = changed - test_files
    verified: set[VerificationKind] = set()
    failed: set[VerificationKind] = set()
    weakly: set[VerificationKind] = set()
    covered: set[str] = set()
    gaps: list[str] = []
    uncertainties: list[str] = []
    for evidence in verifications:
        kind, uncertainty = _kind_of(evidence, kinds)
        if kind is None:
            gaps.append(f"unclassified:{evidence.identity}")
            continue
        if uncertainty:
            uncertainties.append(f"{evidence.identity}:{uncertainty}")
        if evidence.source is VerificationSource.EXECUTED and evidence.status.lower() in _PASSED:
            verified.add(kind)
            covered |= set(evidence.changed_files)
        elif evidence.source is VerificationSource.EXECUTED:
            failed.add(kind)
        else:
            weakly.add(kind)
    missing = _ordered({kind for kind in requested if kind not in verified and kind not in failed and kind not in weakly})
    coverage = round(len(verified & set(requested)) / len(requested), 3)
    behavior_exercised = bool(verified & {VerificationKind.TESTS}) and (bool(test_files) or bool(covered & changed))
    for kind in requested:
        if kind not in verified and kind not in failed and kind not in weakly:
            gaps.append(f"missing:{kind.value}")
        if kind in failed:
            gaps.append(f"failed:{kind.value}")
        if kind in weakly:
            gaps.append(f"weak:{kind.value}:not_executed")
    unexercised = tuple(sorted(sources - covered))
    return VerificationQuality(
        _ordered(set(requested)), _ordered(verified), _ordered(failed), _ordered(weakly), missing,
        coverage, behavior_exercised, unexercised, tuple(gaps), tuple(uncertainties), _METHOD, _VERSION, ClaimKind.DERIVED,
    )
