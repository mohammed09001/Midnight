"""Dependency-free, syntax-aware structural change projection for Python."""
from __future__ import annotations
import ast
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from .contracts import ClaimKind

STRUCTURAL_DIFF_VERSION = "1"
class StructuralEditKind(str, Enum): INSERT="insert"; DELETE="delete"; UPDATE="update"; MOVE="move"; RENAME="rename"; UNRESOLVED="unresolved"
class SurfaceKind(str, Enum): SOURCE="source"; TEST="test"; CONFIG="config"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class StructuralElement:
    id: str; path: str; name: str; kind: str; start_line: int | None; end_line: int | None; body_digest: str | None; parser: str; parser_version: str; uncertainty: str
@dataclass(frozen=True, slots=True)
class StructuralEdit:
    kind: StructuralEditKind; before: StructuralElement | None; after: StructuralElement | None; raw_evidence: tuple[str, ...]; confidence: float; parser: str; parser_version: str; claim_kind: ClaimKind; uncertainty: str
    def __post_init__(self):
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between zero and one")
@dataclass(frozen=True, slots=True)
class StructuralDiff:
    path: str; edits: tuple[StructuralEdit, ...]; raw_evidence: tuple[str, ...]; parser: str; parser_version: str; supported: bool
@dataclass(frozen=True, slots=True)
class ChangedSurface:
    element: StructuralElement | None; edit: StructuralEdit; surface: SurfaceKind; raw_evidence: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class BlastRadius:
    files: tuple[str, ...]; directories: tuple[str, ...]; symbols: tuple[str, ...]; neighborhoods: tuple[str, ...]; uncertainty: str

def _id(path: str, name: str, kind: str) -> str: return "symbol:" + sha256(f"{path}|{name}|{kind}".encode()).hexdigest()[:20]
def _parse(path: str, source: str | None) -> tuple[StructuralElement, ...]:
    if source is None or not path.endswith(".py"): return ()
    try: tree=ast.parse(source)
    except SyntaxError: return ()
    result=[]
    def visit(nodes, parent=""):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name=f"{parent}.{node.name}" if parent else node.name; kind="class" if isinstance(node, ast.ClassDef) else ("method" if parent else "function")
                # The body digest deliberately excludes the declaration name and
                # source locations so rename/move continuity is qualified by body
                # structure rather than string similarity.
                digest=sha256(ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False).encode()).hexdigest()
                result.append(StructuralElement(_id(path,name,kind),path,name,kind,node.lineno,getattr(node,"end_lineno",node.lineno),digest,"python-ast",STRUCTURAL_DIFF_VERSION,"structural projection, not raw diff truth")); visit(node.body,name)
    visit(tree.body); return tuple(result)
def structural_diff(path: str, before: str | None, after: str | None, *, raw_evidence: tuple[str, ...] = ()) -> StructuralDiff:
    old,new=_parse(path,before),_parse(path,after)
    if not path.endswith(".py") or (before is not None and not old and after is not None and not new):
        edit=StructuralEdit(StructuralEditKind.UNRESOLVED,None,None,raw_evidence,0,"none","1",ClaimKind.UNKNOWN,"unsupported language or parser failure; raw change remains authoritative")
        return StructuralDiff(path,(edit,),raw_evidence,"none","1",False)
    edits=[]; old_by={x.name:x for x in old}; new_by={x.name:x for x in new}; matched=set()
    for name in sorted(old_by.keys() & new_by.keys()):
        left,right=old_by[name],new_by[name]; matched|={left.id,right.id}
        if left.body_digest != right.body_digest: edits.append(StructuralEdit(StructuralEditKind.UPDATE,left,right,raw_evidence,.9,"python-ast",STRUCTURAL_DIFF_VERSION,ClaimKind.DERIVED,"AST body differs"))
        elif left.start_line != right.start_line: edits.append(StructuralEdit(StructuralEditKind.MOVE,left,right,raw_evidence,.8,"python-ast",STRUCTURAL_DIFF_VERSION,ClaimKind.DERIVED,"same named structural element moved within module"))
    remaining_old=[x for x in old if x.id not in matched]; remaining_new=[x for x in new if x.id not in matched]
    for left in tuple(remaining_old):
        same=next((right for right in remaining_new if right.body_digest==left.body_digest and right.kind==left.kind),None)
        if same:
            kind=StructuralEditKind.RENAME if left.path==same.path else StructuralEditKind.MOVE
            edits.append(StructuralEdit(kind,left,same,raw_evidence,.75,"python-ast",STRUCTURAL_DIFF_VERSION,ClaimKind.DERIVED,"body-digest continuity suggests rename/move; not source-control rename proof")); remaining_old.remove(left); remaining_new.remove(same)
    edits.extend(StructuralEdit(StructuralEditKind.DELETE,item,None,raw_evidence,.95,"python-ast",STRUCTURAL_DIFF_VERSION,ClaimKind.DERIVED,"element absent from after AST") for item in remaining_old)
    edits.extend(StructuralEdit(StructuralEditKind.INSERT,None,item,raw_evidence,.95,"python-ast",STRUCTURAL_DIFF_VERSION,ClaimKind.DERIVED,"element absent from before AST") for item in remaining_new)
    return StructuralDiff(path,tuple(edits),raw_evidence,"python-ast",STRUCTURAL_DIFF_VERSION,True)
def changed_surfaces(diff: StructuralDiff) -> tuple[ChangedSurface, ...]:
    surface=SurfaceKind.TEST if "/test" in diff.path or diff.path.startswith("tests/") else SurfaceKind.CONFIG if diff.path.endswith((".toml",".json",".yaml",".yml")) else SurfaceKind.SOURCE if diff.supported else SurfaceKind.UNKNOWN
    return tuple(ChangedSurface(edit.after or edit.before,edit,surface,diff.raw_evidence) for edit in diff.edits)
def blast_radius(surfaces: tuple[ChangedSurface, ...], *, neighborhoods: tuple[str, ...] = ()) -> BlastRadius:
    files=tuple(sorted({item.element.path for item in surfaces if item.element})); directories=tuple(sorted({path.rsplit("/",1)[0] if "/" in path else "" for path in files})); symbols=tuple(sorted({item.element.id for item in surfaces if item.element}))
    return BlastRadius(files,directories,symbols,tuple(sorted(set(neighborhoods))),"structural scope only; callers must supply relationship neighborhoods")
