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
# Execution 10, Section B (Projection Identity): the graph algorithm's own
# public method/version identity, for callers (`graph_bridge.py`) that need
# to describe "which algorithm produced this projection" without reaching
# into this module's edge-construction internals. Same values `_reference()`
# already stamps on every edge below — exposed, not duplicated.
GRAPH_ALGORITHM_METHOD = _METHOD
GRAPH_ALGORITHM_VERSION = _VERSION


class EdgeKind(str, Enum):
    REFERENCE = "reference"
    EVIDENCE_LINEAGE = "evidence_lineage"
    SIMILARITY = "similarity"
    CONTRADICTION = "contradiction"
    SUPERSESSION = "supersession"
    REMEDIATION = "remediation"


class EdgeSemanticRole(str, Enum):
    """Execution 06, Section C: WHY an edge exists, kept separate from the
    epistemic `EdgeKind`. `EdgeKind.REFERENCE` alone cannot distinguish
    PromptRun->AgentRun from AgentRun->ToolObservation from PromptRun->
    ChangeSet — a Desktop frontend must not be forced to infer that from
    the target's entity kind, so `build_graph`/`compose_graph` assign one
    of these explicitly, at the point where the relationship's true
    meaning is actually known."""
    PROMPT_VERSION = "prompt_version"
    EXECUTED_BY = "executed_by"
    AGENT_SESSION = "agent_session"
    AGENT_TURN = "agent_turn"
    USED_TOOL = "used_tool"
    EXECUTED_COMMAND = "executed_command"
    PRODUCED_CHANGE = "produced_change"
    CHANGED_FILE = "changed_file"
    CONTAINS_SYMBOL = "contains_symbol"
    CONTAINS_REGION = "contains_region"
    VERIFIED_BY = "verified_by"
    FEEDBACK_FOR = "feedback_for"
    OUTCOME_REFERENCE = "outcome_reference"
    EPISODE_MEMBERSHIP = "episode_membership"
    ANALYSIS_LINEAGE = "analysis_lineage"
    CITES_MEMORY = "cites_memory"
    DATASET_MEMBERSHIP = "dataset_membership"
    EXPERIMENT_REFERENCE = "experiment_reference"
    REPOSITORY_ENTITY = "repository_entity"


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: Identity; target: Identity; kind: EdgeKind; claim_kind: ClaimKind
    confidence: float | None; evidence: tuple[str, ...]; method: str; method_version: str; uncertainty: str
    semantic_role: EdgeSemanticRole | None = None

    def __post_init__(self):
        if self.source == self.target: raise ValueError("an edge must connect two distinct nodes")
        if self.confidence is not None and not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")
        if not self.method.strip() or not self.method_version.strip() or not self.uncertainty.strip(): raise ValueError("edges require method, version, and uncertainty disclosure")


@dataclass(frozen=True, slots=True)
class PerformanceGraph:
    """A rebuildable projection: rebuilding from the same inputs reproduces the same edges. Never the canonical evidence store."""
    edges: tuple[GraphEdge, ...]
    gaps: tuple[str, ...] = ()
    # Execution 06, Section B: node membership was entirely edge-derived,
    # so a Prompt Run with zero edges (no version, no agent runs, nothing)
    # never appeared in `.nodes` at all. `roots` explicitly represents
    # entities known to exist independent of any edge — never a fake
    # self-edge, never a placeholder relationship, just an honest
    # declaration of "this node exists." `build_graph` always sets the
    # requested Prompt Run itself as a root, since Section A guarantees
    # that identity is real.
    roots: frozenset[Identity] = frozenset()

    @property
    def nodes(self) -> frozenset[Identity]:
        return frozenset(edge.source for edge in self.edges) | frozenset(edge.target for edge in self.edges) | self.roots

    def neighbors(self, identity: Identity, *, kinds: frozenset[EdgeKind] | None = None) -> tuple[Identity, ...]:
        return tuple(edge.target for edge in self.edges if edge.source == identity and (kinds is None or edge.kind in kinds))

    def edges_for(self, identity: Identity) -> tuple[GraphEdge, ...]:
        return tuple(edge for edge in self.edges if identity in (edge.source, edge.target))


def _node(kind: EntityKind, stable_key: str) -> Identity:
    return deterministic_identity(kind, stable_key)


def _reference(source: Identity, target: Identity, evidence: str, semantic_role: EdgeSemanticRole | None = None) -> GraphEdge:
    return GraphEdge(source, target, EdgeKind.REFERENCE, ClaimKind.DERIVED, None, (evidence,), _METHOD, _VERSION, "direct reification of an existing typed reference; the graph is a rebuildable projection, not canonical evidence", semantic_role)


@dataclass(frozen=True, slots=True)
class ResolvedRepositoryEntity:
    """Execution 08, Section B: a resolved repository entity plus WHERE it
    attaches. `parent=None` means "attach directly to the ChangeSet" — the
    exact flat behavior `resolved_entities` has always had. A non-`None`
    parent lets a caller express real containment (e.g. a Symbol under its
    owning FileChange) instead of every entity landing directly on the
    ChangeSet merely because the composition API accepts it."""
    entity: Identity
    parent: Identity | None = None


_REPOSITORY_ENTITY_ROLE = {
    EntityKind.FILE_CHANGE: EdgeSemanticRole.CHANGED_FILE,
    EntityKind.SYMBOL: EdgeSemanticRole.CONTAINS_SYMBOL,
    EntityKind.CODE_REGION: EdgeSemanticRole.CONTAINS_REGION,
}


def _wire_repository_entities(
    edges: list[GraphEdge], gaps: list[str], change_node: Identity, change_set_id: str,
    entities: tuple[Identity | ResolvedRepositoryEntity, ...] | None,
) -> None:
    """Shared by `build_graph` and `compose_graph`. Accepts a mix of bare
    `Identity` (today's flat callers, unchanged behavior — attaches
    directly to the ChangeSet) and `ResolvedRepositoryEntity` (hierarchy-
    aware callers, e.g. `repository_entity_resolution.py`)."""
    if entities is None:
        gaps.append(f"{change_set_id}:unavailable:repository_entity_resolution")
        return
    declared = frozenset(item.entity if isinstance(item, ResolvedRepositoryEntity) else item for item in entities)
    for item in entities:
        if isinstance(item, ResolvedRepositoryEntity):
            entity, parent = item.entity, item.parent
        else:
            entity, parent = item, None
        if parent is not None and parent not in declared:
            raise ValueError("resolved entity's parent must also be present in the same change set's resolved entities")
        source = parent if parent is not None else change_node
        role = _REPOSITORY_ENTITY_ROLE.get(entity.kind, EdgeSemanticRole.REPOSITORY_ENTITY)
        edges.append(_reference(source, entity, entity.canonical, role))


def build_graph(
    prompt_run: PromptRun,
    *,
    tool_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    command_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_session_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_turn_ids: Mapping[str, tuple[str, ...]] | None = None,
    memory_references: tuple[ExternalReference, ...] = (),
    resolved_entities: Mapping[str, tuple[Identity | ResolvedRepositoryEntity, ...]] | None = None,
) -> PerformanceGraph:
    """Reify one PromptRun's already-typed references as graph edges; deterministic node identities make rebuilds reproduce the same graph.

    `PromptRun` carries no tool/command observation ids of its own, so that segment of the
    Prompt -> Agent Run -> tools/commands chain is caller-supplied evidence; its absence is
    recorded as an explicit gap rather than fabricated.

    Execution 08: `resolved_entities` (keyed by this run's own `change_set_id`s)
    wires the ChangeSet -> FileChange -> CodeRegion/Symbol hierarchy via
    `ResolvedRepositoryEntity`'s `parent` field — never flattening every
    entity directly onto the ChangeSet merely because the parameter accepts
    a bare `Identity` too (which it still does, unchanged, for existing
    zero-depth callers).
    """
    tool_observation_ids = tool_observation_ids or {}
    command_observation_ids = command_observation_ids or {}
    agent_session_ids = agent_session_ids or {}
    agent_turn_ids = agent_turn_ids or {}
    resolved_entities = resolved_entities or {}
    if not set(resolved_entities) <= set(prompt_run.change_set_ids):
        raise ValueError("resolved entities must belong to represented change sets")
    allowed_entities = {EntityKind.FILE_CHANGE, EntityKind.CODE_REGION, EntityKind.SYMBOL, EntityKind.REPOSITORY, EntityKind.REPOSITORY_SNAPSHOT}
    if any(
        (item.entity if isinstance(item, ResolvedRepositoryEntity) else item).kind not in allowed_entities
        for entities in resolved_entities.values() for item in entities
    ):
        raise ValueError("resolved repository entities must have a repository entity kind")
    prompt_run_node = _node(EntityKind.PROMPT_RUN, prompt_run.prompt_run_id)
    edges: list[GraphEdge] = []
    gaps = list(prompt_run.gaps)
    if prompt_run.prompt_version_id:
        edges.append(_reference(prompt_run_node, _node(EntityKind.PROMPT_VERSION, prompt_run.prompt_version_id), prompt_run.prompt_version_id, EdgeSemanticRole.PROMPT_VERSION))
    for agent_run_id in prompt_run.agent_run_ids:
        agent_run_node = _node(EntityKind.AGENT_RUN, agent_run_id)
        edges.append(_reference(prompt_run_node, agent_run_node, agent_run_id, EdgeSemanticRole.EXECUTED_BY))
        for session_id in agent_session_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.AGENT_SESSION, session_id), session_id, EdgeSemanticRole.AGENT_SESSION))
        for turn_id in agent_turn_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.AGENT_TURN, turn_id), turn_id, EdgeSemanticRole.AGENT_TURN))
        for tool_id in tool_observation_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.TOOL_OBSERVATION, tool_id), tool_id, EdgeSemanticRole.USED_TOOL))
        for command_id in command_observation_ids.get(agent_run_id, ()):
            edges.append(_reference(agent_run_node, _node(EntityKind.COMMAND_OBSERVATION, command_id), command_id, EdgeSemanticRole.EXECUTED_COMMAND))
    if prompt_run.agent_run_ids and not tool_observation_ids and not command_observation_ids:
        gaps.append("unavailable:tool_and_command_observations")
    for change_set_id in prompt_run.change_set_ids:
        change_set_node = _node(EntityKind.CHANGE_SET, change_set_id)
        edges.append(_reference(prompt_run_node, change_set_node, change_set_id, EdgeSemanticRole.PRODUCED_CHANGE))
        if change_set_id in resolved_entities:
            _wire_repository_entities(edges, gaps, change_set_node, change_set_id, resolved_entities[change_set_id])
    for verification_id in prompt_run.verification_ids:
        edges.append(_reference(prompt_run_node, _node(EntityKind.VERIFICATION_RUN, verification_id), verification_id, EdgeSemanticRole.VERIFIED_BY))
    for feedback_id in prompt_run.feedback_ids:
        edges.append(_reference(prompt_run_node, _node(EntityKind.FEEDBACK_RECORD, feedback_id), feedback_id, EdgeSemanticRole.FEEDBACK_FOR))
    for outcome_id in prompt_run.outcome_references:
        edges.append(_reference(prompt_run_node, _node(EntityKind.OUTCOME_OBSERVATION, outcome_id), outcome_id, EdgeSemanticRole.OUTCOME_REFERENCE))
    if prompt_run.episode_id:
        edges.append(_reference(prompt_run_node, _node(EntityKind.EPISODE, prompt_run.episode_id), prompt_run.episode_id, EdgeSemanticRole.EPISODE_MEMBERSHIP))
    for analysis_id in prompt_run.analysis_ids:
        edges.append(GraphEdge(
            prompt_run_node, _node(EntityKind.ANALYSIS_VERSION, analysis_id), EdgeKind.EVIDENCE_LINEAGE, ClaimKind.DERIVED, None, (analysis_id,),
            _METHOD, _VERSION, "raw evidence to derived-analysis provenance; the analysis remains a rebuildable projection", EdgeSemanticRole.ANALYSIS_LINEAGE,
        ))
    for reference in memory_references:
        key = f"{reference.provider}:{reference.kind}:{reference.value}"
        edges.append(_reference(prompt_run_node, _node(EntityKind.MEMORY_RECORD, key), key, EdgeSemanticRole.CITES_MEMORY))
    if not prompt_run.outcome_references:
        gaps.append("unavailable:sibling_outcomes")
    return PerformanceGraph(tuple(edges), tuple(gaps), frozenset({prompt_run_node}))


def merge(graphs: tuple[PerformanceGraph, ...]) -> PerformanceGraph:
    """Combine independently built graphs; exact-duplicate edges collapse, evidence-distinct edges do not."""
    if not graphs:
        raise ValueError("merge requires at least one graph")
    edges = tuple(dict.fromkeys(edge for graph in graphs for edge in graph.edges))
    gaps = tuple(sorted({gap for graph in graphs for gap in graph.gaps}))
    roots = frozenset().union(*(graph.roots for graph in graphs))
    return PerformanceGraph(edges, gaps, roots)


def compose_graph(
    prompt_runs: tuple[PromptRun, ...],
    *,
    tool_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    command_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_session_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_turn_ids: Mapping[str, tuple[str, ...]] | None = None,
    memory_references: Mapping[str, tuple[ExternalReference, ...]] | None = None,
    resolved_entities: Mapping[str, tuple[Identity | ResolvedRepositoryEntity, ...]] | None = None,
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
    if any(
        (item.entity if isinstance(item, ResolvedRepositoryEntity) else item).kind not in allowed_entities
        for entities in resolved_entities.values() for item in entities
    ):
        raise ValueError("resolved repository entities must have a repository entity kind")
    edges: list[GraphEdge] = []
    gaps: list[str] = []
    roots: set[Identity] = set()
    for run in prompt_runs:
        graph = build_graph(run, tool_observation_ids=tool_observation_ids, command_observation_ids=command_observation_ids, agent_session_ids=agent_session_ids, agent_turn_ids=agent_turn_ids, memory_references=memory_references.get(run.prompt_run_id, ()))
        edges.extend(graph.edges)
        gaps.extend(graph.gaps)
        roots |= graph.roots
        if run.prompt_run_id not in memory_references:
            gaps.append(f"{run.prompt_run_id}:unavailable:memory_references")
        run_node = _node(EntityKind.PROMPT_RUN, run.prompt_run_id)
        for dataset_id in dataset_ids.get(run.prompt_run_id, ()):
            edges.append(_reference(run_node, _node(EntityKind.DATASET_ITEM, dataset_id), dataset_id, EdgeSemanticRole.DATASET_MEMBERSHIP))
        for experiment_id in experiment_ids.get(run.prompt_run_id, ()):
            edges.append(_reference(run_node, _node(EntityKind.EXPERIMENT_RUN, experiment_id), experiment_id, EdgeSemanticRole.EXPERIMENT_REFERENCE))
        for change_set_id in run.change_set_ids:
            change_node = _node(EntityKind.CHANGE_SET, change_set_id)
            _wire_repository_entities(edges, gaps, change_node, change_set_id, resolved_entities.get(change_set_id))
    return PerformanceGraph(tuple(dict.fromkeys(edges)), tuple(sorted(set(gaps))), frozenset(roots))


def add_similarity_edge(graph: PerformanceGraph, query_prompt_run_id: str, candidate_prompt_run_id: str, *, score: float, evidence: tuple[str, ...], claim_kind: ClaimKind, method: str, method_version: str, uncertainty: str) -> PerformanceGraph:
    """Attach one retrieval match as a SIMILARITY edge; the caller supplies the match fields so this module never needs to import the retrieval layer."""
    edge = GraphEdge(_node(EntityKind.PROMPT_RUN, query_prompt_run_id), _node(EntityKind.PROMPT_RUN, candidate_prompt_run_id), EdgeKind.SIMILARITY, claim_kind, score, evidence, method, method_version, uncertainty)
    return PerformanceGraph(graph.edges + (edge,), graph.gaps, graph.roots)


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
    return PerformanceGraph(graph.edges + tuple(new_edges), graph.gaps, graph.roots)


def add_contradiction_edges(graph: PerformanceGraph, prompt_run_id: str, alignment: AlignmentResult) -> PerformanceGraph:
    prompt_run_node = _node(EntityKind.PROMPT_RUN, prompt_run_id)
    new_edges = []
    for judgment in alignment.judgments:
        if judgment.status is not AlignmentStatus.CONTRADICTED:
            continue
        for path in judgment.evidence:
            new_edges.append(GraphEdge(prompt_run_node, _node(EntityKind.FILE_CHANGE, path), EdgeKind.CONTRADICTION, judgment.claim_kind, judgment.confidence, (judgment.text,), judgment.method, judgment.method_version, judgment.uncertainty))
    return PerformanceGraph(graph.edges + tuple(new_edges), graph.gaps, graph.roots)


def add_remediation_edge(graph: PerformanceGraph, finding_external_id: str, verification_id: str, *, confidence: float, evidence: tuple[str, ...] = ()) -> PerformanceGraph:
    """Caller-attested: this Watch/Security finding was remediated and checked by this verification run. Performance does not independently verify sibling-domain remediation."""
    edge = GraphEdge(
        _node(EntityKind.OUTCOME_OBSERVATION, finding_external_id), _node(EntityKind.VERIFICATION_RUN, verification_id),
        EdgeKind.REMEDIATION, ClaimKind.INFERRED, confidence, evidence, _METHOD, _VERSION,
        "caller-attested remediation linkage; Performance does not independently verify sibling-domain remediation",
    )
    return PerformanceGraph(graph.edges + (edge,), graph.gaps, graph.roots)


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
