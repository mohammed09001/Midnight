"""Versioned, UI-consumable Visual Intelligence projections.

These models deliberately compose existing Performance projections.  They do
not persist evidence, infer lineage, rank experiences, or render pixels.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

from .contracts import ClaimKind, EntityKind, ExternalReference, Identity
from .neighborhoods import BUCKETS, Neighborhood
from .prompt_lineage import PromptLineageLink, PromptRevision
from .prompt_analysis import RequirementType
from .relationship_graph import GraphEdge, PerformanceGraph, compose_graph
from .prompt_run import PromptRun
from .repository_capture import ChangeEvidence
from .verification import VerificationEvidence
from .feedback import FeedbackRecord
from .similarity import Experience

VISUAL_PROJECTION_VERSION = "1"
PROMPT_LINEAGE_VISUAL_PROJECTION_VERSION = "2"


def _layer(kind: EntityKind) -> str:
    if kind in (EntityKind.PROMPT_RUN, EntityKind.PROMPT, EntityKind.PROMPT_VERSION): return "prompt"
    if kind in (EntityKind.AGENT_RUN, EntityKind.AGENT_SESSION, EntityKind.AGENT_TURN, EntityKind.TOOL_OBSERVATION, EntityKind.COMMAND_OBSERVATION, EntityKind.EPISODE): return "execution"
    if kind in (EntityKind.REPOSITORY, EntityKind.REPOSITORY_SNAPSHOT, EntityKind.CHANGE_SET, EntityKind.FILE_CHANGE, EntityKind.CODE_REGION, EntityKind.SYMBOL): return "repository/change"
    if kind is EntityKind.VERIFICATION_RUN: return "verification"
    if kind is EntityKind.FEEDBACK_RECORD: return "feedback"
    if kind is EntityKind.OUTCOME_OBSERVATION: return "outcome"
    if kind in (EntityKind.DATASET_ITEM, EntityKind.EXPERIMENT_RUN): return "experiment/dataset"
    if kind is EntityKind.MEMORY_RECORD: return "memory"
    return "analysis"


@dataclass(frozen=True, slots=True)
class VisualNode:
    identity: Identity; entity_kind: EntityKind; layer: str; label: str
    claim_kind: ClaimKind; provenance: tuple[str, ...] = (); observed_at: datetime | None = None
    project_context: str | None = None; externally_referenced: bool = False; gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.identity.kind is not self.entity_kind: raise ValueError("visual node identity and kind must agree")
        if not self.layer or not self.label: raise ValueError("visual nodes require layer and safe fallback label")
        if self.observed_at is not None and self.observed_at.tzinfo is None: raise ValueError("node timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class VisualNodeMetadata:
    """Optional source-backed display metadata; it never changes graph membership."""
    label: str | None = None; claim_kind: ClaimKind = ClaimKind.DERIVED
    provenance: tuple[str, ...] = (); observed_at: datetime | None = None
    project_context: str | None = None; externally_referenced: bool = False; gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.claim_kind is ClaimKind.OBSERVED:
            raise ValueError("visual nodes are projections and cannot claim raw observed status")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("node timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class VisualEdge:
    source: Identity; target: Identity; relationship_kind: str; claim_kind: ClaimKind
    evidence: tuple[str, ...]; confidence: float | None; method: str; method_version: str; uncertainty: str

    def __post_init__(self) -> None:
        if self.source == self.target: raise ValueError("visual edges cannot be self edges")
        if not all((self.relationship_kind, self.method, self.method_version, self.uncertainty)): raise ValueError("visual edges require semantics and disclosure")


@dataclass(frozen=True, slots=True)
class PerformanceVisualMap:
    """A graph-derived map; canonical evidence remains outside this read model."""
    schema_version: str; project_context: str | None; nodes: tuple[VisualNode, ...]; edges: tuple[VisualEdge, ...]; gaps: tuple[str, ...]

    def as_records(self) -> tuple[Mapping[str, object], ...]:
        return ({"schema_version": self.schema_version, "project_context": self.project_context, "nodes": tuple(_node_record(n) for n in self.nodes), "edges": tuple(_edge_record(e) for e in self.edges), "gaps": self.gaps},)


def _node_record(node: VisualNode) -> Mapping[str, object]:
    return {"id": node.identity.canonical, "kind": node.entity_kind.value, "layer": node.layer, "label": node.label, "claim_kind": node.claim_kind.value, "provenance": node.provenance, "observed_at": node.observed_at.isoformat() if node.observed_at else None, "project_context": node.project_context, "externally_referenced": node.externally_referenced, "gaps": node.gaps}


def _edge_record(edge: VisualEdge) -> Mapping[str, object]:
    return {"source": edge.source.canonical, "target": edge.target.canonical, "kind": edge.relationship_kind, "claim_kind": edge.claim_kind.value, "evidence": edge.evidence, "confidence": edge.confidence, "method": edge.method, "method_version": edge.method_version, "uncertainty": edge.uncertainty}


def build_performance_visual_map(graph: PerformanceGraph, *, project_context: str | None = None, node_labels: Mapping[Identity, str] | None = None, external_nodes: frozenset[Identity] = frozenset(), node_metadata: Mapping[Identity, VisualNodeMetadata] | None = None) -> PerformanceVisualMap:
    """Adapt a rebuildable relationship graph without adding relationships or nodes."""
    node_labels, node_metadata = node_labels or {}, node_metadata or {}
    graph_nodes = graph.nodes
    if not set(node_labels) <= graph_nodes or not external_nodes <= graph_nodes or not set(node_metadata) <= graph_nodes:
        raise ValueError("visual-map metadata may only describe graph nodes")
    nodes = tuple(VisualNode(node, node.kind, _layer(node.kind), node_labels.get(node, metadata.label or node.canonical), metadata.claim_kind, metadata.provenance, metadata.observed_at, metadata.project_context or project_context, metadata.externally_referenced or node in external_nodes, metadata.gaps) for node in sorted(graph_nodes, key=lambda item: item.canonical) for metadata in (node_metadata.get(node, VisualNodeMetadata()),))
    edges = tuple(VisualEdge(edge.source, edge.target, edge.kind.value, edge.claim_kind, edge.evidence, edge.confidence, edge.method, edge.method_version, edge.uncertainty) for edge in sorted(dict.fromkeys(graph.edges), key=lambda edge: (edge.source.canonical, edge.target.canonical, edge.kind.value, edge.evidence)))
    return PerformanceVisualMap(VISUAL_PROJECTION_VERSION, project_context, nodes, edges, tuple(sorted(set(graph.gaps))))


def build_performance_visual_map_from_inputs(prompt_runs: tuple[PromptRun, ...], **composition_inputs: object) -> PerformanceVisualMap:
    """Build a map through the relationship-graph composition owner, not caller-made edges."""
    visual_keys = {"project_context", "node_labels", "external_nodes", "node_metadata"}
    graph_inputs = {key: value for key, value in composition_inputs.items() if key not in visual_keys}
    visual_inputs = {key: value for key, value in composition_inputs.items() if key in visual_keys}
    return build_performance_visual_map(compose_graph(prompt_runs, **graph_inputs), **visual_inputs)


@dataclass(frozen=True, slots=True)
class LineageRevisionNode:
    version_id: str; parent_version_id: str | None; observed_at: datetime; requirement_counts: Mapping[str, int]
    claim_kind: ClaimKind; change_set_ids: tuple[str, ...] = (); verification_ids: tuple[str, ...] = (); feedback_ids: tuple[str, ...] = (); runtime_references: tuple[ExternalReference, ...] = (); gaps: tuple[str, ...] = ()
    repository_outcome: Mapping[str, object] | None = None; verification_outcome: tuple[Mapping[str, object], ...] = (); feedback_outcome: tuple[Mapping[str, object], ...] = (); runtime_outcome: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class LineageRevisionEdge:
    parent_version_id: str; child_version_id: str; added_constraints: tuple[str, ...]; removed_constraints: tuple[str, ...]
    added_acceptance: tuple[str, ...]; removed_acceptance: tuple[str, ...]; added_verification: tuple[str, ...]; removed_verification: tuple[str, ...]
    unchanged_requirements: int; outcome_shift: object | None; method: str; method_version: str; uncertainty: str


@dataclass(frozen=True, slots=True)
class PromptLineageVisualization:
    schema_version: str; revisions: tuple[LineageRevisionNode, ...]; edges: tuple[LineageRevisionEdge, ...]; gaps: tuple[str, ...]

    def as_records(self) -> tuple[Mapping[str, object], ...]:
        return ({"schema_version": self.schema_version, "revisions": tuple({"version_id": n.version_id, "parent_version_id": n.parent_version_id, "observed_at": n.observed_at.isoformat(), "requirement_counts": dict(n.requirement_counts), "claim_kind": n.claim_kind.value, "change_set_ids": n.change_set_ids, "verification_ids": n.verification_ids, "feedback_ids": n.feedback_ids, "runtime_references": tuple(_structured_record(r) for r in n.runtime_references), "repository_outcome": n.repository_outcome, "verification_outcome": n.verification_outcome, "feedback_outcome": n.feedback_outcome, "runtime_outcome": n.runtime_outcome, "gaps": n.gaps} for n in self.revisions), "edges": tuple({"parent_version_id": e.parent_version_id, "child_version_id": e.child_version_id, "added_constraints": e.added_constraints, "removed_constraints": e.removed_constraints, "added_acceptance": e.added_acceptance, "removed_acceptance": e.removed_acceptance, "added_verification": e.added_verification, "removed_verification": e.removed_verification, "unchanged_requirements": e.unchanged_requirements, "outcome_shift": _structured_record(e.outcome_shift), "method": e.method, "method_version": e.method_version, "uncertainty": e.uncertainty} for e in self.edges), "gaps": self.gaps},)


def _structured_record(value: object) -> object:
    """Serialize bounded public fields, never Python implementation reprs."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, ExternalReference):
        return {"provider": value.provider, "kind": value.kind, "value": value.value, "contract_version": value.contract_version}
    if is_dataclass(value):
        return {key: _structured_record(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _structured_record(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_structured_record(item) for item in value)
    raise TypeError(f"unsupported structured projection value: {type(value).__name__}")


def build_prompt_lineage_visualization(revisions: tuple[PromptRevision, ...], links: tuple[PromptLineageLink, ...], *, change_sets: Mapping[str, tuple[str, ...]] | None = None, verification_ids: Mapping[str, tuple[str, ...]] | None = None, feedback_ids: Mapping[str, tuple[str, ...]] | None = None, runtime_references: Mapping[str, tuple[ExternalReference, ...]] | None = None, change_evidence: Mapping[str, ChangeEvidence] | None = None, verifications: Mapping[str, tuple[VerificationEvidence, ...]] | None = None, feedback: Mapping[str, tuple[FeedbackRecord, ...]] | None = None) -> PromptLineageVisualization:
    """Compose declared lineage with supplied authoritative outcome references; never infer ancestry."""
    change_sets, verification_ids, feedback_ids, runtime_references = change_sets or {}, verification_ids or {}, feedback_ids or {}, runtime_references or {}
    change_evidence, verifications, feedback = change_evidence or {}, verifications or {}, feedback or {}
    ids = [r.version_id for r in revisions]
    if len(ids) != len(set(ids)): raise ValueError("duplicate revision ids in visualization")
    known = set(ids)
    if any(key not in known for source in (change_sets, verification_ids, feedback_ids, runtime_references, change_evidence, verifications, feedback) for key in source): raise ValueError("lineage evidence must belong to represented revisions")
    expected = {(r.parent_version_id, r.version_id) for r in revisions if r.parent_version_id is not None}
    actual = {(e.parent_version_id, e.child_version_id) for e in links}
    if actual != expected: raise ValueError("visualization links must exactly represent declared parent relationships")
    nodes, gaps = [], []
    for revision in sorted(revisions, key=lambda r: (r.observed_at, r.version_id)):
        counts = {kind.value: sum(item.type is kind for item in revision.features.requirements) for kind in RequirementType}
        missing = tuple(name for name, source in (("change_sets", change_sets), ("verification", verification_ids), ("feedback", feedback_ids), ("runtime_outcomes", runtime_references)) if revision.version_id not in source)
        changes = change_evidence.get(revision.version_id)
        repository_outcome = None if changes is None else {"created": changes.created, "modified": changes.modified, "deleted": changes.deleted, "file_count": len(changes.created) + len(changes.modified) + len(changes.deleted)}
        verification_outcome = tuple({"id": item.identity, "source": item.source.value, "status": item.status, "duration_ms": item.duration_ms, "exit_code": item.exit_code, "changed_files": item.changed_files, "uncertainty": item.uncertainty} for item in verifications.get(revision.version_id, ()))
        feedback_outcome = tuple({"id": item.id, "judgment": item.judgment.value, "reasons": tuple(reason.value for reason in item.reasons), "submitted_at": item.submitted_at.isoformat(), "confidence": item.confidence, "uncertainty": item.uncertainty} for item in feedback.get(revision.version_id, ()))
        runtime_outcome = tuple(_structured_record(item) for item in runtime_references.get(revision.version_id, ()))
        nodes.append(LineageRevisionNode(revision.version_id, revision.parent_version_id, revision.observed_at, counts, ClaimKind.DERIVED, change_sets.get(revision.version_id, ()), verification_ids.get(revision.version_id, ()), feedback_ids.get(revision.version_id, ()), runtime_references.get(revision.version_id, ()), tuple(f"unavailable:{name}" for name in missing), repository_outcome, verification_outcome, feedback_outcome, runtime_outcome))
        gaps.extend(f"{revision.version_id}:unavailable:{name}" for name in missing)
    edges = tuple(LineageRevisionEdge(e.parent_version_id, e.child_version_id, e.added_constraints, e.removed_constraints, e.added_acceptance, e.removed_acceptance, e.added_verification, e.removed_verification, e.unchanged_requirements, e.outcome_shift, e.method, e.method_version, e.uncertainty) for e in links)
    return PromptLineageVisualization(PROMPT_LINEAGE_VISUAL_PROJECTION_VERSION, tuple(nodes), edges, tuple(sorted(gaps)))


@dataclass(frozen=True, slots=True)
class NeighborhoodVisualNode:
    prompt_run_id: str; bucket: str | None; score: float | None; signals: tuple[object, ...]; reasons: tuple[str, ...]; feedback_ids: tuple[str, ...]; claim_kind: ClaimKind; uncertainty: str


@dataclass(frozen=True, slots=True)
class ExperienceNeighborhoodVisualization:
    schema_version: str; center: NeighborhoodVisualNode; buckets: Mapping[str, tuple[NeighborhoodVisualNode, ...]]; method: str; method_version: str; claim_kind: ClaimKind; gaps: tuple[str, ...]

    def as_records(self) -> tuple[Mapping[str, object], ...]:
        return ({"schema_version": self.schema_version, "center": {"prompt_run_id": self.center.prompt_run_id}, "buckets": {name: tuple({"prompt_run_id": n.prompt_run_id, "score": n.score, "signals": tuple({"name": s.name, "value": s.value, "weight": s.weight, "evidence": s.evidence} for s in n.signals), "reasons": n.reasons, "feedback_ids": n.feedback_ids, "claim_kind": n.claim_kind.value, "uncertainty": n.uncertainty} for n in values) for name, values in self.buckets.items()}, "method": self.method, "method_version": self.method_version, "claim_kind": self.claim_kind.value, "gaps": self.gaps},)


def build_experience_neighborhood_visualization(neighborhood: Neighborhood, query: Experience, candidates: Mapping[str, Experience]) -> ExperienceNeighborhoodVisualization:
    """Expose existing bucketed retrieval, including empty buckets, without recommendation semantics."""
    if neighborhood.query_prompt_run_id != query.prompt_run_id: raise ValueError("neighborhood center must match query experience")
    member_ids = [m.match.prompt_run_id for m in neighborhood.members]
    if len(member_ids) != len(set(member_ids)): raise ValueError("neighborhood contains duplicate candidate ids")
    if any(member_id not in candidates for member_id in member_ids): raise ValueError("candidate details are required for each neighborhood member")
    center = NeighborhoodVisualNode(query.prompt_run_id, None, None, (), (), tuple(r.id for r in query.feedback), ClaimKind.DERIVED, "center is the query experience, not a similarity result")
    buckets = {bucket: tuple(NeighborhoodVisualNode(m.match.prompt_run_id, bucket, m.match.score, m.match.signals, m.match.reasons, tuple(r.id for r in candidates[m.match.prompt_run_id].feedback), m.match.claim_kind, m.match.uncertainty) for m in neighborhood.bucket(bucket)) for bucket in BUCKETS}
    gaps = [f"empty_bucket:{bucket}" for bucket, members in buckets.items() if not members]
    gaps.extend(neighborhood.gaps)
    return ExperienceNeighborhoodVisualization(VISUAL_PROJECTION_VERSION, center, buckets, neighborhood.method, neighborhood.method_version, neighborhood.claim_kind, tuple(sorted(set(gaps))))


def as_query_projection(name: str, projection: PerformanceVisualMap | PromptLineageVisualization | ExperienceNeighborhoodVisualization):
    """Use the existing project-authorized QueryProjection boundary without a new API."""
    from .query_api import QueryProjection
    return QueryProjection(name, projection.schema_version, ClaimKind.DERIVED, projection.as_records(), (), "rebuildable Visual Intelligence projection; it is not canonical evidence, causal proof, or a recommendation")
