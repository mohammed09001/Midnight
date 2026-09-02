"""Deterministic, provenance-preserving intent contracts for prompt runs."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import re
from .contracts import ClaimKind

INTENT_CONTRACT_VERSION = "2"

class IntentKind(str, Enum):
    GOAL = "goal"
    CONSTRAINT = "constraint"
    ACCEPTANCE = "acceptance"
    VERIFICATION = "verification"
    REFERENCE = "reference"
    IMPLEMENTATION_SUGGESTION = "implementation_suggestion"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: int
    end: int
    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start: raise ValueError("invalid source span")

@dataclass(frozen=True, slots=True)
class IntentElement:
    id: str
    text: str
    span: SourceSpan
    kind: IntentKind
    claim_kind: ClaimKind = ClaimKind.OBSERVED
    parent_id: str | None = None
    dependencies: tuple[str, ...] = ()
    uncertainty: str = "explicit text extraction"

@dataclass(frozen=True, slots=True)
class IntentContract:
    version: str
    source_text: str
    elements: tuple[IntentElement, ...]
    extractor: str = "deterministic-structure"
    extractor_version: str = INTENT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        ids = {item.id for item in self.elements}
        if len(ids) != len(self.elements): raise ValueError("intent element ids must be unique")
        for item in self.elements:
            if item.span.end > len(self.source_text) or self.source_text[item.span.start:item.span.end] != item.text:
                raise ValueError("intent element span must point to exact source text")
            if item.parent_id and item.parent_id not in ids: raise ValueError("intent parent must exist")
            if any(dep not in ids for dep in item.dependencies): raise ValueError("intent dependency must exist")

_SEGMENTS = re.compile(r"(?m)^[ \t]*(?:[-*+] |\d+[.)] )?[^\n]+")
def _kind(text: str) -> IntentKind:
    low = text.lower()
    if any(x in low for x in ("http://", "https://", "see ", "reference")): return IntentKind.REFERENCE
    if any(x in low for x in ("acceptance", "done when", "success criteria", "must pass")): return IntentKind.ACCEPTANCE
    if any(x in low for x in ("do not", "must not", "avoid", "never ", "shall not", "must ")): return IntentKind.CONSTRAINT
    if any(x in low for x in ("test", "verify", "validate", "check")): return IntentKind.VERIFICATION
    if any(x in low for x in ("use ", "implement with", "using ")): return IntentKind.IMPLEMENTATION_SUGGESTION
    return IntentKind.GOAL

def extract_intent_contract(text: str) -> IntentContract:
    elements: list[IntentElement] = []
    stack: list[tuple[int, str]] = []
    for match in _SEGMENTS.finditer(text):
        raw = match.group(0); leading = len(raw) - len(raw.lstrip(" \t")); start = match.start() + leading
        item_text = text[start:match.end()]
        # Keep raw source exactly; bullets are evidence too, but nesting applies to their content.
        # `raw` begins after the regex's indentation prefix; derive hierarchy
        # from the original source instead of the matched fragment.
        indent = len(text[match.start():start].replace("\t", "    "))
        while stack and stack[-1][0] >= indent: stack.pop()
        item_id = f"intent-{len(elements) + 1}"
        parent = stack[-1][1] if stack else None
        elements.append(IntentElement(item_id, item_text, SourceSpan(start, match.end()), _kind(item_text), parent_id=parent))
        stack.append((indent, item_id))
    return IntentContract(INTENT_CONTRACT_VERSION, text, tuple(elements))
