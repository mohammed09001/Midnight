"""Combined multi-view retrieval over prior prompt experiences: prompt structure, task taxonomy, agent execution, repository change, verification, feedback, semantic/vector, relationship-graph, and sibling-outcome signals. A rebuildable projection, never a performance judgment, ground truth, or one opaque nearest-neighbor score."""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from typing import Mapping
from .associations import OutcomeAssociation
from .contracts import ClaimKind
from .feedback import FeedbackRecord
from .outcome_similarity import cross_domain_outcome_similarity
from .prompt_analysis import PromptFeatures, RequirementType
from .prompt_run import PromptRun
from .relationship_graph import graph_reference_overlap
from .repo_change_similarity import repository_change_similarity
from .repository_capture import ChangeEvidence
from .semantic_similarity import EmbeddingVector, embedding_similarity
from .taxonomy import TaxonomyClassification
from .verification import VerificationEvidence

_METHOD = "multi-view-experience-retrieval"
_VERSION = "1"
_DEFAULT_WEIGHTS: dict[str, float] = {
    "lexical_overlap": 1.0, "code_terms": 1.0, "task_category": 1.0,
    "prompt_features": 1.0, "referenced_components": 1.0, "structured_requirements": 1.0,
    "semantic_similarity": 1.0, "repository_change": 1.0, "cross_domain_outcome": 1.0,
    "verification_overlap": 1.0, "feedback_overlap": 1.0,
    "agent_execution": 1.0, "graph_traversal": 1.0,
}
_WORD_PATTERN = re.compile(r"[a-z0-9_]+")
_CODE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_EMPTY_CHANGES = ChangeEvidence((), (), ())


@dataclass(frozen=True, slots=True)
class Experience:
    """One prompt run available for retrieval; the taxonomy is required, every other evidence view is optional."""
    prompt_run_id: str; text: str; features: PromptFeatures; taxonomy: TaxonomyClassification
    changes: ChangeEvidence = _EMPTY_CHANGES; outcomes: tuple[OutcomeAssociation, ...] = ()
    verifications: tuple[VerificationEvidence, ...] = (); feedback: tuple[FeedbackRecord, ...] = ()
    embedding: EmbeddingVector | None = None
    agent_metadata: Mapping[str, str] = field(default_factory=dict)
    prompt_run: PromptRun | None = None

    def __post_init__(self):
        if not self.prompt_run_id.strip(): raise ValueError("experience requires a prompt run id")
        if not self.text.strip(): raise ValueError("experience requires prompt text")
        if self.taxonomy.subject_id != self.prompt_run_id: raise ValueError("taxonomy classification subject must match the experience prompt run id")
        if any(item.prompt_run_id != self.prompt_run_id for item in self.outcomes): raise ValueError("outcome associations must belong to this experience's prompt run id")
        if any(item.prompt_run_id != self.prompt_run_id for item in self.feedback): raise ValueError("feedback records must belong to this experience's prompt run id")
        if self.prompt_run is not None and self.prompt_run.prompt_run_id != self.prompt_run_id: raise ValueError("linked prompt run must belong to this experience's prompt run id")


@dataclass(frozen=True, slots=True)
class SimilaritySignal:
    name: str; value: float | None; weight: float; evidence: tuple[str, ...]

    def __post_init__(self):
        if not self.name.strip(): raise ValueError("signal name is required")
        if self.value is not None and not 0 <= self.value <= 1: raise ValueError("signal value must be between zero and one")
        if self.weight < 0: raise ValueError("signal weight must not be negative")


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    prompt_run_id: str; score: float | None; signals: tuple[SimilaritySignal, ...]; reasons: tuple[str, ...]; method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str

    def __post_init__(self):
        if not self.prompt_run_id.strip(): raise ValueError("match requires a prompt run id")
        if self.score is not None and not 0 <= self.score <= 1: raise ValueError("score must be between zero and one")
        if not self.reasons: raise ValueError("a match must always carry at least one explanatory reason")


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_WORD_PATTERN.findall(text.lower()))


def _code_tokens(text: str) -> frozenset[str]:
    """Snake_case identifiers and dotted paths/modules; a trailing sentence period does not count as a dot."""
    return frozenset(token for token in _CODE_PATTERN.findall(text) if "_" in token or ("." in token and not token.endswith(".")))


def _jaccard(a: frozenset, b: frozenset) -> float | None:
    union = a | b
    return round(len(a & b) / len(union), 3) if union else None


def _type_counts(features: PromptFeatures) -> dict[RequirementType, int]:
    counts = {kind: 0 for kind in RequirementType}
    for requirement in features.requirements:
        counts[requirement.type] += 1
    return counts


def _shape_similarity(a: PromptFeatures, b: PromptFeatures) -> float | None:
    counts_a, counts_b = _type_counts(a), _type_counts(b)
    total = sum(counts_a.values()) + sum(counts_b.values())
    if not total:
        return None
    difference = sum(abs(counts_a[kind] - counts_b[kind]) for kind in counts_a)
    return round(1 - difference / total, 3)


def match(query: Experience, experience: Experience, *, weights: Mapping[str, float] | None = None) -> SimilarityMatch:
    """Score one candidate experience against a query across every available signal view, each cited with its own evidence and never collapsed into a single opaque nearest-neighbor score."""
    weights = _DEFAULT_WEIGHTS if weights is None else weights
    if not any(weight > 0 for weight in weights.values()):
        raise ValueError("similarity requires at least one positively weighted signal")
    query_tokens, candidate_tokens = _tokens(query.text), _tokens(experience.text)
    query_code, candidate_code = _code_tokens(query.text), _code_tokens(experience.text)
    query_requirements = frozenset(item.text for item in query.features.requirements)
    candidate_requirements = frozenset(item.text for item in experience.features.requirements)
    query_areas, candidate_areas = frozenset(query.taxonomy.areas), frozenset(experience.taxonomy.areas)
    query_components, candidate_components = frozenset(query.taxonomy.repository_specific), frozenset(experience.taxonomy.repository_specific)
    query_verifications = frozenset((item.source.value, item.status) for item in query.verifications)
    candidate_verifications = frozenset((item.source.value, item.status) for item in experience.verifications)
    query_feedback = frozenset(item.judgment.value for item in query.feedback) | frozenset(reason.value for item in query.feedback for reason in item.reasons)
    candidate_feedback = frozenset(item.judgment.value for item in experience.feedback) | frozenset(reason.value for item in experience.feedback for reason in item.reasons)
    query_agent = frozenset(f"{key}={value}" for key, value in query.agent_metadata.items())
    candidate_agent = frozenset(f"{key}={value}" for key, value in experience.agent_metadata.items())

    signals: list[SimilaritySignal] = []

    def add(name: str, value: float | None, evidence: tuple[str, ...]) -> None:
        signals.append(SimilaritySignal(name, value, weights.get(name, 0.0), evidence))

    add("lexical_overlap", _jaccard(query_tokens, candidate_tokens), tuple(sorted(query_tokens & candidate_tokens))[:10])
    add("code_terms", _jaccard(query_code, candidate_code), tuple(sorted(query_code & candidate_code))[:10])
    add("task_category", _jaccard(query_areas, candidate_areas), tuple(sorted(query_areas & candidate_areas)))
    add("prompt_features", _shape_similarity(query.features, experience.features), ())
    add("referenced_components", _jaccard(query_components, candidate_components), tuple(sorted(query_components & candidate_components)))
    add("structured_requirements", _jaccard(query_requirements, candidate_requirements), tuple(sorted(query_requirements & candidate_requirements))[:5])
    semantic_value, semantic_evidence = embedding_similarity(query.embedding, experience.embedding)
    add("semantic_similarity", semantic_value, semantic_evidence)
    repo_change_value, repo_change_evidence = repository_change_similarity(query.changes, experience.changes)
    add("repository_change", repo_change_value, repo_change_evidence)
    outcome_value, outcome_evidence = cross_domain_outcome_similarity(query.outcomes, experience.outcomes)
    add("cross_domain_outcome", outcome_value, outcome_evidence)
    add("verification_overlap", _jaccard(query_verifications, candidate_verifications), tuple(sorted(f"{source}:{status}" for source, status in (query_verifications & candidate_verifications))))
    add("feedback_overlap", _jaccard(query_feedback, candidate_feedback), tuple(sorted(query_feedback & candidate_feedback)))
    add("agent_execution", _jaccard(query_agent, candidate_agent), tuple(sorted(query_agent & candidate_agent)))
    if query.prompt_run is not None and experience.prompt_run is not None:
        graph_value, graph_evidence = graph_reference_overlap(query.prompt_run, experience.prompt_run)
    else:
        graph_value, graph_evidence = None, ()
    add("graph_traversal", graph_value, graph_evidence)

    valued = [(signal.value, signal.weight) for signal in signals if signal.value is not None and signal.weight > 0]
    weight_total = sum(weight for _, weight in valued)
    score = round(sum(value * weight for value, weight in valued) / weight_total, 3) if weight_total else None
    reasons = [
        f"{signal.name.replace('_', ' ')}={signal.value}: {list(signal.evidence)}" if signal.evidence else f"{signal.name.replace('_', ' ')}={signal.value}"
        for signal in signals if signal.value
    ]
    if not reasons:
        reasons = ["no lexical, code-term, category, shape, component, embedding, repository-change, outcome, verification, feedback, agent-execution, or graph-traversal overlap was found"]
    undefined = tuple(signal.name for signal in signals if signal.value is None)
    parts = [
        "prompt structure, task taxonomy, agent execution, repository change, verification, feedback, semantic/vector, relationship-graph, and sibling-outcome overlap; each signal is reported separately and never collapsed into one opaque nearest-neighbor score",
        "vector distance and graph adjacency are retrieval evidence, not truth, and none of this is a performance judgment",
    ]
    if undefined:
        parts.append(f"signals with nothing to compare on either side, an unembedded/unlinked run, or incommensurable embedding providers stay unknown, not zero: {list(undefined)}")
    return SimilarityMatch(
        experience.prompt_run_id, score, tuple(signals), tuple(reasons),
        _METHOD, _VERSION, ClaimKind.DERIVED if score is not None else ClaimKind.UNKNOWN, "; ".join(parts),
    )


def retrieve(query: Experience, experiences: tuple[Experience, ...], *, top_k: int = 5, weights: Mapping[str, float] | None = None, min_score: float = 0.0) -> tuple[SimilarityMatch, ...]:
    """Rank prior experiences by similarity to the query; an index-time projection, never canonical Performance state."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not 0 <= min_score <= 1:
        raise ValueError("min_score must be between zero and one")
    matches = tuple(match(query, experience, weights=weights) for experience in experiences)
    ranked = sorted((item for item in matches if item.score is not None and item.score >= min_score), key=lambda item: item.score, reverse=True)
    return tuple(ranked[:top_k])
