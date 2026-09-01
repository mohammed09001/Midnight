"""Rebuildable relationship graph over Performance-owned entities and versioned external references; not canonical evidence, not GraphRAG."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from .alignment import AlignmentResult, AlignmentStatus
from .contracts import ClaimKind, EntityKind, ExternalReference, Identity, deterministic_identity
from .prompt_lineage import PromptLineageLink
from .prompt_run import PromptRun

_METHOD = "relationship-graph"
_VERSION = "1"


class EdgeKind(str, Enum):
    REFERENCE = "reference"
    EVIDENCE_LINEAGE = "evidence_lineage"
    SIMILARITY = "similarity"
    CONTRADICTION = "contradiction"
    SUPERSESSION = "supersession"
    REMEDIATION = "remediation"


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: Identity; target: Identity; kind: EdgeKind; claim_kind: ClaimKind
    confidence: float | None; evidence: tuple[str, ...]; method: str; method_version: str; uncertainty: str

    def __post_init__(self):
        if self.source == self.target: raise ValueError("an edge must connect two distinct nodes")
        if self.confidence is not None and not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")
        if not self.method.strip() or not self.method_version.strip() or not self.uncertainty.strip(): raise ValueError("edges require method, version, and uncertainty disclosure")


@dataclass(frozen=True, slots=True)
class PerformanceGraph:
    """A rebuildable projection: rebuilding from the same inputs reproduces the same edges. Never the canonical evidence store."""
    edges: tuple[GraphEdge, ...]
    gaps: tuple[str, ...] = ()

    @property
    def nodes(self) -> frozenset[Identity]:
        return frozenset(edge.source for edge in self.edges) | frozenset(edge.target for edge in self.edges)

    def neighbors(self, identity: Identity, *, kinds: frozenset[EdgeKind] | None = None) -> tuple[Identity, ...]:
        return tuple(edge.target for edge in self.edges if edge.source == identity and (kinds is None or edge.kind in kinds))

    def edges_for(self, identity: Identity) -> tuple[GraphEdge, ...]:
        return tuple(edge for edge in self.edges if identity in (edge.source, edge.target))


def _node(kind: EntityKind, stable_key: str) -> Identity:
    return deterministic_identity(kind, stable_key)


def _reference(source: Identity, target: Identity, evidence: str) -> GraphEdge:
    return GraphEdge(source, target, EdgeKind.REFERENCE, ClaimKind.DERIVED, None, (evidence,), _METHOD, _VERSION, "direct reification of an existing typed reference; the graph is a rebuildable projection, not canonical evidence")


def build_graph(
    prompt_run: PromptRun,
    *,
    tool_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    command_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_session_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_turn_ids: Mapping[str, tuple[str, ...]] | None = None,
    memory_references: tuple[ExternalReference, ...] = (),
) -> PerformanceGraph:
    """Reify one PromptRun's already-typed references as graph edges; deterministic node identities make rebuilds reproduce the same graph.

    `PromptRun` carries no tool/command observation ids of its own, so that segment of the
    Prompt -> Agent Run -> tools/commands chain is caller-supplied evidence; its absence is
    recorded as an explicit gap rather than fabricated.
    """
    tool_observation_ids = tool_observation_ids or {}
    command_observation_ids = command_observation_ids or {}
    agent_session_ids = agent_session_ids or {}
    agent_turn_ids = agent_turn_ids or {}
    prompt_run_node = _node(EntityKind.PROMPT_RUN, prompt_run.prompt_run_id)
    edges: list[GraphEdge] = []
    gaps = list(prompt_run.gaps)
    if prompt_run.prompt_version_id:
        edges.append(_reference(prompt_run_node, _node(EntityKind.PROMPT_VERSION, prompt_run.prompt_version_id), prompt_run.prompt_version_id))
    for agent_run_id in prompt_run.agent_run_ids:
        agent_run_node = _node(EntityKind.AGENT_RUN, agent_run_id)
        edges.append(_reference(prompt_run_node, agent_run_node, agent_run_id))
        for session_id in agent_session_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.AGENT_SESSION, session_id), session_id))
        for turn_id in agent_turn_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.AGENT_TURN, turn_id), turn_id))
        for tool_id in tool_observation_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.TOOL_OBSERVATION, tool_id), tool_id))
        for command_id in command_observation_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.COMMAND_OBSERVATION, command_id), command_id))
    if prompt_run.agent_run_ids and not tool_observation_ids and not command_observation_ids:
        gaps.append("unavailable:tool_and_command_observations")
    for change_set_id in prompt_run.change_set_ids:
        edges.append(_reference(prompt_run_node, _node(EntityKind.CHANGE_SET, change_set_id), change_set_id))
    for verification_id in prompt_run.verification_ids:
        edges.append(_reference(prompt_run_node, _node(EntityKind.VERIFICATION_RUN, verification_id), verification_id))
    for feedback_id in prompt_run.feedback_ids:
        edges.append(_reference(prompt_run_node, _node(EntityKind.FEEDBACK_RECORD, feedback_id), feedback_id))
    for outcome_id in prompt_run.outcome_references:
        edges.append(_reference(prompt_run_node, _node(EntityKind.OUTCOME_OBSERVATION, outcome_id), outcome_id))
    if prompt_run.episode_id:
        edges.append(_reference(prompt_run_node, _node(EntityKind.EPISODE, prompt_run.episode_id), prompt_run.episode_id))
    for analysis_id in prompt_run.analysis_ids:
        edges.append(GraphEdge(
            prompt_run_node, _node(EntityKind.ANALYSIS_VERSION, analysis_id), EdgeKind.EVIDENCE_LINEAGE, ClaimKind.DERIVED, None, (analysis_id,),
            _METHOD, _VERSION, "raw evidence to derived-analysis provenance; the analysis remains a rebuildable projection",
        ))
    for reference in memory_references:
        key = f"{reference.provider}:{reference.kind}:{reference.value}"
        edges.append(_reference(prompt_run_node, _node(EntityKind.MEMORY_RECORD, key), key))
    if not prompt_run.outcome_references:
        gaps.append("unavailable:sibling_outcomes")
    return PerformanceGraph(tuple(edges), tuple(gaps))


def merge(graphs: tuple[PerformanceGraph, ...]) -> PerformanceGraph:
    """Combine independently built graphs; exact-duplicate edges collapse, evidence-distinct edges do not."""
    if not graphs:
        raise ValueError("merge requires at least one graph")
    edges = tuple(dict.fromkeys(edge for graph in graphs for edge in graph.edges))
    gaps = tuple(sorted({gap for graph in graphs for gap in graph.gaps}))
    return PerformanceGraph(edges, gaps)


def compose_graph(
    prompt_runs: tuple[PromptRun, ...],
    *,
    tool_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    command_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_session_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_turn_ids: Mapping[str, tuple[str, ...]] | None = None,
    memory_references: Mapping[str, tuple[ExternalReference, ...]] | None = None,
    resolved_entities: Mapping[str, tuple[Identity, ...]] | None = None,
    dataset_ids: Mapping[str, tuple[str, ...]] | None = None,
    experiment_ids: Mapping[str, tuple[str, ...]] | None = None,
) -> PerformanceGraph:
    """Compose typed Performance references into the existing rebuildable graph.

    This is deliberately a graph-owner operation, rather than a Visual
    Intelligence shortcut.  Keys are PromptRun ids; repository entities are
    accepted only as typed identities and must be attached to a represented
    Change Set.
    """
    tool_observation_ids = tool_observation_ids or {}
    command_observation_ids = command_observation_ids or {}
    agent_session_ids = agent_session_ids or {}
    agent_turn_ids = agent_turn_ids or {}
    memory_references = memory_references or {}
    resolved_entities = resolved_entities or {}
    dataset_ids = dataset_ids or {}
    experiment_ids = experiment_ids or {}
    run_ids = [run.prompt_run_id for run in prompt_runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("duplicate prompt run ids in graph composition")
    known = set(run_ids)
    for name, source in (("memory", memory_references), ("datasets", dataset_ids), ("experiments", experiment_ids)):
        if not set(source) <= known:
            raise ValueError(f"{name} references must belong to represented prompt runs")
    change_sets = {change_id for run in prompt_runs for change_id in run.change_set_ids}
    if not set(resolved_entities) <= change_sets:
        raise ValueError("resolved entities must belong to represented change sets")
    allowed_entities = {EntityKind.FILE_CHANGE, EntityKind.CODE_REGION, EntityKind.SYMBOL, EntityKind.REPOSITORY, EntityKind.REPOSITORY_SNAPSHOT}
    if any(entity.kind not in allowed_entities for entities in resolved_entities.values() for entity in entities):
        raise ValueError("resolved repository entities must have a repository entity kind")
    edges: list[GraphEdge] = []
    gaps: list[str] = []
    for run in prompt_runs:
        graph = build_graph(run, tool_observation_ids=tool_observation_ids, command_observation_ids=command_observation_ids, agent_session_ids=agent_session_ids, agent_turn_ids=agent_turn_ids, memory_references=memory_references.get(run.prompt_run_id, ()))
        edges.extend(graph.edges)
        gaps.extend(graph.gaps)
        if run.prompt_run_id not in memory_references:
            gaps.append(f"{run.prompt_run_id}:unavailable:memory_references")
        run_node = _node(EntityKind.PROMPT_RUN, run.prompt_run_id)
        for dataset_id in dataset_ids.get(run.prompt_run_id, ()):
            edges.append(_reference(run_node, _node(EntityKind.DATASET_ITEM, dataset_id), dataset_id))
        for experiment_id in experiment_ids.get(run.prompt_run_id, ()):
            edges.append(_reference(run_node, _node(EntityKind.EXPERIMENT_RUN, experiment_id), experiment_id))
        for change_set_id in run.change_set_ids:
            entities = resolved_entities.get(change_set_id)
            if entities is None:
                gaps.append(f"{change_set_id}:unavailable:repository_entity_resolution")
                continue
            change_node = _node(EntityKind.CHANGE_SET, change_set_id)
            for entity in entities:
                edges.append(_reference(change_node, entity, entity.canonical))
    return PerformanceGraph(tuple(dict.fromkeys(edges)), tuple(sorted(set(gaps))))


def add_similarity_edge(graph: PerformanceGraph, query_prompt_run_id: str, candidate_prompt_run_id: str, *, score: float, evidence: tuple[str, ...], claim_kind: ClaimKind, method: str, method_version: str, uncertainty: str) -> PerformanceGraph:
    """Attach one retrieval match as a SIMILARITY edge; the caller supplies the match fields so this module never needs to import the retrieval layer."""
    edge = GraphEdge(_node(EntityKind.PROMPT_RUN, query_prompt_run_id), _node(EntityKind.PROMPT_RUN, candidate_prompt_run_id), EdgeKind.SIMILARITY, claim_kind, score, evidence, method, method_version, uncertainty)
    return PerformanceGraph(graph.edges + (edge,), graph.gaps)


def add_supersession_edges(graph: PerformanceGraph, links: tuple[PromptLineageLink, ...]) -> PerformanceGraph:
    new_edges = []
    for link in links:
        summary = tuple(
            f"{count} {label}" for count, label in (
                (len(link.added_constraints) + len(link.removed_constraints), "constraint changes"),
                (len(link.added_acceptance) + len(link.removed_acceptance), "acceptance changes"),
                (len(link.added_verification) + len(link.removed_verification), "verification changes"),
            ) if count
        )
        new_edges.append(GraphEdge(
            _node(EntityKind.PROMPT_VERSION, link.parent_version_id), _node(EntityKind.PROMPT_VERSION, link.child_version_id),
            EdgeKind.SUPERSESSION, ClaimKind.DERIVED, None, summary or ("no requirement text changed",),
            link.method, link.method_version, link.uncertainty,
        ))
    return PerformanceGraph(graph.edges + tuple(new_edges), graph.gaps)


def add_contradiction_edges(graph: PerformanceGraph, prompt_run_id: str, alignment: AlignmentResult) -> PerformanceGraph:
    prompt_run_node = _node(EntityKind.PROMPT_RUN, prompt_run_id)
    new_edges = []
    for judgment in alignment.judgments:
        if judgment.status is not AlignmentStatus.CONTRADICTED:
            continue
        for path in judgment.evidence:
            new_edges.append(GraphEdge(prompt_run_node, _node(EntityKind.FILE_CHANGE, path), EdgeKind.CONTRADICTION, judgment.claim_kind, judgment.confidence, (judgment.text,), judgment.method, judgment.method_version, judgment.uncertainty))
    return PerformanceGraph(graph.edges + tuple(new_edges), graph.gaps)


def add_remediation_edge(graph: PerformanceGraph, finding_external_id: str, verification_id: str, *, confidence: float, evidence: tuple[str, ...] = ()) -> PerformanceGraph:
    """Caller-attested: this Watch/Security finding was remediated and checked by this verification run. Performance does not independently verify sibling-domain remediation."""
    edge = GraphEdge(
        _node(EntityKind.OUTCOME_OBSERVATION, finding_external_id), _node(EntityKind.VERIFICATION_RUN, verification_id),
        EdgeKind.REMEDIATION, ClaimKind.INFERRED, confidence, evidence, _METHOD, _VERSION,
        "caller-attested remediation linkage; Performance does not independently verify sibling-domain remediation",
    )
    return PerformanceGraph(graph.edges + (edge,), graph.gaps)


def traverse(graph: PerformanceGraph, start: Identity, *, direction: str = "forward", max_depth: int | None = None, kinds: frozenset[EdgeKind] | None = None) -> tuple[Identity, ...]:
    """BFS reachability from `start`, excluding `start` itself. Forward direction is downstream impact exploration; backward is upstream lineage."""
    if direction not in ("forward", "backward", "both"):
        raise ValueError("direction must be forward, backward, or both")
    if max_depth is not None and max_depth < 1:
        raise ValueError("max_depth must be positive when supplied")
    relevant = tuple(edge for edge in graph.edges if kinds is None or edge.kind in kinds)

    def step(identity: Identity) -> tuple[Identity, ...]:
        forward = tuple(edge.target for edge in relevant if edge.source == identity)
        backward = tuple(edge.source for edge in relevant if edge.target == identity)
        if direction == "forward":
            return forward
        if direction == "backward":
            return backward
        return forward + backward

    visited: list[Identity] = []
    seen = {start}
    frontier = [start]
    depth = 0
    while frontier and (max_depth is None or depth < max_depth):
        next_frontier: list[Identity] = []
        for identity in frontier:
            for neighbor in step(identity):
                if neighbor not in seen:
                    seen.add(neighbor)
                    visited.append(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
        depth += 1
    return tuple(visited)


def memory_neighbors(graph: PerformanceGraph, identity: Identity) -> tuple[Identity, ...]:
    """Reachable Memory-kind nodes; Memory itself is an external sibling, referenced only through versioned external references."""
    return tuple(node for node in traverse(graph, identity, direction="both") if node.kind is EntityKind.MEMORY_RECORD)


def graph_reference_overlap(a: PromptRun, b: PromptRun) -> tuple[float | None, tuple[str, ...]]:
    """Jaccard overlap of two prompt runs' directly-referenced graph nodes; a lightweight one-hop relationship-graph traversal signal for retrieval."""
    nodes_a = frozenset(edge.target for edge in build_graph(a).edges)
    nodes_b = frozenset(edge.target for edge in build_graph(b).edges)
    if not nodes_a or not nodes_b:
        return None, ()
    overlap = nodes_a & nodes_b
    union = nodes_a | nodes_b
    return round(len(overlap) / len(union), 3), tuple(sorted(node.canonical for node in overlap))
