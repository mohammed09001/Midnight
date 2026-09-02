"""Bounded parser adapter boundary; Python AST is the sole bundled parser."""
from __future__ import annotations
import ast
from dataclasses import dataclass
from enum import Enum
PARSER_ADAPTER_VERSION="1"; MAX_SOURCE_BYTES=1_000_000
class ParserCapability(str,Enum): STRUCTURE="structure"; SYMBOLS="symbols"
@dataclass(frozen=True,slots=True)
class ParserDescriptor:
    language:str; tool:str; version:str; capabilities:frozenset[ParserCapability]; supported:bool
@dataclass(frozen=True,slots=True)
class ParseResult:
    descriptor:ParserDescriptor; tree:ast.AST|None; gap:str|None
PYTHON_PARSER=ParserDescriptor("python","stdlib-ast","1",frozenset({ParserCapability.STRUCTURE,ParserCapability.SYMBOLS}),True)
NO_PARSER=ParserDescriptor("unknown","none","1",frozenset(),False)
def parse_source(path:str, source:str|None, *, maximum_bytes:int=MAX_SOURCE_BYTES)->ParseResult:
    if source is None: return ParseResult(NO_PARSER,None,"source unavailable or denied")
    if len(source.encode())>maximum_bytes: return ParseResult(PYTHON_PARSER if path.endswith('.py') else NO_PARSER,None,"source exceeds parser resource bound")
    if not path.endswith('.py'): return ParseResult(ParserDescriptor(path.rsplit('.',1)[-1] if '.' in path else "unknown","none","1",frozenset(),False),None,"unsupported language; no parser installed")
    try: return ParseResult(PYTHON_PARSER,ast.parse(source),None)
    except SyntaxError: return ParseResult(PYTHON_PARSER,None,"python source could not be parsed")
