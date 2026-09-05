"""Execution 06, Section J: deterministic validation of the materialized
Desktop graph document.

Two of the required invariants — "no invalid self-edge" and "confidence in
range" — are already structurally impossible to violate:
`relationship_graph.GraphEdge.__post_init__` rejects both at construction
time (`source == target` raises; `confidence` outside `[0, 1]` raises), so
no `GraphEdge` violating either can ever exist in a `PerformanceGraph`. This
module re-checks neither — that would be dead code — and instead covers the
invariants nothing else already guarantees: the requested root actually
exists, every node belongs to the requested project, every edge's endpoints
are represented nodes, no canonical identity is claimed under two different
entity kinds, every skipped resolution has a matching gap, and any
truncation is explicit.

Reuses `link_integrity.py`'s `IntegritySeverity`/`IntegrityMode` — the
"report evidence, never erase" convention already established there — but
none of its actual checks, which validate an unrelated domain (requirement
traceability, behavior contracts, trajectories).
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import Identity
from .link_integrity import IntegrityMode, IntegritySeverity
from .relationship_graph import PerformanceGraph
from .visual_intelligence import PerformanceVisualMap


@dataclass(frozen=True, slots=True)
class GraphIntegrityFinding:
    kind: str
    severity: IntegritySeverity
    subject_id: str
    reference_id: str | None
    evidence: tuple[str, ...]
    uncertainty: str


@dataclass(frozen=True, slots=True)
class GraphIntegrityReport:
    project: str
    root_id: str
    mode: IntegrityMode
    findings: tuple[GraphIntegrityFinding, ...]

    @property
    def qualifies(self) -> bool:
        return not any(item.severity is IntegritySeverity.ERROR for item in self.findings)


def validate_graph_integrity(
    graph: PerformanceGraph,
    visual_map: PerformanceVisualMap,
    *,
    project: Identity,
    root: Identity,
    truncated: bool,
    mode: IntegrityMode = IntegrityMode.DIAGNOSTIC,
) -> GraphIntegrityReport:
    findings: list[GraphIntegrityFinding] = []

    def finding(kind: str, severity: IntegritySeverity, subject: str, reference: str | None, evidence: tuple[str, ...], uncertainty: str) -> None:
        findings.append(GraphIntegrityFinding(kind, severity, subject, reference, evidence, uncertainty))

    # Root exists (Section B's fix gives this real teeth: the root must be
    # present via `PerformanceGraph.roots`, or via an edge, independent of
    # whether any relationship happens to exist).
    if root not in graph.nodes:
        finding("missing_root", IntegritySeverity.ERROR, root.canonical, None, (), "the requested root identity is not represented in the materialized graph")

    # Project matches / no cross-project nodes: `Identity` carries no
    # project field of its own, so this is checked against whatever
    # `project_context` the materializer attached to each node — a node
    # with a DIFFERENT project_context than requested is a real integrity
    # violation; a node with no project_context at all is a diagnosable gap
    # (WARNING), not an ERROR, since some domains may not carry that
    # metadata yet.
    for node in visual_map.nodes:
        if node.project_context is None:
            finding("missing_project_context", IntegritySeverity.WARNING, node.identity.canonical, None, (), "node carries no project scope metadata")
        elif node.project_context != project.canonical:
            finding("cross_project_node", IntegritySeverity.ERROR, node.identity.canonical, node.project_context, (f"expected:{project.canonical}",), "node's project context does not match the requested project scope")

    # Edge endpoints exist as represented nodes.
    node_ids = graph.nodes
    for edge in graph.edges:
        if edge.source not in node_ids:
            finding("dangling_edge_source", IntegritySeverity.ERROR, edge.source.canonical, edge.target.canonical, edge.evidence, "edge source is not a represented node")
        if edge.target not in node_ids:
            finding("dangling_edge_target", IntegritySeverity.ERROR, edge.target.canonical, edge.source.canonical, edge.evidence, "edge target is not a represented node")

    # No conflicting identity kind: the same canonical UUID value must never
    # be claimed under two different entity kinds across the node set.
    seen_values: dict[str, str] = {}
    for node in node_ids:
        value = str(node.value)
        if value in seen_values and seen_values[value] != node.kind.value:
            finding("conflicting_identity_kind", IntegritySeverity.ERROR, node.canonical, seen_values[value], (), "the same identity value is claimed under two different entity kinds")
        seen_values.setdefault(value, node.kind.value)

    # Explicit unresolved resolution gaps: a self-consistency check on the
    # materializer's own gap discipline, not a re-derivation of it.
    if not graph.gaps and not visual_map.gaps and len(node_ids) <= 1:
        # A single-node (root-only) graph with literally nothing else known
        # should almost always carry at least one gap (e.g.
        # "unavailable:prompt_version" or "unavailable:sibling_outcomes")
        # unless the caller explicitly supplied a fully-populated PromptRun
        # with zero absent domains — flagged as INFO, not an error, since a
        # genuinely fully-known bare run is possible.
        finding("no_gaps_recorded_for_sparse_graph", IntegritySeverity.INFO, root.canonical, None, (), "a single-node graph ordinarily reflects at least one unresolved domain")

    # Truncation is explicit: the caller states whether the document was
    # capped; this just asserts that flag actually made it into the report
    # scope requested — real enforcement happens where bounds are applied
    # (graph_bridge.py), this is a documentation-level consistency check.
    if truncated:
        finding("truncated", IntegritySeverity.INFO, root.canonical, None, (), "document was bounded and does not represent the full reachable graph")

    return GraphIntegrityReport(project.canonical, root.canonical, mode, tuple(findings))
