"""Caching for external research: four distinct, never-conflated semantics.

- Content-addressed: exact digest match, always safe to reuse.
- Normalized-source: keyed by locator, freshness/ETag-aware, still exact.
- Search-result: short-TTL reuse of an identical query within one run.
- Semantic reuse: similarity-based, and REJECTED whenever entity, version, or
  time scope differ — semantic similarity is never treated as equivalence.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .ports import DiscoveredSource, FetchedDocument
from .sources import SourceClass

DEFAULT_SEARCH_CACHE_TTL = timedelta(minutes=5)
DEFAULT_NORMALIZED_CACHE_MAX_AGE = timedelta(hours=24)


class ContentAddressedCache:
    """digest -> FetchedDocument, exact match only, bounded LRU size."""

    def __init__(self, *, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("content-addressed cache requires a positive max_entries")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, FetchedDocument] = OrderedDict()

    def get(self, content_digest: str) -> FetchedDocument | None:
        document = self._entries.get(content_digest)
        if document is not None:
            self._entries.move_to_end(content_digest)
        return document

    def put(self, document: FetchedDocument) -> None:
        digest = document.text.content_digest
        self._entries[digest] = document
        self._entries.move_to_end(digest)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


@dataclass(frozen=True, slots=True)
class NormalizedCacheEntry:
    etag: str | None
    content_digest: str
    fetched_at: datetime
    normalized_text: str


class NormalizedSourceCache:
    """canonical_locator -> NormalizedCacheEntry, freshness-checked by age."""

    def __init__(self, *, max_age: timedelta = DEFAULT_NORMALIZED_CACHE_MAX_AGE, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("normalized-source cache requires a positive max_entries")
        self._max_age = max_age
        self._max_entries = max_entries
        self._entries: OrderedDict[str, NormalizedCacheEntry] = OrderedDict()

    def get(self, locator: str) -> NormalizedCacheEntry | None:
        entry = self._entries.get(locator)
        if entry is not None:
            self._entries.move_to_end(locator)
        return entry

    def is_fresh(self, entry: NormalizedCacheEntry, *, now: datetime) -> bool:
        return now - entry.fetched_at <= self._max_age

    def put(self, locator: str, entry: NormalizedCacheEntry) -> None:
        self._entries[locator] = entry
        self._entries.move_to_end(locator)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


@dataclass(frozen=True, slots=True)
class CachedSearchResult:
    hits: tuple[DiscoveredSource, ...]
    cached_at: datetime


class SearchResultCache:
    """(query, source_classes) -> CachedSearchResult, short TTL."""

    def __init__(self, *, ttl: timedelta = DEFAULT_SEARCH_CACHE_TTL, max_entries: int = 128) -> None:
        if max_entries < 1:
            raise ValueError("search-result cache requires a positive max_entries")
        self._ttl = ttl
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[str, tuple[SourceClass, ...]], CachedSearchResult] = OrderedDict()

    @staticmethod
    def _key(query: str, source_classes: tuple[SourceClass, ...]) -> tuple[str, tuple[SourceClass, ...]]:
        return (" ".join(query.split()).lower(), tuple(sorted(source_classes, key=lambda c: c.value)))

    def get(self, query: str, source_classes: tuple[SourceClass, ...], *, now: datetime) -> tuple[DiscoveredSource, ...] | None:
        key = self._key(query, source_classes)
        cached = self._entries.get(key)
        if cached is None:
            return None
        if now - cached.cached_at > self._ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return cached.hits

    def put(self, query: str, source_classes: tuple[SourceClass, ...], hits: tuple[DiscoveredSource, ...], *, now: datetime) -> None:
        key = self._key(query, source_classes)
        self._entries[key] = CachedSearchResult(hits=hits, cached_at=now)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


@dataclass(frozen=True, slots=True)
class SemanticReuseCandidate:
    """A past fetch offered as a candidate for reuse by a NEW, similar query.

    Never a claim of equivalence by itself — `resolve_semantic_reuse` still
    enforces the entity/time-scope check before returning it.
    """

    concept: str
    entity: str
    captured_at: datetime
    document: FetchedDocument


def _token_overlap(a: str, b: str) -> float:
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def resolve_semantic_reuse(
    candidate: SemanticReuseCandidate,
    *,
    requested_concept: str,
    requested_entity: str,
    requested_time_scope: tuple[datetime, datetime] | None,
    minimum_similarity: float = 0.5,
) -> FetchedDocument | None:
    """Return the candidate's document only when it is a SAFE reuse.

    Rejects on entity mismatch or a capture time outside the requested
    scope even when the concept text is near-identical — similarity is a
    necessary, never sufficient, condition for reuse.
    """
    if candidate.entity != requested_entity:
        return None
    if requested_time_scope is not None:
        start, end = requested_time_scope
        if not (start <= candidate.captured_at <= end):
            return None
    if _token_overlap(candidate.concept, requested_concept) < minimum_similarity:
        return None
    return candidate.document


__all__ = [
    "CachedSearchResult",
    "ContentAddressedCache",
    "NormalizedCacheEntry",
    "NormalizedSourceCache",
    "SearchResultCache",
    "SemanticReuseCandidate",
    "resolve_semantic_reuse",
]
