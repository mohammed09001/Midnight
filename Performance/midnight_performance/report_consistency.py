"""Agent final-response report quality versus observed evidence; never code truth."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import re
from pathlib import PurePosixPath
from typing import Mapping
from .alignment import _PATH_LIKE, _path_tokens, _tokens
from .contracts import ClaimKind
from .repository_capture import ChangeEvidence
from .verification import VerificationEvidence, VerificationSource
from .verification_quality import VerificationKind, _PASSED, assess_verification

_METHOD = "report-heuristic"
_VERSION = "1"
_EXCERPT_LIMIT = 240
_CLAIM_VERBS = ("done", "complete", "completed", "implemented", "added", "fixed", "created", "built", "finished", "resolved", "delivered", "working", "refactored", "updated", "removed", "wrote")
_PASS_SIGNALS = ("pass", "passed", "passing", "green", "ran", "run", "executed", "executes")
_ACKNOWLEDGMENTS = ("fail", "error", "broken")
_COMPLETION = re.compile(r"\b(?:" + "|".join(_CLAIM_VERBS) + r")\b")
_TEST_CLAIM = re.compile(r"\btests?\b|\bspecs?\b|\bsuite\b")

class ReportIssue(str, Enum):
    UNSUPPORTED_COMPLETION_CLAIM = "unsupported_completion_claim"; OMITTED_FAILURE = "omitted_failure"; UNVERIFIED_TEST_CLAIM = "unverified_test_claim"; FILE_DISCREPANCY = "file_discrepancy"

@dataclass(frozen=True, slots=True)
class ProseClaim:
    excerpt: str; supported: bool | None; claim_kind: ClaimKind; confidence: float; uncertainty: str
    def __post_init__(self):
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")

@dataclass(frozen=True, slots=True)
class ReportFinding:
    issue: ReportIssue; excerpt: str; confidence: float; method: str; method_version: str; uncertainty: str
    def __post_init__(self):
        if not self.excerpt.strip(): raise ValueError("findings require the prose or evidence excerpt")
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")

@dataclass(frozen=True, slots=True)
class ReportConsistency:
    method_version: str; claims: tuple[ProseClaim, ...]; issues: tuple[ReportFinding, ...]

def _excerpt(sentence: str) -> tuple[str, bool]:
    return (sentence, False) if len(sentence) <= _EXCERPT_LIMIT else (sentence[:_EXCERPT_LIMIT], True)

def assess_report(prose: str, changes: ChangeEvidence, verifications: tuple[VerificationEvidence, ...] = (), *, kinds: Mapping[str, VerificationKind] | None = None) -> ReportConsistency:
    """Compare agent prose with observed change and verification evidence as report quality only."""
    changed = set(changes.created + changes.modified + changes.deleted)
    changed_tokens: set[str] = set()
    for path in changed:
        changed_tokens |= _path_tokens(path)
    quality = assess_verification(tuple(VerificationKind), changes, verifications, kinds=kinds)
    verified, failed = set(quality.verified), set(quality.failed)
    has_tests_changed = any(p.startswith("tests/") or PurePosixPath(p).name.startswith("test_") for p in changed)
    claims: list[ProseClaim] = []
    issues: list[ReportFinding] = []
    for sentence in (part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", prose) if part.strip()):
        low = sentence.lower()
        excerpt, truncated = _excerpt(sentence)
        suffix = "; excerpt truncated" if truncated else ""
        paths = [match.group(0) for match in _PATH_LIKE.finditer(sentence)]
        test_claim = bool(_TEST_CLAIM.search(low))
        completion = bool(_COMPLETION.search(low))
        if completion:
            objects = _tokens(low) - set(_CLAIM_VERBS)
            if paths:
                missing_paths = [path for path in paths if path not in changed]
                claims.append(ProseClaim(excerpt, not missing_paths, ClaimKind.DERIVED, .7, "consistency with observed changes only, not code truth" + suffix))
                if missing_paths:
                    issues.append(ReportFinding(ReportIssue.FILE_DISCREPANCY, excerpt, .8, _METHOD, _VERSION, f"described paths absent from observed changes: {sorted(missing_paths)}" + suffix))
            elif not objects:
                claims.append(ProseClaim(excerpt, None, ClaimKind.UNKNOWN, 0.0, "claim has no assessable object" + suffix))
            elif objects & changed_tokens:
                claims.append(ProseClaim(excerpt, True, ClaimKind.DERIVED, .7, "token-level consistency with observed changes, not code truth" + suffix))
            else:
                claims.append(ProseClaim(excerpt, False, ClaimKind.DERIVED, .7, "no token relation to observed changes" + suffix))
                issues.append(ReportFinding(ReportIssue.UNSUPPORTED_COMPLETION_CLAIM, excerpt, .7, _METHOD, _VERSION, "completion claim without observed change relation" + suffix))
        if test_claim:
            if any(signal in low for signal in _PASS_SIGNALS):
                observed = VerificationKind.TESTS in verified
                uncertainty = "claimed test execution was not observed as executed passing evidence"
            else:
                observed = has_tests_changed
                uncertainty = "claimed tests were not observed among changed test files"
            if observed:
                claims.append(ProseClaim(excerpt, True, ClaimKind.DERIVED, .8, "test claim consistent with observed evidence" + suffix))
            else:
                claims.append(ProseClaim(excerpt, False, ClaimKind.DERIVED, .8, "test claim without observed executed or changed test evidence" + suffix))
                issues.append(ReportFinding(ReportIssue.UNVERIFIED_TEST_CLAIM, excerpt, .8, _METHOD, _VERSION, uncertainty + suffix))
    if failed and not any(word in prose.lower() for word in _ACKNOWLEDGMENTS):
        names = ", ".join(sorted(evidence.identity for evidence in verifications if evidence.source is VerificationSource.EXECUTED and evidence.status.lower() not in _PASSED))
        issues.append(ReportFinding(ReportIssue.OMITTED_FAILURE, f"failed verification: {names}", .9, _METHOD, _VERSION, "prose does not acknowledge observed failed verification"))
    return ReportConsistency(_VERSION, tuple(claims), tuple(issues))
