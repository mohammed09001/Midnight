"""Rebuildable fine-grained requirement-to-code trace projections.

Raw prompts and repository snapshots remain authoritative elsewhere.  This
module only derives versioned units, candidates, and link lifecycle records.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import re
from .contracts import ClaimKind
from .intent_contract import IntentContract, IntentKind, SourceSpan

TRACEABILITY_VERSION = "1"
PARSER_VERSION = "python-ast-1"

class CodeElementKind(str, Enum): MODULE="module"; CLASS="class"; FUNCTION="function"; METHOD="method"; UNKNOWN="unknown"
class TraceState(str, Enum): CANDIDATE="candidate"; SUPPORTED="supported"; CONTRADICTED="contradicted"; STALE="stale"; SUPERSEDED="superseded"; INSUFFICIENT_EVIDENCE="insufficient_evidence"

@dataclass(frozen=True, slots=True)
class RequirementUnit:
    id: str; prompt_run_id: str; intent_element_id: str; intent_kind: IntentKind
    span: SourceSpan; parent_id: str | None; sibling_ids: tuple[str, ...]
    dependencies: tuple[str, ...]; analysis_version: str; source_reference: str

@dataclass(frozen=True, slots=True)
class CodeElement:
    id: str; path: str; qualified_name: str; kind: CodeElementKind
    start_line: int | None; end_line: int | None; parser: str; parser_version: str
    source_available: bool; uncertainty: str = "derived structural projection; source snapshot remains authoritative"

@dataclass(frozen=True, slots=True)
class TraceCandidate:
    requirement_id: str; code_element_id: str; score: float; evidence: tuple[str, ...]
    method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str
    def __post_init__(self):
        if not 0 <= self.score <= 1: raise ValueError("candidate score must be between zero and one")

@dataclass(frozen=True, slots=True)
class TraceLink:
    requirement_id: str | None; code_element_id: str; state: TraceState; analysis_version: str
    evidence: tuple[str, ...]; candidate_score: float | None; method: str; method_version: str
    claim_kind: ClaimKind; uncertainty: str; previous_version_id: str | None = None
    def __post_init__(self):
        if self.state is TraceState.SUPPORTED and not self.evidence:
            raise ValueError("supported traces require concrete non-similarity evidence")
        if self.state is TraceState.SUPPORTED and self.claim_kind is not ClaimKind.DERIVED:
            raise ValueError("supported trace is a qualified derived conclusion")
        if self.state is TraceState.CANDIDATE and self.claim_kind is not ClaimKind.INFERRED:
            raise ValueError("candidate trace must remain inferred")
        if self.requirement_id is None and self.state is not TraceState.INSUFFICIENT_EVIDENCE:
            raise ValueError("only insufficient-evidence links may lack a requirement")

def _stable(prefix: str, *parts: str) -> str:
    return f"{prefix}:{sha256('|'.join(parts).encode()).hexdigest()[:24]}"

def build_requirement_units(prompt_run_id: str, contract: IntentContract, *, analysis_version: str = TRACEABILITY_VERSION, source_reference: str | None = None) -> tuple[RequirementUnit, ...]:
    if not prompt_run_id.strip(): raise ValueError("prompt run id is required")
    source_reference = source_reference or f"prompt-run:{prompt_run_id}:intent:{contract.version}"
    ids = {item.id: _stable("requirement", prompt_run_id, contract.version, item.id) for item in contract.elements}
    units = []
    for item in contract.elements:
        siblings = tuple(ids[other.id] for other in contract.elements if other.parent_id == item.parent_id and other.id != item.id)
        units.append(RequirementUnit(ids[item.id], prompt_run_id, item.id, item.kind, item.span, ids.get(item.parent_id), siblings, tuple(ids[item_id] for item_id in item.dependencies), analysis_version, source_reference))
    return tuple(units)

def resolve_code_elements(path: str, source: str | None, *, source_permitted: bool = True) -> tuple[CodeElement, ...]:
    """Use stdlib AST only for Python source; all other cases are explicit gaps."""
    if not source_permitted or source is None:
        return (CodeElement(_stable("code", path, "unavailable"), path, path, CodeElementKind.UNKNOWN, None, None, "none", "1", False, "source unavailable or denied by policy"),)
    if not path.endswith(".py"):
        return (CodeElement(_stable("code", path, "unsupported"), path, path, CodeElementKind.UNKNOWN, None, None, "none", "1", True, "unsupported language; no structural symbol resolution"),)
    try: tree = ast.parse(source)
    except SyntaxError:
        return (CodeElement(_stable("code", path, "syntax-error"), path, path, CodeElementKind.UNKNOWN, None, None, "python-ast", PARSER_VERSION, True, "Python source could not be parsed"),)
    elements: list[CodeElement] = []
    def walk(nodes, parent: str | None = None):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{parent}.{node.name}" if parent else node.name
                kind = CodeElementKind.CLASS if isinstance(node, ast.ClassDef) else (CodeElementKind.METHOD if parent else CodeElementKind.FUNCTION)
                elements.append(CodeElement(_stable("code", path, name), path, name, kind, node.lineno, getattr(node, "end_lineno", node.lineno), "python-ast", PARSER_VERSION, True))
                walk(node.body, name)
    walk(tree.body)
    return tuple(elements) or (CodeElement(_stable("code", path, "module"), path, path, CodeElementKind.MODULE, 1, len(source.splitlines()), "python-ast", PARSER_VERSION, True, "module has no class or function symbols"),)

def _tokens(value: str) -> set[str]: return {x for x in re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", value.lower().replace("_", " ")) if x not in {"the", "and", "with", "that", "this", "must", "should"}}
def retrieve_candidates(units: tuple[RequirementUnit, ...], contract: IntentContract, elements: tuple[CodeElement, ...], *, limit: int = 10) -> tuple[TraceCandidate, ...]:
    if limit < 1: raise ValueError("candidate limit must be positive")
    text = {item.id: item.text for item in contract.elements}; result=[]
    by_intent = {unit.intent_element_id: unit for unit in units}
    for element in elements:
        if element.kind is CodeElementKind.UNKNOWN: continue
        code_tokens = _tokens(f"{element.path} {element.qualified_name}")
        for intent_id, requirement in by_intent.items():
            overlap = _tokens(text[intent_id]) & code_tokens
            if overlap:
                score=round(len(overlap)/max(1, len(_tokens(text[intent_id]))), 3)
                result.append(TraceCandidate(requirement.id, element.id, score, tuple(sorted(f"identifier:{word}" for word in overlap)), "identifier-structure-retrieval", TRACEABILITY_VERSION, ClaimKind.INFERRED, "candidate only; identifier overlap is not trace truth"))
    return tuple(sorted(result, key=lambda item: (-item.score, item.code_element_id, item.requirement_id))[:limit])

def link_from_candidate(candidate: TraceCandidate, *, support_evidence: tuple[str, ...] = (), contradictory_evidence: tuple[str, ...] = (), analysis_version: str = TRACEABILITY_VERSION, previous_version_id: str | None = None) -> TraceLink:
    if contradictory_evidence:
        return TraceLink(candidate.requirement_id, candidate.code_element_id, TraceState.CONTRADICTED, analysis_version, contradictory_evidence, candidate.score, "trace-lifecycle", TRACEABILITY_VERSION, ClaimKind.DERIVED, "concrete evidence contradicts candidate", previous_version_id)
    if support_evidence:
        return TraceLink(candidate.requirement_id, candidate.code_element_id, TraceState.SUPPORTED, analysis_version, support_evidence, candidate.score, "trace-lifecycle", TRACEABILITY_VERSION, ClaimKind.DERIVED, "support evidence is linked but does not prove full behavioural satisfaction", previous_version_id)
    return TraceLink(candidate.requirement_id, candidate.code_element_id, TraceState.CANDIDATE, analysis_version, candidate.evidence, candidate.score, "trace-lifecycle", TRACEABILITY_VERSION, ClaimKind.INFERRED, candidate.uncertainty, previous_version_id)

def reprocess_links(links: tuple[TraceLink, ...], *, live_code_element_ids: frozenset[str], analysis_version: str, moved_elements: dict[str, str] | None = None) -> tuple[TraceLink, ...]:
    """Create new records; old link versions are never rewritten."""
    moved_elements = moved_elements or {}; result=[]
    for index, link in enumerate(links):
        element_id = moved_elements.get(link.code_element_id, link.code_element_id)
        state = link.state if element_id in live_code_element_ids else TraceState.STALE
        if link.code_element_id in moved_elements:
            reason = "caller-supplied structural move/rename evidence retained code-element continuity"
        else:
            reason = link.uncertainty if state is link.state else "referenced code element is absent in the reprocessed structural projection"
        result.append(TraceLink(link.requirement_id, element_id, state, analysis_version, link.evidence, link.candidate_score, link.method, link.method_version, link.claim_kind if state is not TraceState.STALE else ClaimKind.DERIVED, reason, f"link-{index + 1}"))
    return tuple(result)

def unrequested_code_links(elements: tuple[CodeElement, ...], links: tuple[TraceLink, ...]) -> tuple[TraceLink, ...]:
    linked={link.code_element_id for link in links if link.requirement_id is not None}
    return tuple(TraceLink(None, element.id, TraceState.INSUFFICIENT_EVIDENCE, TRACEABILITY_VERSION, (), None, "trace-lifecycle", TRACEABILITY_VERSION, ClaimKind.UNKNOWN, "changed code has no requirement trace evidence") for element in elements if element.id not in linked)
