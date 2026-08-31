"""Provider-neutral Performance evaluators; evaluations are qualified projections, never source evidence."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, Protocol
from .contracts import ClaimKind

_METHOD = "performance-evaluation"
_VERSION = "1"

class EvaluatorKind(str, Enum):
    DETERMINISTIC = "deterministic"; STATISTICAL = "statistical"; USER_LABEL = "user_label"; MODEL_JUDGE = "model_judge"; CUSTOM = "custom"

@dataclass(frozen=True, slots=True)
class EvaluationResult:
    subject_id: str; evaluator: str; evaluator_version: str; kind: EvaluatorKind; score: float | None
    evidence: tuple[str, ...]; explanation: str; confidence: float | None; claim_kind: ClaimKind
    def __post_init__(self) -> None:
        if not all((self.subject_id.strip(), self.evaluator.strip(), self.evaluator_version.strip(), self.explanation.strip())): raise ValueError("evaluation identity and explanation are required")
        if self.score is not None and not 0 <= self.score <= 1: raise ValueError("evaluation score must be zero-one")
        if self.confidence is not None and not 0 <= self.confidence <= 1: raise ValueError("evaluation confidence must be zero-one")

class Evaluator(Protocol):
    def evaluate(self, subject_id: str, values: Mapping[str, float | None], evidence: Mapping[str, tuple[str, ...]]) -> EvaluationResult: ...

@dataclass(frozen=True, slots=True)
class DeterministicEvaluator:
    name: str; metric: str; inverse: bool = False; version: str = _VERSION
    def evaluate(self, subject_id: str, values: Mapping[str, float | None], evidence: Mapping[str, tuple[str, ...]]) -> EvaluationResult:
        value = values.get(self.metric)
        if value is not None and not 0 <= value <= 1: raise ValueError("deterministic evaluator values must be zero-one")
        score = None if value is None else round(1 - value if self.inverse else value, 3)
        return EvaluationResult(subject_id, self.name, self.version, EvaluatorKind.DETERMINISTIC, score, evidence.get(self.metric, ()), f"deterministic {self.metric}" + ("; unknown input" if score is None else ""), 1.0 if score is not None else None, ClaimKind.DERIVED if score is not None else ClaimKind.UNKNOWN)

def deterministic_evaluators() -> tuple[DeterministicEvaluator, ...]:
    """Canonical first-pass evaluators; callers supply outputs from their existing authoritative analyzers."""
    return (
        DeterministicEvaluator("requirement_coverage", "requirement_coverage"), DeterministicEvaluator("constraint_violations", "constraint_violation_rate", True),
        DeterministicEvaluator("verification_evidence", "verification_coverage"), DeterministicEvaluator("unexpected_deletions", "unexpected_deletion_rate", True),
        DeterministicEvaluator("scope_expansion", "scope_expansion_rate", True), DeterministicEvaluator("test_build_outcomes", "test_build_success"),
        DeterministicEvaluator("agent_report_consistency", "report_consistency"),
    )

def evaluate_deterministically(subject_id: str, values: Mapping[str, float | None], evidence: Mapping[str, tuple[str, ...]]) -> tuple[EvaluationResult, ...]:
    return tuple(evaluator.evaluate(subject_id, values, evidence) for evaluator in deterministic_evaluators())

@dataclass(frozen=True, slots=True)
class JudgeConfiguration:
    provider: str; model: str; prompt_version: str; maximum_cost: float; content_allowed: bool; require_repeatability: bool = True
    def __post_init__(self) -> None:
        if not all((self.provider.strip(), self.model.strip(), self.prompt_version.strip())) or self.maximum_cost < 0: raise ValueError("judge configuration requires provider/model/prompt and non-negative cost")

@dataclass(frozen=True, slots=True)
class JudgeResponse:
    score: float; explanation: str; cost: float
    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1 or not self.explanation.strip() or self.cost < 0: raise ValueError("judge response must be bounded, explained, and non-negative cost")

def evaluate_with_judge(subject_id: str, criterion: str, content: str, config: JudgeConfiguration, judge: Callable[[str], JudgeResponse]) -> EvaluationResult:
    """Run an injected judge only with explicit content permission, budget, and repeatability evidence."""
    if not config.content_allowed: raise PermissionError("judge content is not privacy-authorized")
    if not criterion.strip() or not content.strip(): raise ValueError("judge criterion and content are required")
    first = judge(content)
    if first.cost > config.maximum_cost: raise PermissionError("judge cost exceeds configured maximum")
    if config.require_repeatability:
        second = judge(content)
        if second.cost > config.maximum_cost or (first.score, first.explanation) != (second.score, second.explanation):
            return EvaluationResult(subject_id, criterion, config.prompt_version, EvaluatorKind.MODEL_JUDGE, None, (f"provider={config.provider}", f"model={config.model}"), "judge was not repeatable; score withheld", None, ClaimKind.UNKNOWN)
    return EvaluationResult(subject_id, criterion, config.prompt_version, EvaluatorKind.MODEL_JUDGE, first.score, (f"provider={config.provider}", f"model={config.model}", f"cost={first.cost}"), first.explanation, .5, ClaimKind.INFERRED)
