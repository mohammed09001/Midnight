"""Verification coverage mathematics; execution evidence stays separate from behavioral proof."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
from .prompt_analysis import PromptFeatures, RequirementType
from .repository_capture import ChangeEvidence
from .verification_quality import VerificationQuality, VerificationKind
from .vector import Dimension

_METHOD = "verification-coverage-math"
_VERSION = "1"

@dataclass(frozen=True, slots=True)
class VerificationCoverageScore:
    verifiable_requirements: int; verified_requirements: int; value: float | None; tests_executed: bool; behavior_proven: bool; evidence_quality: float | None; change_coverage: float | None; method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str

    def dimension(self) -> Dimension:
        return Dimension("verification_quality", self.value, self.claim_kind, self.method, self.method_version, .8 if self.value is not None else None, self.uncertainty)

def score_verification_coverage(features: PromptFeatures, quality: VerificationQuality, changes: ChangeEvidence) -> VerificationCoverageScore:
    """Verified versus verifiable requirements; 'test executed' and 'test proves requested behavior' stay separate."""
    verifiable = [requirement for requirement in features.requirements if requirement.type is RequirementType.VERIFICATION]
    tests_executed = VerificationKind.TESTS in set(quality.verified)
    verified_requirements = len(verifiable) if tests_executed else 0
    value = round(verified_requirements / len(verifiable), 3) if verifiable else None
    behavior_proven = bool(tests_executed and quality.behavior_exercised)
    changed = set(changes.created + changes.modified + changes.deleted)
    test_files = {path for path in changed if path.startswith("tests/") or path.split("/")[-1].startswith("test_")}
    sources = changed - test_files
    change_coverage = round(1 - len(quality.unexercised) / len(sources), 3) if sources else None
    parts = [f"{len(quality.weakly_reported)} requested kinds rest on unexecuted reports"]
    if quality.failed:
        parts.append(f"failed kinds: {list(quality.failed)}")
    parts.append("tests executed is not proof they exercise the requested behavior; behavior_proven tracks that separately")
    return VerificationCoverageScore(
        len(verifiable), verified_requirements, value, tests_executed, behavior_proven,
        quality.coverage if quality.requested else None, change_coverage,
        _METHOD, _VERSION, ClaimKind.DERIVED if verifiable else ClaimKind.UNKNOWN, "; ".join(parts),
    )
