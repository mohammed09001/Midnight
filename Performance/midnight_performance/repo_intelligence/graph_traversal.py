"""Budget-aware, cycle-safe traversal over the project knowledge overlay.

All traversals are deterministic (sorted frontier by canonical identity),
bounded by explicit node/hop budgets, and path explanations always cite
the underlying evidence ids of the links they use.  Cross-project
identities can never enter: every endpoint is an overlay node validated
at build time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import GraphLink, GraphRelation
from .project_graph import ProjectKnowledgeGraph

_MAX_HOPS_CAP = 8
_MAX_NODES_CAP = 500


@dataclass(frozen=True, slots=True)
class Neighbor:
    identity: str
    via: GraphLink
    direction: str

    def __post_init__(self) -> None:
        if self.direction not in ("outgoing", "incoming"):
            raise ValueError("neighbor direction must be outgoing or incoming")


@dataclass(frozen=True, slots=True)
class TraversalResult:
    """Ordered, bounded traversal outcome with an explicit truncation flag."""

    start: str
    visited: tuple[str, ...]
    links_used: tuple[GraphLink, ...]
    hops_used: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class PathHop:
    link: GraphLink
    from_identity: str
    to_identity: str

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return self.link.evidence_ids


@dataclass(frozen=True, slots=True)
class PathExplanation:
    """A path whose every hop cites the evidence that justifies it."""

    source: str
    target: str
    hops: tuple[PathHop, ...]
    found: bool


@dataclass(frozen=True, slots=True)
class Community:
    """One deterministic connected component of the selected relation set."""

    members: tuple[str, ...]


def neighbors(
    graph: ProjectKnowledgeGraph,
    identity: str,
    *,
    relations: frozenset[GraphRelation] | None = None,
    direction: str = "both",
) -> tuple[Neighbor, ...]:
    if direction not in ("outgoing", "incoming", "both"):
        raise ValueError("direction must be outgoing, incoming, or both")
    found: list[Neighbor] = []
    for link in graph.links_for(identity):
        if relations is not None and link.relation not in relations:
            continue
        if link.source == identity and direction in ("outgoing", "both"):
            found.append(Neighbor(identity=link.target, via=link, direction="outgoing"))
        if link.target == identity and direction in ("incoming", "both"):
            found.append(Neighbor(identity=link.source, via=link, direction="incoming"))
    return tuple(sorted(found, key=lambda n: (n.direction, n.identity, n.via.identity.canonical)))


def traverse(
    graph: ProjectKnowledgeGraph,
    start: str,
    *,
    max_hops: int = 2,
    max_nodes: int = 200,
    relations: frozenset[GraphRelation] | None = None,
    direction: str = "both",
) -> TraversalResult:
    """Bounded BFS from ``start``; cycle-safe by construction.

    Deterministic: the frontier expands in canonical-identity order, so
    the same graph always yields the same visited list.
    """
    if start not in {node.identity for node in graph.nodes}:
        raise ValueError(f"traversal start is not a graph node: {start}")
    if not 1 <= max_hops <= _MAX_HOPS_CAP:
        raise ValueError(f"max_hops must be between 1 and {_MAX_HOPS_CAP}")
    if not 1 <= max_nodes <= _MAX_NODES_CAP:
        raise ValueError(f"max_nodes must be between 1 and {_MAX_NODES_CAP}")

    visited: list[str] = [start]
    visited_set = {start}
    links_used: list[GraphLink] = []
    seen_links: set[str] = set()
    frontier = [start]
    truncated = False
    hops_used = 0

    for _hop in range(max_hops):
        hops_used = _hop + 1
        next_frontier: list[str] = []
        for current in sorted(frontier):
            for neighbor in neighbors(
                graph, current, relations=relations, direction=direction
            ):
                if neighbor.via.identity.canonical not in seen_links:
                    seen_links.add(neighbor.via.identity.canonical)
                    links_used.append(neighbor.via)
                if neighbor.identity not in visited_set:
                    if len(visited) >= max_nodes:
                        truncated = True
                        return TraversalResult(
                            start=start,
                            visited=tuple(sorted(visited)),
                            links_used=tuple(
                                sorted(links_used, key=lambda l: l.identity.canonical)
                            ),
                            hops_used=hops_used,
                            truncated=True,
                        )
                    visited.append(neighbor.identity)
                    visited_set.add(neighbor.identity)
                    next_frontier.append(neighbor.identity)
        if not next_frontier:
            break
        frontier = next_frontier
    return TraversalResult(
        start=start,
        visited=tuple(sorted(visited)),
        links_used=tuple(sorted(links_used, key=lambda l: l.identity.canonical)),
        hops_used=hops_used,
        truncated=truncated,
    )


def explain_path(
    graph: ProjectKnowledgeGraph,
    source: str,
    target: str,
    *,
    max_hops: int = 4,
    relations: frozenset[GraphRelation] | None = None,
) -> PathExplanation:
    """Shortest path (deterministic tie-break) with evidence-citing hops."""
    if source not in {node.identity for node in graph.nodes}:
        raise ValueError(f"path source is not a graph node: {source}")
    if target not in {node.identity for node in graph.nodes}:
        raise ValueError(f"path target is not a graph node: {target}")
    if not 1 <= max_hops <= _MAX_HOPS_CAP:
        raise ValueError(f"max_hops must be between 1 and {_MAX_HOPS_CAP}")
    if source == target:
        return PathExplanation(source=source, target=target, hops=(), found=True)

    parents: dict[str, tuple[str, GraphLink]] = {}
    visited = {source}
    frontier = [source]
    for _hop in range(max_hops):
        next_frontier: list[str] = []
        for current in sorted(frontier):
            for neighbor in neighbors(graph, current, relations=relations, direction="outgoing"):
                if neighbor.identity in visited:
                    continue
                visited.add(neighbor.identity)
                parents[neighbor.identity] = (current, neighbor.via)
                if neighbor.identity == target:
                    hops: list[PathHop] = []
                    cursor = target
                    while cursor != source:
                        previous, link = parents[cursor]
                        hops.append(
                            PathHop(
                                link=link,
                                from_identity=previous,
                                to_identity=cursor,
                            )
                        )
                        cursor = previous
                    hops.reverse()
                    return PathExplanation(
                        source=source, target=target, hops=tuple(hops), found=True
                    )
                next_frontier.append(neighbor.identity)
        if not next_frontier:
            break
        frontier = next_frontier
    return PathExplanation(source=source, target=target, hops=(), found=False)


def communities(
    graph: ProjectKnowledgeGraph,
    *,
    relations: frozenset[GraphRelation] | None = None,
    max_communities: int = 50,
) -> tuple[Community, ...]:
    """Deterministic connected components over the undirected relation subset.

    Components are seeded from the smallest canonical identity and grow in
    sorted order, so the same graph always yields the same communities.
    """
    if not 1 <= max_communities <= 500:
        raise ValueError("max_communities must be between 1 and 500")
    adjacency: dict[str, set[str]] = {node.identity: set() for node in graph.nodes}
    selected = relations if relations is not None else frozenset(GraphRelation)
    for link in graph.links:
        if link.relation not in selected:
            continue
        adjacency.setdefault(link.source, set()).add(link.target)
        adjacency.setdefault(link.target, set()).add(link.source)

    visited: set[str] = set()
    result: list[Community] = []
    for seed in sorted(adjacency):
        if seed in visited:
            continue
        members = [seed]
        visited.add(seed)
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for other in sorted(adjacency.get(current, ())):
                if other not in visited:
                    visited.add(other)
                    members.append(other)
                    frontier.append(other)
        result.append(Community(members=tuple(sorted(members))))
        if len(result) >= max_communities:
            break
    return tuple(result)


__all__ = [
    "Community",
    "Neighbor",
    "PathExplanation",
    "PathHop",
    "TraversalResult",
    "communities",
    "explain_path",
    "neighbors",
    "traverse",
]
