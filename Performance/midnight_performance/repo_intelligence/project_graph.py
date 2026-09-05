"""Project knowledge graph overlay for Repo Intelligent.

A rebuildable, deterministic, project-scoped overlay — never a second
source of truth.  Performance entities and Memory records appear as
typed reference nodes owned by their canonical products; repository
structure comes from resolved entity refs; intelligence artifacts
(signals, insights, questions, exposures, outcomes) link through
stable ``GraphLink`` edges that separate exact structural derivation
from probabilistic semantic edges.  The same authoritative inputs always
produce the same graph (generation digest); incremental updates are
provably equal to a full rebuild.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from itertools import combinations
from pathlib import PurePosixPath
from typing import Iterable, Mapping

from ..contracts import ClaimKind, ExternalReference, Identity
from .authorization import CrossProjectAccessError
from .contracts import (
    AnalogyRecord,
    EdgeClass,
    Exposure,
    GraphLink,
    GraphRelation,
    LearningOutcome,
    ProjectEntityRef,
    ProjectEntityRefKind,
    ProjectInsight,
    ResearchQuestion,
)
from .evidence_join import JoinedEvidence
from .identities import (
    RepoIntelligenceKind,
    RepoIdentity,
    deterministic_repo_identity,
    is_performance_canonical,
    is_repo_intelligence_canonical,
)
from .question_compiler import abstract_concept
from .signals import ScoredSignal

GRAPH_METHOD = "project-graph-overlay"
GRAPH_METHOD_VERSION = "1"

_MAX_LABEL_CHARS = 120
_MAX_SUPPORTED_BY = 16

_FILE_ROLES = frozenset(
    {
        ProjectEntityRefKind.MODULE,
        ProjectEntityRefKind.FILE,
        ProjectEntityRefKind.TEST,
        ProjectEntityRefKind.CONFIG,
        ProjectEntityRefKind.DOC,
    }
)

_EXTERNAL_SOURCE_CLASS_VALUES = frozenset(
    {
        "github_external_repository",
        "official_docs",
        "standards",
        "papers",
        "web",
    }
)


class NodeFamily(str, Enum):
    """Federated node families; only Repo Intelligent's own are materialized."""

    REPOSITORY_STRUCTURE = "repository_structure"
    PERFORMANCE_EVIDENCE = "performance_evidence"
    MEMORY_REFERENCE = "memory_reference"
    CONCEPT = "concept"
    RESEARCH = "research"
    EXTERNAL_KNOWLEDGE = "external_knowledge"
    INTELLIGENCE = "intelligence"


class ConceptRole(str, Enum):
    """Topic/Concept/Technology/Dependency/Pattern/FailureMode families."""

    TOPIC = "topic"
    CONCEPT = "concept"
    TECHNOLOGY = "technology"
    DEPENDENCY = "dependency"
    PATTERN = "pattern"
    FAILURE_MODE = "failure_mode"


def concept_identity(
    project: Identity, concept: str, role: ConceptRole = ConceptRole.CONCEPT
) -> RepoIdentity:
    if not concept.strip():
        raise ValueError("concept nodes require a non-blank concept")
    return deterministic_repo_identity(
        RepoIntelligenceKind.CONCEPT,
        f"{project.canonical}|{role.value}|{concept.strip().lower()}",
    )


def memory_ref_identity(project: Identity, reference: ExternalReference) -> RepoIdentity:
    return deterministic_repo_identity(
        RepoIntelligenceKind.MEMORY_REF,
        f"{project.canonical}|{reference.provider}:{reference.kind}:{reference.value}",
    )


def _label(text: str) -> str:
    return " ".join(text.split())[:_MAX_LABEL_CHARS]


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One overlay node: a stable typed reference or a derived concept."""

    identity: str
    project: str
    family: NodeFamily
    label: str
    claim_kind: ClaimKind
    first_seen: datetime
    last_seen: datetime
    provenance: tuple[str, ...] = ()
    concept_role: ConceptRole | None = None

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise ValueError("graph nodes require a canonical identity")
        if not (self.identity.startswith("mp:") or self.identity.startswith("ri:")):
            raise ValueError("graph node identities must be mp: or ri: canonical identities")
        if not self.label.strip():
            raise ValueError("graph nodes require a label")
        if self.first_seen.tzinfo is None or self.last_seen.tzinfo is None:
            raise ValueError("graph node times must be timezone-aware")
        if self.first_seen > self.last_seen:
            raise ValueError("first_seen must not be after last_seen")

    def to_dict(self) -> dict:
        return {
            "identity": self.identity,
            "project": self.project,
            "family": self.family.value,
            "label": self.label,
            "claim_kind": self.claim_kind.value,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "provenance": list(self.provenance),
            "concept_role": self.concept_role.value if self.concept_role else None,
        }


@dataclass(frozen=True, slots=True)
class ProjectKnowledgeGraph:
    """Deterministic overlay: nodes + links + generation digest + gaps."""

    project: str
    repository_key: str
    nodes: tuple[GraphNode, ...]
    links: tuple[GraphLink, ...]
    generation: str
    built_at: datetime
    gaps: tuple[str, ...] = ()
    schema_version: int = 1

    def node(self, identity: str) -> GraphNode | None:
        for candidate in self.nodes:
            if candidate.identity == identity:
                return candidate
        return None

    def links_for(self, identity: str) -> tuple[GraphLink, ...]:
        return tuple(
            link for link in self.links if link.source == identity or link.target == identity
        )

    def to_document(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "repository_key": self.repository_key,
            "generation": self.generation,
            "built_at": self.built_at.isoformat(),
            "nodes": [node.to_dict() for node in self.nodes],
            "links": [link.to_dict() for link in self.links],
            "gaps": list(self.gaps),
        }


def _sorted_nodes(nodes: Iterable[GraphNode]) -> tuple[GraphNode, ...]:
    return tuple(sorted(nodes, key=lambda n: n.identity))


def _sorted_links(links: Iterable[GraphLink]) -> tuple[GraphLink, ...]:
    return tuple(
        sorted(
            links,
            key=lambda l: (l.relation.value, l.source, l.target, l.method, l.method_version),
        )
    )


def _generation(nodes: tuple[GraphNode, ...], links: tuple[GraphLink, ...]) -> str:
    def _canonical(item: dict) -> str:
        return json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)

    payload = json.dumps(
        {
            "nodes": sorted(_canonical(node.to_dict()) for node in nodes),
            "links": sorted(_canonical(link.to_dict()) for link in links),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _GraphBuilder:
    def __init__(self, project: Identity, repository_key: str, now: datetime) -> None:
        self.project = project
        self.repository_key = repository_key
        self.now = now
        self.nodes: dict[str, GraphNode] = {}
        self.links: dict[str, GraphLink] = {}
        self.gaps: list[str] = []
        self.entity_by_path: dict[str, str] = {}

    def check_same_project(self, record_project: Identity, what: str) -> None:
        if record_project != self.project:
            raise CrossProjectAccessError(
                f"cross-project {what} reached the graph builder; failing closed"
            )

    def add_node(self, node: GraphNode) -> None:
        prior = self.nodes.get(node.identity)
        if prior is None:
            self.nodes[node.identity] = node
            return
        self.nodes[node.identity] = GraphNode(
            identity=node.identity,
            project=node.project,
            family=node.family,
            label=node.label or prior.label,
            claim_kind=node.claim_kind,
            first_seen=min(prior.first_seen, node.first_seen),
            last_seen=max(prior.last_seen, node.last_seen),
            provenance=tuple(dict.fromkeys(prior.provenance + node.provenance)),
            concept_role=node.concept_role or prior.concept_role,
        )

    def reference_node(
        self,
        canonical: str,
        *,
        family: NodeFamily,
        label: str,
        observed_at: datetime,
        last_seen: datetime | None = None,
        provenance: tuple[str, ...] = (),
        concept_role: ConceptRole | None = None,
    ) -> str:
        self.add_node(
            GraphNode(
                identity=canonical,
                project=self.project.canonical,
                family=family,
                label=_label(label),
                claim_kind=ClaimKind.DERIVED,
                first_seen=observed_at,
                last_seen=last_seen if last_seen is not None else observed_at,
                provenance=provenance,
                concept_role=concept_role,
            )
        )
        return canonical

    def performance_reference(self, canonical: str, observed_at: datetime) -> str:
        try:
            identity = Identity.parse(canonical)
        except ValueError:
            self.gaps.append(f"unparseable performance reference skipped: {canonical}")
            return canonical
        return self.reference_node(
            canonical,
            family=NodeFamily.PERFORMANCE_EVIDENCE,
            label=f"{identity.kind.value} {str(identity.value)[:8]}",
            observed_at=observed_at,
            provenance=("typed reference; Performance owns the evidence",),
        )

    def ensure_evidence_node(self, canonical: str, observed_at: datetime) -> str | None:
        """Guarantee a node exists for any mp:/ri: evidence anchor (no orphans)."""
        if canonical in self.nodes:
            return canonical
        if is_performance_canonical(canonical):
            return self.performance_reference(canonical, observed_at)
        if is_repo_intelligence_canonical(canonical):
            return self.reference_node(
                canonical,
                family=NodeFamily.INTELLIGENCE,
                label=f"intelligence anchor {canonical[-12:]}",
                observed_at=observed_at,
                provenance=("typed reference; Repo Intelligent owns the derived record",),
            )
        self.gaps.append(f"evidence anchor with unknown namespace skipped: {canonical}")
        return None

    def link(
        self,
        *,
        relation: GraphRelation,
        source: str,
        target: str,
        observed_at: datetime | None = None,
        evidence_ids: tuple[str, ...] = (),
        uncertainty: str = "direct reification of typed evidence",
        edge_class: EdgeClass = EdgeClass.STRUCTURAL,
        claim_kind: ClaimKind = ClaimKind.DERIVED,
        confidence: float | None = None,
        first_seen: datetime | None = None,
        last_seen: datetime | None = None,
    ) -> None:
        if source == target:
            return
        moment = observed_at if observed_at is not None else self.now
        identity = deterministic_repo_identity(
            RepoIntelligenceKind.GRAPH_LINK,
            f"{self.project.canonical}|{relation.value}|{source}|{target}"
            f"|{GRAPH_METHOD}|{GRAPH_METHOD_VERSION}",
        )
        self.add_link(
            GraphLink(
                identity=identity,
                project=self.project,
                source=source,
                target=target,
                relation=relation,
                edge_class=edge_class,
                claim_kind=claim_kind,
                method=GRAPH_METHOD,
                method_version=GRAPH_METHOD_VERSION,
                uncertainty=uncertainty,
                evidence_ids=evidence_ids or (source,),
                first_seen=first_seen if first_seen is not None else moment,
                last_seen=last_seen if last_seen is not None else moment,
                confidence=confidence,
            )
        )

    def add_link(self, link: GraphLink) -> None:
        self.links[link.identity.canonical] = link


def _add_structure(
    builder: _GraphBuilder, entity_refs: Iterable[ProjectEntityRef]
) -> dict[str, ProjectEntityRef]:
    by_path: dict[str, ProjectEntityRef] = {}
    by_canonical: dict[str, ProjectEntityRef] = {}
    for ref in sorted(entity_refs, key=lambda r: r.identity.canonical):
        builder.check_same_project(ref.project, "entity refs")
        by_canonical[ref.identity.canonical] = ref
        if ref.path is not None and ref.ref_kind in _FILE_ROLES:
            by_path[ref.path] = ref
            builder.entity_by_path[ref.path] = ref.identity.canonical
        builder.reference_node(
            ref.identity.canonical,
            family=NodeFamily.REPOSITORY_STRUCTURE,
            label=ref.path or ref.qualified_name or ref.repository_key,
            observed_at=ref.first_seen_at,
            last_seen=ref.last_seen_at,
            provenance=(f"resolver {ref.resolver_tool}:{ref.resolver_version}",),
        )

    repo_ref = next(
        (r for r in by_canonical.values() if r.ref_kind is ProjectEntityRefKind.REPOSITORY),
        None,
    )
    packages = {
        r.path: r for r in by_canonical.values() if r.ref_kind is ProjectEntityRefKind.PACKAGE
    }
    for ref in sorted(by_canonical.values(), key=lambda r: r.identity.canonical):
        if ref.ref_kind is ProjectEntityRefKind.REPOSITORY:
            continue
        parent = _structure_parent(ref, by_path, packages, repo_ref)
        if parent is None:
            builder.gaps.append(
                f"entity ref without a structural parent: {ref.path or ref.qualified_name}"
            )
            continue
        builder.link(
            relation=GraphRelation.CONTAINS,
            source=parent.identity.canonical,
            target=ref.identity.canonical,
            first_seen=ref.first_seen_at,
            last_seen=ref.last_seen_at,
            evidence_ids=(ref.identity.canonical,),
            uncertainty="deterministic path-hierarchy containment",
        )
    return by_path


def _structure_parent(
    ref: ProjectEntityRef,
    by_path: Mapping[str, ProjectEntityRef],
    packages: Mapping[str, ProjectEntityRef],
    repo_ref: ProjectEntityRef | None,
) -> ProjectEntityRef | None:
    if ref.ref_kind in (ProjectEntityRefKind.SYMBOL, ProjectEntityRefKind.CODE_REGION):
        return by_path.get(ref.path or "")
    if ref.ref_kind is ProjectEntityRefKind.PACKAGE:
        pure = PurePosixPath(ref.path or "")
        for ancestor in reversed(list(pure.parents)[:-1] if len(pure.parents) > 1 else list(pure.parents)):
            if str(ancestor) in packages:
                return packages[str(ancestor)]
        return repo_ref
    if ref.path is None:
        return None
    pure = PurePosixPath(ref.path)
    for ancestor in reversed(list(pure.parents)[:-1] if len(pure.parents) > 1 else list(pure.parents)):
        text = str(ancestor)
        if text in packages:
            return packages[text]
        if text in by_path:
            return by_path[text]
    return repo_ref


def _add_joined(builder: _GraphBuilder, joined: JoinedEvidence) -> None:
    builder.check_same_project(joined.project, "joined evidence")
    for path, events in joined.timelines.items():
        source = builder.entity_by_path.get(path)
        if source is None:
            builder.gaps.append(f"event path without a structure node: {path}")
            continue
        for event in events:
            if event.event_kind == "change":
                target = builder.performance_reference(event.observation_canonical, event.observed_at)
                builder.link(
                    relation=GraphRelation.CHANGED_IN,
                    source=source,
                    target=target,
                    observed_at=event.observed_at,
                    evidence_ids=(event.observation_canonical,),
                    first_seen=event.observed_at,
                    last_seen=event.observed_at,
                )
            elif event.event_kind == "verification":
                target = builder.performance_reference(event.observation_canonical, event.observed_at)
                relation = (
                    GraphRelation.FAILED_IN if event.passed is False else GraphRelation.VERIFIED_BY
                )
                builder.link(
                    relation=relation,
                    source=source,
                    target=target,
                    observed_at=event.observed_at,
                    evidence_ids=(event.observation_canonical,),
                    first_seen=event.observed_at,
                    last_seen=event.observed_at,
                )
            elif event.event_kind == "intent":
                target = builder.performance_reference(event.observation_canonical, event.observed_at)
                builder.link(
                    relation=GraphRelation.DISCUSSED_IN,
                    source=source,
                    target=target,
                    observed_at=event.observed_at,
                    evidence_ids=(event.observation_canonical,),
                    uncertainty="episode-correlated prompt occurrence; occurrence only, not content",
                    first_seen=event.observed_at,
                    last_seen=event.observed_at,
                )


def _concept_canonical(builder: _GraphBuilder, path: str) -> str | None:
    try:
        concept = abstract_concept(path, repository_key=builder.repository_key)
    except ValueError:
        builder.gaps.append(f"no abstractable concept for path: {path}")
        return None
    identity = concept_identity(builder.project, concept).canonical
    builder.reference_node(
        identity,
        family=NodeFamily.CONCEPT,
        label=concept,
        observed_at=builder.now,
        provenance=("deterministic token abstraction",),
        concept_role=ConceptRole.CONCEPT,
    )
    return identity


def _add_about_links(builder: _GraphBuilder) -> None:
    for path, entity in sorted(builder.entity_by_path.items()):
        concept = _concept_canonical(builder, path)
        if concept is None:
            continue
        builder.link(
            relation=GraphRelation.ABOUT,
            source=entity,
            target=concept,
            evidence_ids=(entity,),
            uncertainty="deterministic token abstraction of the repository path",
        )


def _add_signals(builder: _GraphBuilder, signals: Iterable[ScoredSignal]) -> None:
    for scored in signals:
        signal = scored.signal
        builder.check_same_project(signal.project, "signals")
        signal_node = builder.reference_node(
            signal.identity.canonical,
            family=NodeFamily.INTELLIGENCE,
            label=f"{signal.signal_kind}: {signal.summary}",
            observed_at=signal.window_start,
            provenance=(f"{signal.method}:{signal.method_version}",),
        )
        evidence_ids = signal.evidence_ids[:8]
        for evidence in evidence_ids:
            target = builder.ensure_evidence_node(evidence, signal.window_start)
            if target is None:
                continue
            builder.link(
                relation=GraphRelation.DERIVED_FROM,
                source=signal_node,
                target=target,
                evidence_ids=evidence_ids,
                uncertainty="signal derived from the cited evidence ids",
            )
        for path in scored.paths:
            concept = _concept_canonical(builder, path)
            if concept is not None:
                builder.link(
                    relation=GraphRelation.ABOUT,
                    source=signal_node,
                    target=concept,
                    evidence_ids=(signal.identity.canonical,),
                    uncertainty="signal concerns the abstracted concept of its entity path",
                )


def _add_insights(
    builder: _GraphBuilder, insights: Iterable[tuple[ProjectInsight, object]]
) -> None:
    for insight, bundle in insights:
        builder.check_same_project(insight.project, "insights")
        insight_node = builder.reference_node(
            insight.identity.canonical,
            family=NodeFamily.INTELLIGENCE,
            label=insight.statement,
            observed_at=insight.valid_from,
            provenance=(
                f"{insight.method}:{insight.method_version}",
                f"claim {insight.claim_kind.value}",
            ),
        )
        if bundle is not None:
            bundle_node = builder.reference_node(
                bundle.identity.canonical,
                family=NodeFamily.INTELLIGENCE,
                label=f"evidence bundle ({len(bundle.items)} items)",
                observed_at=bundle.created_at,
                provenance=("rebuildable evidence bundle",),
            )
            builder.link(
                relation=GraphRelation.DERIVED_FROM,
                source=insight_node,
                target=bundle_node,
                evidence_ids=(bundle_node,),
                uncertainty="insight derived from its evidence bundle",
            )
            for item in bundle.items[:_MAX_SUPPORTED_BY]:
                if item.source_class.value in _EXTERNAL_SOURCE_CLASS_VALUES:
                    target = builder.reference_node(
                        item.ref,
                        family=NodeFamily.EXTERNAL_KNOWLEDGE,
                        label=f"external evidence {item.ref[-12:]}",
                        observed_at=item.captured_at,
                        provenance=("typed external reference",),
                    )
                else:
                    target = builder.ensure_evidence_node(item.ref, item.captured_at)
                if target is None:
                    builder.gaps.append(f"unsupported evidence ref skipped: {item.ref}")
                    continue
                builder.link(
                    relation=GraphRelation.SUPPORTED_BY,
                    source=insight_node,
                    target=target,
                    evidence_ids=(item.ref,),
                    uncertainty="insight supported by bundled evidence item",
                )
        if insight.superseded_by is not None:
            builder.link(
                relation=GraphRelation.SUPERSEDES,
                source=insight.superseded_by.canonical,
                target=insight_node,
                evidence_ids=(insight.superseded_by.canonical,),
                uncertainty="supersession recorded on the superseded insight",
            )


def _add_questions(
    builder: _GraphBuilder, questions: Iterable[ResearchQuestion]
) -> None:
    for question in questions:
        builder.check_same_project(question.project, "research questions")
        question_node = builder.reference_node(
            question.identity.canonical,
            family=NodeFamily.RESEARCH,
            label=question.question_text,
            observed_at=question.created_at,
            provenance=(f"status {question.status.value}",),
        )
        for ref in question.triggered_by[:8]:
            target = builder.ensure_evidence_node(ref, question.created_at)
            if target is None:
                continue
            builder.link(
                relation=GraphRelation.DERIVED_FROM,
                source=question_node,
                target=target,
                evidence_ids=tuple(question.triggered_by[:8]),
                uncertainty="question compiled from its triggering evidence",
            )
        matched = False
        for node in sorted(builder.nodes.values(), key=lambda n: n.identity):
            if (
                node.family is NodeFamily.CONCEPT
                and node.label
                and node.label in question.question_text
            ):
                builder.link(
                    relation=GraphRelation.RELEVANT_TO,
                    source=question_node,
                    target=node.identity,
                    evidence_ids=(question.identity.canonical,),
                    uncertainty="deterministic concept-label match in the question text",
                )
                matched = True
        if not matched:
            builder.gaps.append(
                f"question has no concept match in the overlay: {question.identity.canonical}"
            )


def _add_exposures(builder: _GraphBuilder, exposures: Iterable[Exposure]) -> None:
    for exposure in exposures:
        builder.check_same_project(exposure.project, "exposures")
        insight_target = builder.ensure_evidence_node(
            exposure.insight.canonical, exposure.occurred_at
        )
        exposure_node = builder.reference_node(
            exposure.identity.canonical,
            family=NodeFamily.INTELLIGENCE,
            label=f"exposure {exposure.channel.value} {exposure.outcome.value}",
            observed_at=exposure.occurred_at,
            provenance=(f"surface {exposure.surface}",),
        )
        if insight_target is None:
            builder.gaps.append(
                f"exposure without a resolvable insight anchor: {exposure.identity.canonical}"
            )
            continue
        builder.link(
            relation=GraphRelation.EXPOSED_AS,
            source=insight_target,
            target=exposure_node,
            evidence_ids=(exposure.identity.canonical,),
            uncertainty="insight exposed as this exposure event",
            first_seen=exposure.occurred_at,
            last_seen=exposure.occurred_at,
        )


def _add_outcomes(builder: _GraphBuilder, outcomes: Iterable[LearningOutcome]) -> None:
    for outcome in outcomes:
        builder.check_same_project(outcome.project, "learning outcomes")
        exposure_source = builder.ensure_evidence_node(
            outcome.exposure.canonical, outcome.created_at
        )
        outcome_node = builder.reference_node(
            outcome.identity.canonical,
            family=NodeFamily.INTELLIGENCE,
            label=f"outcome {outcome.association.value} ({outcome.claim_kind.value})",
            observed_at=outcome.created_at,
            provenance=(f"{outcome.method}:{outcome.method_version}",),
        )
        if exposure_source is None:
            builder.gaps.append(
                f"outcome without a resolvable exposure anchor: {outcome.identity.canonical}"
            )
            continue
        builder.link(
            relation=GraphRelation.LEARNED_FROM,
            source=outcome_node,
            target=exposure_source,
            evidence_ids=(outcome.identity.canonical,),
            uncertainty="association observed after exposure; association is not causality",
            first_seen=outcome.window_start,
            last_seen=outcome.window_end,
        )
        for ref in outcome.associated_performance_refs[:8]:
            target = builder.ensure_evidence_node(ref, outcome.created_at)
            if target is None:
                continue
            builder.link(
                relation=GraphRelation.DERIVED_FROM,
                source=outcome_node,
                target=target,
                evidence_ids=(ref,),
                uncertainty="outcome associated with subsequent performance evidence",
            )


_CONTRADICTION_THRESHOLD = 0.5


def _analogies_contradict(left: AnalogyRecord, right: AnalogyRecord) -> bool:
    """Divergent structural-similarity verdicts on a shared dimension, for the same entity."""
    by_dimension_left = {c.dimension: c.similarity for c in left.comparable_dimensions()}
    by_dimension_right = {c.dimension: c.similarity for c in right.comparable_dimensions()}
    shared = set(by_dimension_left) & set(by_dimension_right)
    return any(abs(by_dimension_left[d] - by_dimension_right[d]) >= _CONTRADICTION_THRESHOLD for d in shared)


def _add_analogies(builder: _GraphBuilder, analogies: Iterable[AnalogyRecord]) -> None:
    """External analogies as first-class overlay nodes; divergent verdicts stay CONTRADICTS, not deleted."""
    items = tuple(analogies)
    for record in items:
        builder.check_same_project(record.project, "analogy records")
        analogy_node = builder.reference_node(
            record.identity.canonical,
            family=NodeFamily.EXTERNAL_KNOWLEDGE,
            label=f"analogy {record.identity.canonical[-12:]} (confidence {record.confidence:.2f})",
            observed_at=record.created_at,
            provenance=(f"{record.method}:{record.method_version}",),
        )
        internal_target = builder.ensure_evidence_node(record.internal_entity_ref.canonical, record.created_at)
        external_target = builder.ensure_evidence_node(record.external_repository.canonical, record.created_at)
        if internal_target is not None:
            builder.link(
                relation=GraphRelation.EXTERNAL_ANALOGUE_OF,
                source=internal_target,
                target=analogy_node,
                evidence_ids=record.evidence_ids,
                edge_class=EdgeClass.SEMANTIC,
                claim_kind=ClaimKind.INFERRED,
                confidence=record.confidence,
                uncertainty="structural dimension comparison; not a claim of causal or feature-identical behavior",
                first_seen=record.created_at,
                last_seen=record.created_at,
            )
        if external_target is not None:
            builder.link(
                relation=GraphRelation.EXTERNAL_ANALOGUE_OF,
                source=analogy_node,
                target=external_target,
                evidence_ids=record.evidence_ids,
                edge_class=EdgeClass.SEMANTIC,
                claim_kind=ClaimKind.INFERRED,
                confidence=record.confidence,
                uncertainty="analogy references this external source as its comparison side",
                first_seen=record.created_at,
                last_seen=record.created_at,
            )
        if record.superseded_by is not None:
            builder.link(
                relation=GraphRelation.SUPERSEDES,
                source=record.superseded_by.canonical,
                target=analogy_node,
                evidence_ids=(record.superseded_by.canonical,),
                uncertainty="supersession recorded on the superseded analogy",
            )
    for left, right in combinations(sorted(items, key=lambda r: r.identity.canonical), 2):
        if left.internal_entity_ref != right.internal_entity_ref:
            continue
        if not _analogies_contradict(left, right):
            continue
        builder.link(
            relation=GraphRelation.CONTRADICTS,
            source=left.identity.canonical,
            target=right.identity.canonical,
            evidence_ids=(left.identity.canonical, right.identity.canonical),
            edge_class=EdgeClass.SEMANTIC,
            claim_kind=ClaimKind.INFERRED,
            confidence=min(left.confidence, right.confidence),
            uncertainty=(
                "divergent structural-similarity verdicts for the same internal entity; "
                "both preserved, neither deleted"
            ),
        )


def _add_memory(builder: _GraphBuilder, memory_refs: Iterable[ExternalReference]) -> None:
    for reference in memory_refs:
        identity = memory_ref_identity(builder.project, reference).canonical
        builder.reference_node(
            identity,
            family=NodeFamily.MEMORY_REFERENCE,
            label=f"memory {reference.provider}:{reference.kind}:{reference.value}",
            observed_at=builder.now,
            provenance=("typed external reference; Midnight Memory owns the record",),
        )


def _add_external(builder: _GraphBuilder, external_refs: Iterable) -> None:
    for ref in external_refs:
        builder.check_same_project(ref.project, "external source refs")
        builder.reference_node(
            ref.identity.canonical,
            family=NodeFamily.EXTERNAL_KNOWLEDGE,
            label=f"{ref.source_class.value}: {ref.title}",
            observed_at=ref.captured_at,
            provenance=(
                f"trust {ref.trust_class.value}",
                f"digest {ref.content_digest[:12]}",
                "external text is untrusted evidence",
            ),
        )


def _add_custom_concepts(
    builder: _GraphBuilder, concept_specs: Iterable[tuple[str, ConceptRole]]
) -> None:
    for concept, role in concept_specs:
        identity = concept_identity(builder.project, concept, role).canonical
        builder.reference_node(
            identity,
            family=NodeFamily.CONCEPT,
            label=concept,
            observed_at=builder.now,
            provenance=("caller-supplied concept node",),
            concept_role=role,
        )


def build_project_graph(
    project: Identity,
    repository_key: str,
    *,
    entity_refs: Iterable[ProjectEntityRef] = (),
    joined: JoinedEvidence | None = None,
    signals: Iterable[ScoredSignal] = (),
    insights: Iterable[tuple[ProjectInsight, object]] = (),
    questions: Iterable[ResearchQuestion] = (),
    exposures: Iterable[Exposure] = (),
    outcomes: Iterable[LearningOutcome] = (),
    memory_refs: Iterable[ExternalReference] = (),
    external_refs: Iterable = (),
    concept_specs: Iterable[tuple[str, ConceptRole]] = (),
    analogies: Iterable[AnalogyRecord] = (),
    extra_links: Iterable[GraphLink] = (),
    now: datetime,
) -> ProjectKnowledgeGraph:
    """Deterministically build the federated overlay from authoritative inputs."""
    if now.tzinfo is None:
        raise ValueError("graph build time must be timezone-aware")
    builder = _GraphBuilder(project, repository_key, now)
    _add_structure(builder, entity_refs)
    if joined is not None:
        _add_joined(builder, joined)
    _add_about_links(builder)
    _add_signals(builder, signals)
    _add_insights(builder, insights)
    _add_questions(builder, questions)
    _add_exposures(builder, exposures)
    _add_outcomes(builder, outcomes)
    _add_memory(builder, memory_refs)
    _add_analogies(builder, analogies)
    _add_external(builder, external_refs)
    _add_custom_concepts(builder, concept_specs)
    for link in extra_links:
        if link.project != project:
            raise CrossProjectAccessError("cross-project extra link; failing closed")
        builder.add_link(link)
    nodes = _sorted_nodes(builder.nodes.values())
    links = _sorted_links(builder.links.values())
    return ProjectKnowledgeGraph(
        project=project.canonical,
        repository_key=repository_key,
        nodes=nodes,
        links=links,
        generation=_generation(nodes, links),
        built_at=now,
        gaps=tuple(sorted(set(builder.gaps))),
    )


def update_project_graph(
    previous: ProjectKnowledgeGraph,
    project: Identity,
    repository_key: str,
    *,
    changed_paths: frozenset[str],
    now: datetime,
    **build_kwargs,
) -> ProjectKnowledgeGraph:
    """Incremental update: recompute only the changed subgraph, splice, re-digest.

    Correctness contract: with the same authoritative inputs, the updated
    graph equals a full rebuild (proven by tests), and the untouched
    region is preserved.  ``changed_paths`` scopes the affected entity
    region; links are cut when either endpoint leaves the graph.
    """
    if previous.project != project.canonical:
        raise CrossProjectAccessError("cross-project graph update; failing closed")
    rebuilt = build_project_graph(project, repository_key, now=now, **build_kwargs)
    if not changed_paths:
        return rebuilt

    touched = {
        node.identity
        for node in previous.nodes
        if node.label in changed_paths
    }
    affected = set(touched)
    frontier = list(touched)
    while frontier:
        current = frontier.pop()
        for link in previous.links:
            if link.source == current or link.target == current:
                other = link.target if link.source == current else link.source
                if other not in affected:
                    affected.add(other)
                    frontier.append(other)

    kept_nodes = [n for n in previous.nodes if n.identity not in affected]
    kept_node_ids = {n.identity for n in kept_nodes}
    kept_links = [
        l for l in previous.links if l.source in kept_node_ids and l.target in kept_node_ids
    ]
    kept_link_keys = {
        (l.relation.value, l.source, l.target, l.method, l.method_version)
        for l in kept_links
    }
    merged_nodes = list(kept_nodes) + [
        n for n in rebuilt.nodes if n.identity not in kept_node_ids
    ]
    merged_ids = {n.identity for n in merged_nodes}
    merged_links = list(kept_links) + [
        l
        for l in rebuilt.links
        if (l.relation.value, l.source, l.target, l.method, l.method_version)
        not in kept_link_keys
        and l.source in merged_ids
        and l.target in merged_ids
    ]
    nodes = _sorted_nodes(merged_nodes)
    links = _sorted_links(merged_links)
    return ProjectKnowledgeGraph(
        project=previous.project,
        repository_key=repository_key,
        nodes=nodes,
        links=links,
        generation=_generation(nodes, links),
        built_at=now,
        gaps=tuple(sorted(set(previous.gaps) | set(rebuilt.gaps))),
    )


def validate_overlay(graph: ProjectKnowledgeGraph) -> "OverlayIntegrity":
    """Fail-closed integrity: dangling endpoints, project mixtures, digest drift."""
    violations: list[str] = []
    node_ids = {node.identity for node in graph.nodes}
    for link in graph.links:
        if link.source not in node_ids:
            violations.append(f"dangling link source: {link.source} ({link.relation.value})")
        if link.target not in node_ids:
            violations.append(f"dangling link target: {link.target} ({link.relation.value})")
        if link.project.canonical != graph.project:
            violations.append(f"cross-project link in overlay: {link.identity.canonical}")
    for node in graph.nodes:
        if node.project != graph.project:
            violations.append(f"node from another project: {node.identity}")
    if _generation(graph.nodes, graph.links) != graph.generation:
        violations.append("generation digest does not match graph contents")
    return OverlayIntegrity(
        ok=not violations,
        violations=tuple(violations),
        node_count=len(graph.nodes),
        link_count=len(graph.links),
    )


@dataclass(frozen=True, slots=True)
class OverlayIntegrity:
    ok: bool
    violations: tuple[str, ...]
    node_count: int
    link_count: int


def active_links(graph: ProjectKnowledgeGraph, now: datetime) -> tuple[GraphLink, ...]:
    """Links not superseded and not past valid_to (temporal decay honored)."""
    if now.tzinfo is None:
        raise ValueError("active-link evaluation time must be timezone-aware")
    return tuple(link for link in graph.links if not link.is_stale(now))


def stale_links(graph: ProjectKnowledgeGraph, now: datetime) -> tuple[GraphLink, ...]:
    if now.tzinfo is None:
        raise ValueError("stale-link evaluation time must be timezone-aware")
    return tuple(link for link in graph.links if link.is_stale(now))


__all__ = [
    "ConceptRole",
    "GraphNode",
    "NodeFamily",
    "OverlayIntegrity",
    "ProjectKnowledgeGraph",
    "active_links",
    "build_project_graph",
    "concept_identity",
    "memory_ref_identity",
    "stale_links",
    "update_project_graph",
    "validate_overlay",
]
