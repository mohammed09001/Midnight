"""Prompt-fragment to code-change alignment judgments with explicit evidence."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import re
from pathlib import PurePosixPath
from .contracts import ClaimKind
from .prompt_analysis import PromptFeatures, RequirementType
from .repository_capture import ChangeEvidence

_METHOD = "alignment-heuristic"
_VERSION = "1"
_STOPWORDS = frozenset({"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "must", "should", "not", "do", "dont", "be", "is", "are", "was", "were", "that", "this", "it", "its", "as", "at", "by", "from", "into", "all", "any", "new", "add", "added", "use", "using", "keep", "when", "then", "than", "so", "if", "but", "about", "each", "file", "files", "code", "change", "changes", "changed"})
_PATH_LIKE = re.compile(r"[\w\-./]+\.(?:py|js|ts|tsx|json|toml|md|txt|yaml|yml|rst)")

class AlignmentStatus(str, Enum):
    SATISFIED = "satisfied"; PARTIALLY_SATISFIED = "partially_satisfied"; NOT_SATISFIED = "not_satisfied"; CONTRADICTED = "contradicted"; INSUFFICIENT_EVIDENCE = "insufficient_evidence"

@dataclass(frozen=True, slots=True)
class RequirementAlignment:
    text: str; start: int; end: int; status: AlignmentStatus; evidence: tuple[str, ...]; claim_kind: ClaimKind; confidence: float; method: str; method_version: str; uncertainty: str
    def __post_init__(self):
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")

@dataclass(frozen=True, slots=True)
class AlignmentResult:
    method_version: str; judgments: tuple[RequirementAlignment, ...]

def _normalize(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token

def _tokens(text: str) -> set[str]:
    return {_normalize(x) for x in re.split(r"[^a-z0-9]+", text.lower()) if len(x) >= 3 and x not in _STOPWORDS}

def _path_tokens(path: str) -> set[str]:
    tokens: set[str] = set()
    for part in PurePosixPath(path).parts[:-1]:
        tokens.update(_normalize(x) for x in re.split(r"[^a-z0-9]+", part.lower()) if len(x) >= 3)
    tokens.update(_normalize(x) for x in re.split(r"[^a-z0-9]+", PurePosixPath(path).stem.lower()) if len(x) >= 3)
    return tokens

def _banned_paths(text: str) -> set[str]:
    return {match.group(0).lower() for match in _PATH_LIKE.finditer(text)}

def align(features: PromptFeatures, changes: ChangeEvidence) -> AlignmentResult:
    """Judge every extracted requirement against repository change evidence only."""
    changed = set(changes.created + changes.modified + changes.deleted)
    judged: list[RequirementAlignment] = []
    for requirement in features.requirements:
        banned = _banned_paths(requirement.text)
        hit = tuple(sorted(p for p in changed if p.lower() in banned or PurePosixPath(p).as_posix() in banned))
        if requirement.type is RequirementType.CONSTRAINT and banned and hit:
            judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.CONTRADICTED, hit, ClaimKind.DERIVED, .9, _METHOD, _VERSION, "constraint forbids changing the listed path"))
            continue
        if requirement.type is RequirementType.CONSTRAINT:
            judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.INSUFFICIENT_EVIDENCE, (), ClaimKind.UNKNOWN, 0.0, _METHOD, _VERSION, "path evidence can falsify a constraint but cannot confirm compliance"))
            continue
        if requirement.type is RequirementType.VERIFICATION:
            if any(p.startswith("tests/") or PurePosixPath(p).name.startswith("test_") for p in changed):
                judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.PARTIALLY_SATISFIED, (), ClaimKind.DERIVED, .6, _METHOD, _VERSION, "verification files changed but execution evidence is not change evidence"))
            else:
                judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.INSUFFICIENT_EVIDENCE, (), ClaimKind.UNKNOWN, 0.0, _METHOD, _VERSION, "no verification evidence exists in the changes"))
            continue
        tokens = _tokens(requirement.text)
        if not tokens or not changed:
            judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.INSUFFICIENT_EVIDENCE, (), ClaimKind.UNKNOWN, 0.0, _METHOD, _VERSION, "no comparable tokens" if tokens else "no repository changes to compare"))
            continue
        union: set[str] = set()
        for path in changed:
            union |= _path_tokens(path)
        matched = tokens & union
        evidence = tuple(sorted(p for p in changed if matched and tokens & _path_tokens(p)))
        score = len(matched) / len(tokens)
        if score == 0:
            judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.NOT_SATISFIED, (), ClaimKind.DERIVED, .5, _METHOD, _VERSION, "changes exist but none relate to the requirement"))
        elif score < 1:
            judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.PARTIALLY_SATISFIED, evidence, ClaimKind.DERIVED, round(.8 * score, 3), _METHOD, _VERSION, "token-level path match, not behavioral proof"))
        else:
            judged.append(RequirementAlignment(requirement.text, requirement.start, requirement.end, AlignmentStatus.SATISFIED, evidence, ClaimKind.DERIVED, .8, _METHOD, _VERSION, "token-level path match, not behavioral proof"))
    return AlignmentResult(_VERSION, tuple(judged))
