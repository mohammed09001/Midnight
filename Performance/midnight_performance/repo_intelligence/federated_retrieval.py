"""One bounded retrieval interface over the project knowledge overlay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .authorization import RepoIntelligenceAuthorization, require_active_authorization
from .contracts import EdgeClass, GraphLink
from .cost_quality import prune_communities
from .graph_traversal import communities, traverse
from .project_graph import NodeFamily, ProjectKnowledgeGraph


class QueryClass(str, Enum):
    ENTITY_LOCAL = "entity_local"
    ACTIVITY_LOCAL = "activity_local"
    PROJECT_GLOBAL = "project_global"
    EXTERNAL_ANALOGUE = "external_analogue"
    LEARNING_PATH = "learning_path"
    PROVENANCE_PATH = "provenance_path"


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    anchor_identity: str | None = None
    exact_identities: tuple[str, ...] = ()
    allow_external: bool = False

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > 500:
            raise ValueError("retrieval query text must be non-empty and bounded")


@dataclass(frozen=True, slots=True)
class RetrievalControls:
    maximum_hops: int = 3
    maximum_nodes: int = 100
    maximum_communities: int = 4
    maximum_follow_up_questions: int = 2
    community_relevance_threshold: float = 0.2
    minimum_information_gain: float = 0.1

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_hops <= 8 or not 1 <= self.maximum_nodes <= 500:
            raise ValueError("retrieval traversal exceeds hard caps")
        if self.maximum_communities < 0 or self.maximum_follow_up_questions < 0:
            raise ValueError("retrieval expansion limits cannot be negative")
        if not 0 <= self.community_relevance_threshold <= 1 or not 0 <= self.minimum_information_gain <= 1:
            raise ValueError("retrieval gain thresholds must be between zero and one")


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    query_class: QueryClass
    stages: tuple[str, ...]
    external_expansion_eligible: bool
    stop_condition: str


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    identity: str
    label: str
    family: NodeFamily
    score: float
    basis: str
    uncertainty: str


@dataclass(frozen=True, slots=True)
class ExplainedHop:
    source: str
    relation: str
    target: str
    edge_type: str
    uncertainty: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgePath:
    source: str
    target: str
    hops: tuple[ExplainedHop, ...]
    found: bool


@dataclass(frozen=True, slots=True)
class FederatedRetrievalResult:
    plan: RetrievalPlan
    hits: tuple[RetrievalHit, ...]
    path: KnowledgePath | None
    selected_communities: tuple[tuple[str, ...], ...]
    follow_up_questions: tuple[str, ...]
    external_lookup_required: bool
    gaps: tuple[str, ...]
    truncated: bool


def classify_query(query: RetrievalQuery) -> QueryClass:
    text = query.text.lower()
    if query.exact_identities or any(term in text for term in ("why believe", "provenance", "evidence path", "where did")):
        return QueryClass.PROVENANCE_PATH
    if any(term in text for term in ("external", "other project", "analogue", "similar repository")):
        return QueryClass.EXTERNAL_ANALOGUE
    if any(term in text for term in ("what should i understand", "learn next", "learning path")):
        return QueryClass.LEARNING_PATH
    if any(term in text for term in ("hotspot", "what happened", "failed verification", "activity")):
        return QueryClass.ACTIVITY_LOCAL
    if any(term in text for term in ("catch me up", "project themes", "architecture evolution", "project-wide")):
        return QueryClass.PROJECT_GLOBAL
    return QueryClass.ENTITY_LOCAL


def plan_retrieval(query: RetrievalQuery) -> RetrievalPlan:
    kind = classify_query(query)
    stages = ["exact_typed_references", "lexical_labels", "structural_neighbors", "temporal_relationships"]
    if kind in (QueryClass.EXTERNAL_ANALOGUE, QueryClass.LEARNING_PATH):
        stages.append("semantic_if_quality_gap")
    if kind in (QueryClass.PROJECT_GLOBAL, QueryClass.LEARNING_PATH, QueryClass.EXTERNAL_ANALOGUE):
        stages.append("bounded_lazy_community_traversal")
    eligible = kind is QueryClass.EXTERNAL_ANALOGUE and query.allow_external
    if eligible:
        stages.append("external_adapter_if_authorized_and_budgeted")
    return RetrievalPlan(kind, tuple(stages), eligible, "stop on node/hop/community limits or insufficient marginal information gain")


def _tokens(text: str) -> frozenset[str]:
    normalized = text
    for separator in ".,:;!?()[]{}_/\\-":
        normalized = normalized.replace(separator, " ")
    return frozenset(token.lower() for token in normalized.split() if len(token) >= 3)


def _path(graph: ProjectKnowledgeGraph, source: str, target: str, *, now: datetime, max_hops: int) -> KnowledgePath:
    if source == target:
        return KnowledgePath(source, target, (), True)
    parents: dict[str, tuple[str, GraphLink]] = {}
    visited = {source}
    frontier = [source]
    for _ in range(max_hops):
        next_frontier = []
        for current in sorted(frontier):
            links = sorted((link for link in graph.links_for(current) if not link.is_stale(now)), key=lambda link: link.identity.canonical)
            for link in links:
                other = link.target if link.source == current else link.source
                if other in visited:
                    continue
                visited.add(other)
                parents[other] = (current, link)
                if other == target:
                    hops = []
                    cursor = target
                    while cursor != source:
                        previous, used = parents[cursor]
                        hops.append(ExplainedHop(previous, used.relation.value, cursor, "exact" if used.edge_class is EdgeClass.STRUCTURAL else "probabilistic", used.uncertainty, used.evidence_ids))
                        cursor = previous
                    return KnowledgePath(source, target, tuple(reversed(hops)), True)
                next_frontier.append(other)
        frontier = next_frontier
        if not frontier:
            break
    return KnowledgePath(source, target, (), False)


def retrieve(graph: ProjectKnowledgeGraph, query: RetrievalQuery, authorization: RepoIntelligenceAuthorization, *, now: datetime, controls: RetrievalControls = RetrievalControls(), information_gain: float = 0.0, memory_available: bool = True) -> FederatedRetrievalResult:
    if now.tzinfo is None:
        raise ValueError("retrieval time must be timezone-aware")
    if not 0 <= information_gain <= 1:
        raise ValueError("information gain must be between zero and one")
    require_active_authorization(authorization, now=now)
    if graph.project != authorization.project.canonical:
        raise PermissionError("cross-project federated graph access denied")
    plan = plan_retrieval(query)
    nodes = {node.identity: node for node in graph.nodes}
    active_graph = ProjectKnowledgeGraph(graph.project, graph.repository_key, graph.nodes, tuple(link for link in graph.links if not link.is_stale(now)), graph.generation, graph.built_at, graph.gaps, graph.schema_version)
    hits: dict[str, RetrievalHit] = {}
    for identity in query.exact_identities:
        node = nodes.get(identity)
        if node:
            hits[identity] = RetrievalHit(identity, node.label, node.family, 1.0, "exact typed reference", "none; exact overlay node identity")
    query_tokens = _tokens(query.text)
    for node in graph.nodes:
        overlap = len(query_tokens & _tokens(node.label))
        if overlap:
            score = round(overlap / max(1, len(query_tokens)), 6)
            previous = hits.get(node.identity)
            if previous is None or score > previous.score:
                hits[node.identity] = RetrievalHit(node.identity, node.label, node.family, score, "lexical label match", "label match does not prove semantic relevance")

    anchor = query.anchor_identity
    if anchor is not None and anchor not in nodes:
        raise ValueError("query anchor is not present in the graph")
    if anchor is None and hits:
        anchor = sorted(hits.values(), key=lambda hit: (-hit.score, hit.identity))[0].identity
    truncated = False
    if anchor:
        traversal = traverse(active_graph, anchor, max_hops=controls.maximum_hops, max_nodes=controls.maximum_nodes)
        truncated = traversal.truncated
        for identity in traversal.visited:
            node = nodes[identity]
            hits.setdefault(identity, RetrievalHit(identity, node.label, node.family, .35, "bounded structural/temporal traversal", "graph projection edge; inspect path evidence"))

    selected_communities: tuple[tuple[str, ...], ...] = ()
    if plan.query_class in (QueryClass.PROJECT_GLOBAL, QueryClass.LEARNING_PATH, QueryClass.EXTERNAL_ANALOGUE):
        groups = communities(active_graph, max_communities=max(1, controls.maximum_communities or 1))
        scored = []
        for index, group in enumerate(groups):
            member_tokens = set().union(*(_tokens(nodes[member].label) for member in group.members))
            score = len(query_tokens & member_tokens) / max(1, len(query_tokens))
            scored.append((str(index), score))
        chosen = prune_communities(tuple(scored), relevance_threshold=controls.community_relevance_threshold, maximum=controls.maximum_communities)
        selected_communities = tuple(groups[int(index)].members for index in chosen)

    ordered = tuple(sorted(hits.values(), key=lambda hit: (-hit.score, hit.identity))[:controls.maximum_nodes])
    path = None
    if anchor and len(ordered) > 1:
        target = next((hit.identity for hit in ordered if hit.identity != anchor), anchor)
        path = _path(active_graph, anchor, target, now=now, max_hops=controls.maximum_hops)
    external_required = plan.external_expansion_eligible and information_gain > controls.minimum_information_gain and authorization.external_access
    gaps = list(graph.gaps)
    if plan.query_class in (QueryClass.LEARNING_PATH, QueryClass.PROVENANCE_PATH) and not memory_available:
        gaps.append("Memory is unavailable; retrieval remains graph-local and does not reconstruct it")
    if plan.external_expansion_eligible and not authorization.external_access:
        gaps.append("external analogue requested but project authorization denies network access")
    followups = ()
    if information_gain > controls.minimum_information_gain and plan.query_class in (QueryClass.PROJECT_GLOBAL, QueryClass.LEARNING_PATH, QueryClass.EXTERNAL_ANALOGUE):
        templates = ("which high-value component best explains this theme?", "which contradictory or stale edge would change this answer?")
        followups = templates[:controls.maximum_follow_up_questions]
    return FederatedRetrievalResult(plan, ordered, path, selected_communities, followups, external_required, tuple(sorted(set(gaps))), truncated)


__all__ = ["ExplainedHop", "FederatedRetrievalResult", "KnowledgePath", "QueryClass", "RetrievalControls", "RetrievalHit", "RetrievalPlan", "RetrievalQuery", "classify_query", "plan_retrieval", "retrieve"]
