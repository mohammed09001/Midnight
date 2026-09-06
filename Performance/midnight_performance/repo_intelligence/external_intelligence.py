"""Vendor-neutral external-intelligence capability functions.

`search`/`fetch` are already provider-neutral ports (`ports.py`); this module
adds the two capabilities the spec requires that are the same regardless of
which adapter produced the fetched bytes: `normalize_external` and
`verify_external`. Real, network-calling adapters (e.g. the GitHub search +
fetch adapter) live in `repo_intelligence_adapters.py`, not here — this
package never imports network/DB libraries directly (enforced by
`test_repo_intelligence_architecture.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..privacy import redact_sensitive_text
from .ports import FetchedDocument
from .sources import SourceClass


@dataclass(frozen=True, slots=True)
class NormalizedSource:
    """A fetched document reduced to cache-friendly, comparison-ready text.

    Content is unchanged (digest matches the original fetch) — normalization
    only collapses whitespace and redacts anything `redact_sensitive_text`
    would strip from an outbound query, applied here defensively to inbound
    content too, before it can appear in any exposed statement.
    """

    source_class: SourceClass
    provider: str
    locator: str
    title: str
    normalized_text: str
    content_digest: str


def normalize_external(document: FetchedDocument, *, provider: str, locator: str, title: str) -> NormalizedSource:
    collapsed = " ".join(document.text.content.split())
    return NormalizedSource(
        source_class=document.text.source_class,
        provider=provider,
        locator=locator,
        title=title,
        normalized_text=redact_sensitive_text(collapsed),
        content_digest=document.text.content_digest,
    )


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verified: bool
    overlap: float
    reason: str


def verify_external(normalized: NormalizedSource, concept: str, *, minimum_overlap: float = 0.15) -> VerificationResult:
    """Deterministic token-overlap check: does the fetched content actually
    relate to the question's concept? No ML — a cheap, honest relevance gate
    so an off-topic fetch never silently strengthens an unrelated insight."""
    concept_tokens = set(concept.lower().split())
    text_tokens = set(normalized.normalized_text.lower().split())
    if not concept_tokens or not text_tokens:
        return VerificationResult(verified=False, overlap=0.0, reason="concept or fetched text has no tokens to compare")
    overlap = len(concept_tokens & text_tokens) / len(concept_tokens)
    if overlap < minimum_overlap:
        return VerificationResult(
            verified=False, overlap=overlap,
            reason=f"fetched content overlap {overlap:.2f} is below the {minimum_overlap:.2f} relevance floor",
        )
    return VerificationResult(verified=True, overlap=overlap, reason="fetched content overlaps the question's concept")


__all__ = [
    "NormalizedSource",
    "VerificationResult",
    "normalize_external",
    "verify_external",
]
