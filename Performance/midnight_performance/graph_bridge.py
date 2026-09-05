"""Execution 06: `graph.getPromptRun` — the versioned, bounded Desktop read
contract over Performance's real relationship graph for one Prompt Run.

Mirrors `desktop_bridge.py`'s established pattern exactly: a pure function,
project-scoped, self-validated JSON on stdout, no write path. This module
never manufactures a `PromptRun` — it resolves the requested identity's
real existence via `projection_store` (Execution 05's indexed, checkpoint-
verified read path), and only ever fills in richer domains from
caller-supplied evidence (mirroring `build_graph`'s own long-standing
parameters), never inventing missing relationships. Today's real system has
no durable capture for AgentRun/Session/Turn/Tool/Command/Verification/
Feedback/Outcome/Episode/Analysis/Memory-citation evidence — every one of
those domains resolves to an honest gap unless a caller (a future capture
integration, or a test standing in for one) supplies it explicitly.

Default is one Prompt-scoped graph slice; this bridge only ever calls
`build_graph` (one run), never `compose_graph` (many runs) — never defaults
to a full-project graph.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from pathlib import Path
from typing import Mapping

from . import projection_store
from .contract_schema import validate_graph_prompt_run_response
from .contracts import ClaimKind, EntityKind, ExternalReference, Identity, deterministic_identity
from .desktop_bridge import open_project_ledger
from .evidence_citation import EvidenceCitation, feedback_citation, outcome_citation, verification_citation
from .feedback import FeedbackRecord
from .graph_integrity import validate_graph_integrity
from .link_integrity import IntegrityMode
from .memory_bridge import MalformedMemoryRecordError
from .memory_temporal_lineage import MemoryCitationState, pinned_state
from .outcomes import OutcomeReference
from .prompt_run import PromptRun
from .relationship_graph import GRAPH_ALGORITHM_METHOD, GRAPH_ALGORITHM_VERSION, PerformanceGraph, ResolvedRepositoryEntity, build_graph, traverse
from .verification import VerificationEvidence
from .visual_intelligence import PerformanceVisualMap, VisualNodeMetadata, _edge_record, _node_record, build_performance_visual_map

GRAPH_BRIDGE_VERSION = 1
DEFAULT_MAX_NODES = 200
DEFAULT_MAX_EDGES = 400
CURSOR_FORMAT_VERSION = 1


class PromptRunNotFoundError(ValueError):
    """Raised when the requested Prompt Run does not exist for the project."""


class InvalidGraphCursorError(ValueError):
    """Raised when a continuation cursor is malformed, garbled, or foreign."""


class InvalidGraphFocusError(ValueError):
    """Execution 10, Section A (neighborhood expansion): raised when
    `focus_node` is malformed or does not name a real node already present
    in this Prompt Run's full graph — never silently ignored or treated as
    the root."""


def encode_cursor(offset: int, project: Identity, root: Identity) -> str:
    payload = json.dumps([CURSOR_FORMAT_VERSION, offset, project.canonical, root.canonical], separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def decode_cursor(token: str, project: Identity, root: Identity) -> int:
    """Decode and validate a continuation cursor against the bound project
    and root — a cursor minted elsewhere fails closed here rather than
    silently returning a confusing result."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or len(parsed) != 4:
            raise ValueError("cursor payload must be a 4-element array")
        format_version, offset, project_canonical, root_canonical = parsed
        if format_version != CURSOR_FORMAT_VERSION:
            raise ValueError(f"unsupported cursor format version: {format_version!r}")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("cursor offset must be a non-negative integer")
        if project_canonical != project.canonical:
            raise ValueError("cursor was minted for a different project")
        if root_canonical != root.canonical:
            raise ValueError("cursor was minted for a different root")
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise InvalidGraphCursorError(f"invalid continuation cursor: {exc}") from exc
    return offset


def _resolve_prompt_run(
    data_dir: Path, project_key: str, project: Identity, prompt_run_id: str, known_evidence: PromptRun | None,
) -> tuple[PromptRun, ClaimKind, str, Identity, projection_store.ProjectionCheckpoint]:
    """The one thing this bridge independently resolves from real evidence
    today: does this Prompt Run really exist, for this project. Everything
    else on `PromptRun` comes from `known_evidence` when a caller supplies
    it (mirroring `build_graph`'s own caller-supplied-evidence parameters —
    a future capture integration, or a test standing in for one), or stays
    an honest gap when it doesn't.

    `prompt_run_id` is the CANONICAL Prompt Run identity (e.g.
    ``mp:v1:prompt_run:<uuid>``) — the only Prompt Run identity Desktop's
    frontend ever has (`ActivityEvent.promptRunId`, itself already the
    output of `record_prompt_run`'s one-way hash). It is parsed directly via
    `Identity.parse`, never re-hashed through `deterministic_identity` —
    that would treat an already-canonical string as a fresh raw stable key
    and hash it a second time, producing a different identity that can
    never match anything in the projection. `PromptRun.prompt_run_id`
    itself must stay the raw STABLE key (`"{provider}:{provider_event_id}"`)
    since `build_graph` re-derives the node identity by hashing it — so the
    stable key is recovered from the resolved observation's own
    `provider`/`provider_event_id` fields, the same inputs `record_prompt_run`
    originally hashed to produce this exact canonical id.

    Ensures the projection reflects the real ledger before querying it
    (mirroring `desktop_bridge.prompt_run_activity`'s own O(1)-checkpoint
    catch-up) — never trusts a possibly-stale or never-built projection."""
    path = projection_store.projection_path(data_dir)
    ledger = open_project_ledger(data_dir / "evidence.jsonl", project_key)
    checkpoint = projection_store.update(ledger, path)
    try:
        root = Identity.parse(prompt_run_id)
    except ValueError as exc:
        raise PromptRunNotFoundError(f"'{prompt_run_id}' is not a valid Prompt Run identity: {exc}") from exc
    if root.kind is not EntityKind.PROMPT_RUN:
        raise PromptRunNotFoundError(f"'{prompt_run_id}' is not a Prompt Run identity")
    record = projection_store.get_observation(path, project, root.canonical)
    if record is None:
        raise PromptRunNotFoundError(f"no Prompt Run '{prompt_run_id}' found for project {project.canonical}")
    stable_key = f"{record.provider}:{record.provider_event_id}"
    source_claim_kind, source_layer = ClaimKind.OBSERVED, record.layer
    if known_evidence is not None:
        if known_evidence.prompt_run_id != stable_key:
            raise ValueError("known_evidence.prompt_run_id must match the resolved Prompt Run's stable key")
        return known_evidence, source_claim_kind, source_layer, root, checkpoint
    return PromptRun(stable_key, None, gaps=("unavailable:prompt_version",)), source_claim_kind, source_layer, root, checkpoint


def _build_citations(
    prompt_run: PromptRun, project: str, *,
    verification_evidence: Mapping[str, VerificationEvidence] | None,
    feedback_records: Mapping[str, FeedbackRecord] | None,
    outcome_evidence: Mapping[str, OutcomeReference] | None,
) -> tuple[tuple[EvidenceCitation, ...], tuple[str, ...]]:
    verification_evidence, feedback_records, outcome_evidence = verification_evidence or {}, feedback_records or {}, outcome_evidence or {}
    citations: list[EvidenceCitation] = []
    gaps: list[str] = []
    for verification_id in prompt_run.verification_ids:
        evidence = verification_evidence.get(verification_id)
        if evidence is None:
            gaps.append(f"unavailable:citation:{verification_id}")
            continue
        citations.append(verification_citation(evidence, project=project))
    for feedback_id in prompt_run.feedback_ids:
        record = feedback_records.get(feedback_id)
        if record is None:
            gaps.append(f"unavailable:citation:{feedback_id}")
            continue
        citations.append(feedback_citation(record, project=project))
    for outcome_id in prompt_run.outcome_references:
        reference = outcome_evidence.get(outcome_id)
        if reference is None:
            gaps.append(f"unavailable:citation:{outcome_id}")
            continue
        citations.append(outcome_citation(reference, project=project))
    return tuple(citations), tuple(gaps)


def _build_memory_lineage(
    memory_references: tuple[ExternalReference, ...],
) -> tuple[tuple[dict, ...], dict[Identity, VisualNodeMetadata]]:
    """Execution 09, Section B: the build-time-only lineage overlay for every
    cited Memory node in this graph. Pure parsing of each already-issued
    citation (`memory_temporal_lineage.pinned_state`) — never contacts
    Memory, so building a graph never gets slower or flakier because of
    this. A reference that isn't a recognizable Memory record citation is
    skipped here (its `cites_memory` edge and node still render from
    `build_graph` as before) rather than failing the whole graph build over
    one malformed lineage entry.

    Also produces the node metadata (`label`/`provenance`) every Memory
    citation node needs to be legible at all — before this, a cited Memory
    node's `VisualNode.label` fell back to its opaque hashed canonical
    identity, since `prompt_run_graph` never supplied metadata for the
    citation nodes `build_graph` creates from `memory_references`.
    """
    entries: list[dict] = []
    node_metadata: dict[Identity, VisualNodeMetadata] = {}
    for reference in memory_references:
        key = f"{reference.provider}:{reference.kind}:{reference.value}"
        node_id = deterministic_identity(EntityKind.MEMORY_RECORD, key)
        try:
            state: MemoryCitationState = pinned_state(reference)
        except MalformedMemoryRecordError:
            continue
        entries.append({"nodeId": node_id.canonical, **state.to_record()})
        node_metadata[node_id] = VisualNodeMetadata(
            label=f"memory:{state.record_id}#rev{state.pinned_revision}",
            provenance=(reference.value,),
        )
    return tuple(entries), node_metadata


def prompt_run_graph(
    data_dir: Path,
    project_key: str,
    prompt_run_id: str,
    *,
    known_evidence: PromptRun | None = None,
    tool_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    command_observation_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_session_ids: Mapping[str, tuple[str, ...]] | None = None,
    agent_turn_ids: Mapping[str, tuple[str, ...]] | None = None,
    memory_references: tuple[ExternalReference, ...] = (),
    verification_evidence: Mapping[str, VerificationEvidence] | None = None,
    feedback_records: Mapping[str, FeedbackRecord] | None = None,
    outcome_evidence: Mapping[str, OutcomeReference] | None = None,
    resolved_entities: Mapping[str, tuple[Identity | ResolvedRepositoryEntity, ...]] | None = None,
    entity_labels: Mapping[Identity, str] | None = None,
    max_depth: int | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_edges: int = DEFAULT_MAX_EDGES,
    allowed_layers: frozenset[str] | None = None,
    cursor: str | None = None,
    focus_node: str | None = None,
) -> dict[str, object]:
    """Return one versioned, bounded Desktop graph document for one real
    Prompt Run. Raises `PromptRunNotFoundError` if the identity doesn't
    exist for the project (an honest 404-shaped failure, not a fabricated
    empty graph); raises `InvalidGraphCursorError` for a malformed/foreign
    continuation token; raises `InvalidGraphFocusError` for a malformed
    `focus_node` or one naming a node absent from this graph.

    Execution 10, Section A (neighborhood expansion): `focus_node` (a
    canonical node identity already present somewhere in this Prompt Run's
    graph) EXPANDS the `maxDepth`-bounded view rather than re-centering it —
    the returned node set is the union of root's own reachability window and
    `focus_node`'s, so a client that already rendered a truncated view can
    ask "also show me what's around this node" without losing what it
    already had. Root always stays the Prompt Run itself (Section A: "root
    at one Prompt Run") — `focus_node` never changes `root`. Inert when
    `max_depth` is not supplied (nothing to expand against an unbounded
    view), but still validated either way — a bogus `focus_node` fails
    closed regardless of `max_depth`.

    Execution 08: `resolved_entities` (see `build_graph`) wires the real
    ChangeSet -> FileChange -> CodeRegion/Symbol hierarchy from
    `repository_entity_resolution.resolve_repository_entities`. Python-
    function-only, like every other caller-supplied-evidence parameter here
    — no CLI flag, no Host/IPC change, matching `known_evidence`/
    `verification_evidence`'s existing precedent exactly (Desktop must never
    become a second evidence owner). `entity_labels` is the accompanying
    optional display-only labels map that same resolver returns, threaded
    straight into `build_performance_visual_map`'s `node_labels`.
    """
    if max_nodes < 1 or max_edges < 1:
        raise ValueError("max_nodes and max_edges must be positive")
    if max_depth is not None and max_depth < 1:
        raise ValueError("max_depth must be positive when supplied")

    project = deterministic_identity(EntityKind.PROJECT, project_key)
    prompt_run, source_claim_kind, source_layer, root, checkpoint = _resolve_prompt_run(data_dir, project_key, project, prompt_run_id, known_evidence)

    graph = build_graph(
        prompt_run, tool_observation_ids=tool_observation_ids, command_observation_ids=command_observation_ids,
        agent_session_ids=agent_session_ids, agent_turn_ids=agent_turn_ids, memory_references=memory_references,
        resolved_entities=resolved_entities,
    )
    offset = decode_cursor(cursor, project, root) if cursor is not None else 0

    focus_identity: Identity | None = None
    if focus_node is not None:
        try:
            focus_identity = Identity.parse(focus_node)
        except ValueError as exc:
            raise InvalidGraphFocusError(f"'{focus_node}' is not a valid node identity: {exc}") from exc
        if focus_identity not in graph.nodes:
            raise InvalidGraphFocusError(f"'{focus_node}' is not part of this Prompt Run's graph")

    citations, citation_gaps = _build_citations(
        prompt_run, project.canonical, verification_evidence=verification_evidence, feedback_records=feedback_records, outcome_evidence=outcome_evidence,
    )
    graph = PerformanceGraph(graph.edges, graph.gaps + citation_gaps, graph.roots)

    memory_lineage, memory_node_metadata = _build_memory_lineage(memory_references)
    node_metadata = {
        root: VisualNodeMetadata(source_claim_kind=source_claim_kind, source_layer=source_layer),
        **memory_node_metadata,
    }
    visual_map = build_performance_visual_map(
        graph, project_context=project.canonical, node_metadata=node_metadata, node_labels=entity_labels,
    )

    # Section I bounds: maxDepth first (reachability from the root, unioned
    # with focus_node's own reachability window when supplied — Section A's
    # neighborhood expansion), then allowedLayers, then maxNodes/maxEdges
    # with an offset cursor over the deterministically sorted node order
    # build_performance_visual_map already produces. Edges beyond max_edges
    # are cut, never paginated separately — a deliberate V1 simplification
    # for what is meant to stay a small, single-Prompt-Run slice, not a
    # general graph browser. `truncation_reasons` (Execution 10, Section A:
    # "stable truncation reason") names WHICH bound(s) actually cut
    # something, in a fixed, machine-readable vocabulary — never inferred
    # after the fact from the booleans below.
    truncated = False
    truncation_reasons: list[str] = []
    allowed_ids = graph.nodes
    if max_depth is not None:
        reachable = frozenset(traverse(graph, root, direction="both", max_depth=max_depth)) | {root}
        if focus_identity is not None and focus_identity != root:
            reachable |= frozenset(traverse(graph, focus_identity, direction="both", max_depth=max_depth)) | {focus_identity}
        allowed_ids &= reachable
    nodes = tuple(node for node in visual_map.nodes if node.identity in allowed_ids)
    if allowed_layers is not None:
        before = len(nodes)
        nodes = tuple(node for node in nodes if node.layer in allowed_layers)
        if len(nodes) < before:
            truncated = True
            truncation_reasons.append("layer_filter")
    if max_depth is not None and len(allowed_ids) < len(graph.nodes):
        truncated = True
        truncation_reasons.append("max_depth")

    total_nodes = len(nodes)
    page_nodes = nodes[offset : offset + max_nodes]
    if offset + max_nodes < total_nodes:
        truncated = True
        truncation_reasons.append("max_nodes")
    page_node_ids = frozenset(node.identity for node in page_nodes)

    edges = tuple(edge for edge in visual_map.edges if edge.source in page_node_ids and edge.target in page_node_ids)
    if len(edges) > max_edges:
        edges = edges[:max_edges]
        truncated = True
        truncation_reasons.append("max_edges")

    next_cursor = encode_cursor(offset + max_nodes, project, root) if offset + max_nodes < total_nodes else None

    integrity_map = PerformanceVisualMap(visual_map.schema_version, visual_map.project_context, page_nodes, edges, visual_map.gaps)
    integrity = validate_graph_integrity(graph, integrity_map, project=project, root=root, truncated=truncated, mode=IntegrityMode.DIAGNOSTIC)

    document = {
        "version": GRAPH_BRIDGE_VERSION,
        "project": project.canonical,
        "root": root.canonical,
        "nodes": [dict(_node_record(node)) for node in page_nodes],
        "edges": [dict(_edge_record(edge)) for edge in edges],
        "citations": [
            {
                "reference_id": c.reference_id, "evidence_kind": c.evidence_kind, "project": c.project,
                "observed_at": c.observed_at.isoformat() if c.observed_at else None, "source": c.source,
                "detail_available": c.detail_available, "summary": c.summary,
            }
            for c in citations
        ],
        "memoryLineage": list(memory_lineage),
        "gaps": tuple(sorted(set(visual_map.gaps))),
        "truncated": truncated,
        "truncationReasons": tuple(dict.fromkeys(truncation_reasons)),
        "cursor": cursor,
        "nextCursor": next_cursor,
        "bounds": {
            "maxDepth": max_depth, "maxNodes": max_nodes, "maxEdges": max_edges,
            "allowedLayers": sorted(allowed_layers) if allowed_layers is not None else None,
            "focusNode": focus_identity.canonical if focus_identity is not None else None,
        },
        "projectionIdentity": {
            "project": project.canonical,
            "root": root.canonical,
            "graphSchemaVersion": GRAPH_BRIDGE_VERSION,
            "graphAlgorithmMethod": GRAPH_ALGORITHM_METHOD,
            "graphAlgorithmVersion": GRAPH_ALGORITHM_VERSION,
            "evidenceCheckpoint": checkpoint.generation,
        },
        "integrity": {
            "qualifies": integrity.qualifies,
            "findings": [
                {"kind": f.kind, "severity": f.severity.value, "subject_id": f.subject_id, "reference_id": f.reference_id, "evidence": list(f.evidence), "uncertainty": f.uncertainty}
                for f in integrity.findings
            ],
        },
    }
    document = _jsonify(document)
    validate_graph_prompt_run_response(document)
    return document


def _jsonify(value: object) -> object:
    """Normalize tuples (returned by `_node_record`/`_edge_record` and this
    module's own gap tuples) to plain lists before schema validation — the
    shared `contract_schema.validate` interpreter checks `isinstance(x,
    list)` strictly for `"type": "array"`, and `json.dump` itself doesn't
    need this (tuples already serialize as JSON arrays), but validation
    runs on the pre-serialization Python object."""
    if isinstance(value, (tuple, list)):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    return value


# Exit codes distinguishing an honest "not found"/"bad cursor" from a real
# crash — stdout stays reserved exclusively for the schema-validated success
# document (mirroring every other bridge in this package), so these failures
# are reported as JSON on STDERR instead, with a distinct exit code the
# Desktop Host can branch on without parsing stdout at all.
EXIT_NOT_FOUND = 2
EXIT_INVALID_CURSOR = 3
EXIT_INVALID_REQUEST = 4
EXIT_INVALID_FOCUS = 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only versioned Desktop graph document for one Prompt Run (stdout JSON).",
    )
    parser.add_argument("--data-dir", type=Path, required=True, help="project ledger/projection directory")
    parser.add_argument("--project", default="midnight", help="local project key (deterministic identity input)")
    parser.add_argument("--prompt-run-id", required=True, help="the Prompt Run's canonical identity (e.g. mp:v1:prompt_run:<uuid>)")
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    parser.add_argument("--max-edges", type=int, default=DEFAULT_MAX_EDGES)
    parser.add_argument("--layers", default=None, help="comma-separated allowed layer names")
    parser.add_argument("--cursor", default=None)
    parser.add_argument("--focus-node", default=None, help="canonical node identity to expand the maxDepth window around")
    args = parser.parse_args(argv)
    allowed_layers = frozenset(args.layers.split(",")) if args.layers else None
    try:
        document = prompt_run_graph(
            args.data_dir, args.project, args.prompt_run_id,
            max_depth=args.max_depth, max_nodes=args.max_nodes, max_edges=args.max_edges,
            allowed_layers=allowed_layers, cursor=args.cursor, focus_node=args.focus_node,
        )
    except PromptRunNotFoundError as exc:
        json.dump({"error": "not_found", "message": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return EXIT_NOT_FOUND
    except InvalidGraphCursorError as exc:
        json.dump({"error": "invalid_cursor", "message": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return EXIT_INVALID_CURSOR
    except InvalidGraphFocusError as exc:
        json.dump({"error": "invalid_focus", "message": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return EXIT_INVALID_FOCUS
    except ValueError as exc:
        json.dump({"error": "invalid_request", "message": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return EXIT_INVALID_REQUEST
    json.dump(document, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
