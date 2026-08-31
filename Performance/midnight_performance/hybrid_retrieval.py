"""Hybrid retrieval over rebuildable Performance projections.

The ledger remains the canonical owner of observations.  This module only
combines supplied, already-authorized experiences, embeddings, and graph
projections into an explainable retrieval view; it neither persists an index
nor calls a sibling product.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re

from .relationship_graph import PerformanceGraph
from .semantic_similarity import embedding_similarity
from .similarity import Experience
from .contracts import ClaimKind, EntityKind, deterministic_identity


_METHOD = "hybrid-relational-vector-graph-retrieval"
_VERSION = "1"
_WORD = re.compile(r"[a-z0-9_]+")
_CODE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


class RetrievalPath(str, Enum):
    RELATIONAL = "relational"
    VECTOR = "vector"
    GRAPH = "graph"
    LEXICAL = "lexical"


@dataclass(frozen=True, slots=True)
class RetrievalEntry:
    """One time-stamped experience in a rebuildable retrieval projection."""

    experience: Experience
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("retrieval entry timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class HybridQuery:
    """Query and exact filters. Dates are inclusive and do not infer missing time."""

    experience: Experience
    prompt_run_ids: frozenset[str] = frozenset()
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    max_graph_depth: int = 3
    exclude_self: bool = True

    def __post_init__(self) -> None:
        if any(not value.strip() for value in self.prompt_run_ids):
            raise ValueError("prompt_run_ids must be non-empty")
        if self.observed_from is not None and self.observed_from.tzinfo is None:
            raise ValueError("observed_from must be timezone-aware")
        if self.observed_to is not None and self.observed_to.tzinfo is None:
            raise ValueError("observed_to must be timezone-aware")
        if self.observed_from and self.observed_to and self.observed_from > self.observed_to:
            raise ValueError("observed_from must not be after observed_to")
        if self.max_graph_depth < 1:
            raise ValueError("max_graph_depth must be positive")


@dataclass(frozen=True, slots=True)
class RetrievalContribution:
    path: RetrievalPath
    value: float | None
    evidence: tuple[str, ...]
    claim_kind: ClaimKind = ClaimKind.DERIVED

    def __post_init__(self) -> None:
        if self.value is not None and not 0 <= self.value <= 1:
            raise ValueError("retrieval contribution value must be between zero and one")


@dataclass(frozen=True, slots=True)
class HybridResult:
    prompt_run_id: str
    score: float
    contributions: tuple[RetrievalContribution, ...]
    method: str = _METHOD
    method_version: str = _VERSION
    claim_kind: ClaimKind = ClaimKind.DERIVED
    uncertainty: str = (
        "relational filters are exact gates; vector and graph indexes are rebuildable "
        "retrieval evidence, not canonical truth or a performance judgment"
    )


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall(text.lower()))


def _technical_terms(text: str) -> frozenset[str]:
    return frozenset(term.lower() for term in _CODE.findall(text) if "_" in term or "." in term)


def _overlap(left: frozenset[str], right: frozenset[str]) -> tuple[float | None, tuple[str, ...]]:
    union = left | right
    if not union:
        return None, ()
    shared = tuple(sorted(left & right))
    return round(len(shared) / len(union), 3), shared


def _graph_distance(graph: PerformanceGraph | None, query_id: str, candidate_id: str, max_depth: int) -> int | None:
    """Find the shortest undirected lineage path without treating direct text overlap as graph evidence."""
    if graph is None:
        return None
    start = deterministic_identity(EntityKind.PROMPT_RUN, query_id)
    target = deterministic_identity(EntityKind.PROMPT_RUN, candidate_id)
    if start == target:
        return 0
    neighbors: dict[object, list[object]] = {}
    for edge in graph.edges:
        neighbors.setdefault(edge.source, []).append(edge.target)
        neighbors.setdefault(edge.target, []).append(edge.source)
    frontier = [start]
    seen = {start}
    for depth in range(1, max_depth + 1):
        next_frontier = []
        for node in frontier:
            for neighbor in neighbors.get(node, ()):
                if neighbor == target:
                    return depth
                if neighbor not in seen:
                    seen.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
    return None


def _passes_filters(query: HybridQuery, entry: RetrievalEntry) -> bool:
    candidate_id = entry.experience.prompt_run_id
    if query.exclude_self and candidate_id == query.experience.prompt_run_id:
        return False
    if query.prompt_run_ids and candidate_id not in query.prompt_run_ids:
        return False
    if query.observed_from is not None and entry.observed_at < query.observed_from:
        return False
    return not (query.observed_to is not None and entry.observed_at > query.observed_to)


def retrieve_hybrid(query: HybridQuery, entries: tuple[RetrievalEntry, ...], *, graph: PerformanceGraph | None = None, top_k: int = 5, min_score: float = 0.0) -> tuple[HybridResult, ...]:
    """Filter exact identities/times, then rank lexical, vector, and multi-hop graph evidence.

    Lexical/structured matching is always available and is the deterministic
    fallback when embeddings are absent or graph traversal finds no route.
    """
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not 0 <= min_score <= 1:
        raise ValueError("min_score must be between zero and one")
    ids = [entry.experience.prompt_run_id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("retrieval entries must have unique prompt run ids")
    filtered = tuple(entry for entry in entries if _passes_filters(query, entry))
    query_words, query_terms = _tokens(query.experience.text), _technical_terms(query.experience.text)
    filters_active = bool(query.prompt_run_ids or query.observed_from or query.observed_to)
    results: list[HybridResult] = []
    for entry in filtered:
        candidate = entry.experience
        word_score, words = _overlap(query_words, _tokens(candidate.text))
        term_score, terms = _overlap(query_terms, _technical_terms(candidate.text))
        lexical_values = [value for value in (word_score, term_score) if value is not None]
        lexical_score = round(sum(lexical_values) / len(lexical_values), 3) if lexical_values else 0.0
        lexical_evidence = tuple(f"term:{term}" for term in terms[:10]) + tuple(f"word:{word}" for word in words[:10] if word not in terms)
        vector_score, vector_evidence = embedding_similarity(query.experience.embedding, candidate.embedding)
        distance = _graph_distance(graph, query.experience.prompt_run_id, candidate.prompt_run_id, query.max_graph_depth)
        graph_score = round(1 / distance, 3) if distance else None
        graph_evidence = (f"shortest undirected graph path: {distance} hop(s)",) if distance else ()
        contributions = []
        if filters_active:
            evidence = []
            if query.prompt_run_ids:
                evidence.append("exact prompt_run_id filter")
            if query.observed_from or query.observed_to:
                evidence.append("inclusive observed_at filter")
            contributions.append(RetrievalContribution(RetrievalPath.RELATIONAL, 1.0, tuple(evidence)))
        contributions.append(RetrievalContribution(RetrievalPath.LEXICAL, lexical_score, lexical_evidence))
        if vector_score is not None:
            contributions.append(RetrievalContribution(RetrievalPath.VECTOR, vector_score, vector_evidence))
        if graph_score is not None:
            contributions.append(RetrievalContribution(RetrievalPath.GRAPH, graph_score, graph_evidence))
        ranking_values = [item.value for item in contributions if item.path is not RetrievalPath.RELATIONAL and item.value is not None]
        score = round(sum(ranking_values) / len(ranking_values), 3) if ranking_values else 0.0
        if score >= min_score:
            results.append(HybridResult(candidate.prompt_run_id, score, tuple(contributions)))
    return tuple(sorted(results, key=lambda item: (-item.score, item.prompt_run_id))[:top_k])
