"""Execution 08, Section D: the pluggable structural-resolver contract.

A standalone, language-agnostic shape any structural resolver (today: the
Python stdlib-AST resolver in `repository_entity_resolution.py`; potentially
in the future: a qualified Tree-sitter-backed resolver, see that module's
docstring for why Tree-sitter does not qualify for THIS execution) declares
itself against. This module has zero language-specific logic and zero
dependencies beyond the stdlib — it is a contract, not an implementation.

Deliberately a richer, standalone sibling to `parser_adapter.ParserDescriptor`
(which stays exactly as it is, still serving `traceability.py`) rather than
an extension of it: Section D asks for materially more disclosure (a named
resource budget, an explicit identity strategy, a required uncertainty
statement) than that minimal existing shape carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

STRUCTURAL_RESOLVER_CONTRACT_VERSION = "1"


class ResolverCapability(str, Enum):
    STRUCTURE = "structure"
    SYMBOLS = "symbols"
    REGIONS = "regions"


class IdentityStrategy(str, Enum):
    """How a resolver's produced identities are made replay-stable — always
    fed into `deterministic_identity`, never a second identity scheme."""

    REPOSITORY_FILE = "repository_file"
    REPOSITORY_FILE_LINE_RANGE = "repository_file_line_range"
    REPOSITORY_FILE_QUALIFIED_SYMBOL = "repository_file_qualified_symbol"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ResolverDescriptor:
    """One resolver's self-declared capability envelope for one language.

    `gap`/`uncertainty` are deliberately separate disclosures: `gap` explains
    WHY a resolver is unsupported (or, for a supported resolver, stays
    `None`); `uncertainty` is always present and explains what the resolver's
    OUTPUT actually claims to be (e.g. "line-based diff evidence, not
    structural/symbol parsing") — so a caller can tell "nothing was
    attempted" apart from "something was attempted, here's its honest
    ceiling," even for a `supported=True` resolver.
    """

    language: str
    tool: str
    tool_version: str
    capabilities: frozenset[ResolverCapability]
    max_bytes: int
    identity_strategy: IdentityStrategy
    supported: bool
    gap: str | None
    uncertainty: str

    def __post_init__(self) -> None:
        if not self.language.strip() or not self.tool.strip() or not self.tool_version.strip():
            raise ValueError("resolver descriptors require language, tool, and tool_version")
        if self.max_bytes < 1:
            raise ValueError("resolver descriptors require a positive max_bytes budget")
        if not self.uncertainty.strip():
            raise ValueError("resolver descriptors require an uncertainty disclosure")
        if self.supported and self.identity_strategy is IdentityStrategy.NONE:
            raise ValueError("a supported resolver must declare a real identity strategy")
        if not self.supported and self.gap is None:
            raise ValueError("an unsupported resolver must disclose why via `gap`")
