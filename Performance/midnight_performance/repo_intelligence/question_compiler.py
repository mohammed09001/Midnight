"""Performance → Question Compiler.

Research questions are compiled from evidence-backed internal signals,
never from generic topic extraction.  Compilation is deterministic and
local: no model and no network is involved, so compiling can never spend
model/search budget.  Question text is privacy-minimized by construction
(abstract concept tokens only) unless policy explicitly allows private
identifiers, and semantically equivalent questions collapse onto one
deterministic dedup key before any external call could exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from ..contracts import Identity
from .authorization import RepoIntelligenceAuthorization
from .contracts import (
    BudgetCeiling,
    InternalAnswerStatus,
    QuestionStatus,
    ResearchQuestion,
    research_question_identity,
)
from .signals import ScoredSignal

_STOP_TOKENS = frozenset(
    {
        "src",
        "lib",
        "libs",
        "app",
        "pkg",
        "packages",
        "package",
        "internal",
        "core",
        "py",
        "ts",
        "tsx",
        "js",
        "jsx",
        "json",
        "toml",
        "yaml",
        "yml",
        "md",
        "rst",
        "txt",
        "init",
        "main",
        "utils",
        "util",
        "helpers",
        "helper",
    }
)

_TEMPLATE_KINDS = frozenset(
    {
        "rework",
        "verification_failure",
        "flaky_verification",
        "recurring_intent",
        "rollback",
        "evidence_gap",
        "unfamiliar_subsystem",
        "recurring_task",
        "coupling",
    }
)

_UNKNOWN_WHAT_IS_UNKNOWN = (
    "which established approach applies to this recurring need has not been established"
)
_DEFAULT_WHAT_IS_UNKNOWN = (
    "which proven pattern addresses this recurring failure has not been established"
)
_COUPLING_WHAT_IS_UNKNOWN = (
    "whether the observed co-change coupling reflects a healthy shared contract "
    "or a missing boundary has not been established"
)

_DEFAULT_WHAT_EXTERNAL_WOULD_CHANGE = (
    "an authoritative pattern for this class of problem would confirm or replace "
    "the current local approach"
)
_COUPLING_WHAT_EXTERNAL_WOULD_CHANGE = (
    "an authoritative architectural boundary example for this coupling would confirm "
    "or redirect the current structure"
)


@dataclass(frozen=True, slots=True)
class CompiledQuestion:
    """Result of one compilation attempt; duplicates are named, never re-spent."""

    question: ResearchQuestion | None
    dedup_key: str
    duplicate_of: str | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("compiled question results require a reason")


def abstract_concept(path: str, *, repository_key: str | None = None) -> str:
    """Deterministic abstract concept tokens for a repository path.

    Structural tokens, the repository key, and extensions are dropped so
    the remaining words describe the technical concept, not the private
    filesystem layout.
    """
    if not path.strip():
        raise ValueError("concept extraction requires a path")
    clean = path.replace("\\", "/").lstrip("/")
    repo_tokens: frozenset[str] = (
        frozenset(
            token
            for token in repository_key.lower().replace("-", "_").replace(".", "_").split("_")
            if token
        )
        if repository_key
        else frozenset()
    )
    tokens: list[str] = []
    for part in clean.split("/"):
        for token in part.replace("-", "_").replace(".", "_").split("_"):
            token = token.strip().lower()
            if not token or token in _STOP_TOKENS or token in repo_tokens:
                continue
            if token.isdigit():
                continue
            tokens.append(token)
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        raise ValueError(f"no abstractable concept tokens in path: {path}")
    return " ".join(tokens[:6])


def dedup_key_for(concept: str, template_kind: str) -> str:
    """Semantic dedup anchor: same concept and same question kind collapse."""
    if not concept.strip() or template_kind not in _TEMPLATE_KINDS:
        raise ValueError("dedup keys require a concept and a compilable question kind")
    return f"{template_kind}|{concept}"


def _question_text(template_kind: str, concept: str, second_concept: str | None) -> str:
    if template_kind == "coupling" and second_concept:
        return (
            f"how should responsibilities be divided between {concept} and "
            f"{second_concept} to keep their coupling healthy"
        )
    if template_kind in ("verification_failure", "flaky_verification", "rework"):
        return f"what are reliable patterns to prevent recurring failures in {concept}"
    if template_kind == "rollback":
        return f"what are safer alternatives for {concept} changes that had to be reverted"
    return f"what are established approaches for {concept}"


def compile_question(
    scored: ScoredSignal,
    *,
    project: Identity,
    repository_key: str,
    authorization: RepoIntelligenceAuthorization,
    internal_answer_status: InternalAnswerStatus,
    now: datetime,
    budget: BudgetCeiling,
    existing: Mapping[str, QuestionStatus] | None = None,
) -> CompiledQuestion:
    """Compile one privacy-minimized research question candidate from a signal.

    All-or-nothing: if any compiler field cannot be produced honestly, no
    question is returned.  Signals whose only dimension is churn are never
    compiled — churn alone is not a learning need.  A question the
    internal/Memory check already answers is closed as answered
    internally, so it can never launch external research.  Private
    identifiers stay out of the question text unless the authorization
    explicitly allows them.
    """
    signal = scored.signal
    if signal.claim_kind.value == "unknown":
        return CompiledQuestion(
            question=None,
            dedup_key="",
            duplicate_of=None,
            reason="signal has unknown claim strength; compilation refused",
        )
    if signal.signal_kind not in _TEMPLATE_KINDS:
        return CompiledQuestion(
            question=None,
            dedup_key="",
            duplicate_of=None,
            reason=f"signal kind '{signal.signal_kind}' alone is not a learning need (churn is activity, not a defect)",
        )
    if not signal.summary.strip() or not signal.uncertainty.strip():
        return CompiledQuestion(
            question=None,
            dedup_key="",
            duplicate_of=None,
            reason="signal lacks the bounded evidence summary required for compilation",
        )

    primary_path = scored.paths[0]
    second_path = scored.paths[1] if signal.signal_kind == "coupling" and len(scored.paths) > 1 else None
    try:
        concept = abstract_concept(primary_path, repository_key=repository_key)
        second_concept = (
            abstract_concept(second_path, repository_key=repository_key)
            if second_path
            else None
        )
    except ValueError as error:
        return CompiledQuestion(
            question=None,
            dedup_key="",
            duplicate_of=None,
            reason=f"cannot abstract a concept honestly: {error}",
        )

    template_kind = "coupling" if signal.signal_kind == "coupling" else signal.signal_kind
    key = dedup_key_for(concept, template_kind)

    known_statuses = existing or {}
    status = known_statuses.get(key)
    if status is not None and status not in (
        QuestionStatus.SUPERSEDED,
        QuestionStatus.CANCELLED,
    ):
        identity = research_question_identity(project, key)
        return CompiledQuestion(
            question=None,
            dedup_key=key,
            duplicate_of=identity.canonical,
            reason="semantically equivalent question already exists; no external call needed",
        )

    question_text = _question_text(template_kind, concept, second_concept)
    allow_private = authorization.allow_private_identifiers
    if allow_private:
        question_text = f"{question_text} (component: {primary_path})"
    else:
        private_markers = [repository_key, primary_path] + ([second_path] if second_path else [])
        for marker in private_markers:
            if marker and marker.lower() in question_text.lower():
                return CompiledQuestion(
                    question=None,
                    dedup_key=key,
                    duplicate_of=None,
                    reason=f"privacy check failed: private identifier '{marker}' would leak into the question",
                )

    if internal_answer_status is InternalAnswerStatus.SUFFICIENT:
        status = QuestionStatus.ANSWERED_INTERNAL
        what_is_known = "internal/Memory knowledge already answers this need"
    elif internal_answer_status is InternalAnswerStatus.PARTIAL:
        status = QuestionStatus.OPEN
        what_is_known = "partial internal context exists; the specific gap is unresolved"
    elif internal_answer_status is InternalAnswerStatus.STALE:
        status = QuestionStatus.OPEN
        what_is_known = (
            "internal/Memory knowledge previously answered this need but freshness "
            "requirements are no longer met"
        )
    elif internal_answer_status is InternalAnswerStatus.CONTRADICTED:
        status = QuestionStatus.OPEN
        what_is_known = (
            "internal evidence materially conflicts; contradiction requires resolution "
            "before this can be treated as answered"
        )
    elif internal_answer_status is InternalAnswerStatus.UNKNOWN:
        status = QuestionStatus.OPEN
        what_is_known = "internal sufficiency could not be evaluated reliably"
    else:
        status = QuestionStatus.OPEN
        what_is_known = "no internal knowledge found; recorded as an honest gap, not reconstructed"

    question = ResearchQuestion(
        identity=research_question_identity(project, key),
        project=project,
        question_text=question_text,
        privacy_minimized=True,
        why_now=(
            f"{signal.signal_kind} signal observed in the window ending "
            f"{signal.window_end.isoformat()}"
        ),
        triggered_by=(signal.identity.canonical,) + tuple(signal.evidence_ids)[:4],
        what_is_already_known=what_is_known,
        what_is_unknown=(
            _COUPLING_WHAT_IS_UNKNOWN
            if template_kind == "coupling"
            else (
                _DEFAULT_WHAT_IS_UNKNOWN
                if template_kind in ("verification_failure", "flaky_verification", "rework", "rollback")
                else _UNKNOWN_WHAT_IS_UNKNOWN
            )
        ),
        what_external_evidence_would_change=(
            _COUPLING_WHAT_EXTERNAL_WOULD_CHANGE
            if template_kind == "coupling"
            else _DEFAULT_WHAT_EXTERNAL_WOULD_CHANGE
        ),
        stop_condition="stop at the first authoritative answer that addresses the unknown",
        budget=budget,
        internal_answer_status=internal_answer_status,
        dedup_key=key,
        status=status,
        created_at=now,
    )
    return CompiledQuestion(
        question=question,
        dedup_key=key,
        duplicate_of=None,
        reason="compiled" if status is QuestionStatus.OPEN else "answered internally; no external call needed",
    )


__all__ = [
    "CompiledQuestion",
    "abstract_concept",
    "compile_question",
    "dedup_key_for",
]
