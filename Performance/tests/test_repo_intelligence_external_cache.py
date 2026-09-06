"""External research caching: four distinct semantics, never conflated."""

import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.contracts import ExternalSourceRef, external_source_ref_identity
from midnight_performance.repo_intelligence.external_cache import (
    ContentAddressedCache,
    NormalizedCacheEntry,
    NormalizedSourceCache,
    SearchResultCache,
    SemanticReuseCandidate,
    resolve_semantic_reuse,
)
from midnight_performance.repo_intelligence.ports import DiscoveredSource, FetchedDocument, UntrustedText
from midnight_performance.repo_intelligence.sources import SourceClass

PROJECT = deterministic_identity(EntityKind.PROJECT, "cache-alpha")
T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _document(body: str = "content") -> FetchedDocument:
    digest = hashlib.sha256(body.encode()).hexdigest()
    ref = ExternalSourceRef(
        identity=external_source_ref_identity("fixture", "https://example.com/x", digest),
        project=PROJECT, source_class=SourceClass.WEB, provider="fixture",
        locator="https://example.com/x", title="x", content_digest=digest,
        captured_at=T0, retrieval_method="fixture", retrieval_version="1",
    )
    return FetchedDocument(ref, UntrustedText(body, digest, SourceClass.WEB))


class ContentAddressedCacheTests(unittest.TestCase):
    def test_exact_digest_hit_and_miss(self):
        cache = ContentAddressedCache()
        document = _document()
        self.assertIsNone(cache.get(document.text.content_digest))
        cache.put(document)
        self.assertIs(cache.get(document.text.content_digest), document)

    def test_lru_eviction_bounded_by_max_entries(self):
        cache = ContentAddressedCache(max_entries=2)
        docs = [_document(f"body-{i}") for i in range(3)]
        for doc in docs:
            cache.put(doc)
        self.assertIsNone(cache.get(docs[0].text.content_digest))
        self.assertIsNotNone(cache.get(docs[1].text.content_digest))
        self.assertIsNotNone(cache.get(docs[2].text.content_digest))


class NormalizedSourceCacheTests(unittest.TestCase):
    def test_freshness_check_by_age(self):
        cache = NormalizedSourceCache(max_age=timedelta(hours=1))
        entry = NormalizedCacheEntry(etag="abc", content_digest="d" * 64, fetched_at=T0, normalized_text="hi")
        cache.put("locator", entry)
        self.assertTrue(cache.is_fresh(entry, now=T0 + timedelta(minutes=30)))
        self.assertFalse(cache.is_fresh(entry, now=T0 + timedelta(hours=2)))

    def test_get_returns_none_for_unknown_locator(self):
        cache = NormalizedSourceCache()
        self.assertIsNone(cache.get("never-fetched"))


class SearchResultCacheTests(unittest.TestCase):
    def test_ttl_expiry(self):
        cache = SearchResultCache(ttl=timedelta(minutes=5))
        hits = (DiscoveredSource("github", "https://github.com/a/b", "a/b", SourceClass.GITHUB_REPOSITORY),)
        cache.put("query", (SourceClass.GITHUB_REPOSITORY,), hits, now=T0)
        self.assertEqual(cache.get("query", (SourceClass.GITHUB_REPOSITORY,), now=T0 + timedelta(minutes=1)), hits)
        self.assertIsNone(cache.get("query", (SourceClass.GITHUB_REPOSITORY,), now=T0 + timedelta(minutes=10)))

    def test_query_normalization_is_case_and_whitespace_insensitive(self):
        cache = SearchResultCache()
        hits = (DiscoveredSource("github", "https://github.com/a/b", "a/b", SourceClass.GITHUB_REPOSITORY),)
        cache.put("Retry   Backoff", (SourceClass.GITHUB_REPOSITORY,), hits, now=T0)
        self.assertEqual(cache.get("retry backoff", (SourceClass.GITHUB_REPOSITORY,), now=T0), hits)


class SemanticReuseTests(unittest.TestCase):
    def test_rejects_reuse_on_entity_mismatch_even_with_identical_concept(self):
        candidate = SemanticReuseCandidate(concept="retry backoff", entity="service-a", captured_at=T0, document=_document())
        result = resolve_semantic_reuse(
            candidate, requested_concept="retry backoff", requested_entity="service-b", requested_time_scope=None,
        )
        self.assertIsNone(result)

    def test_rejects_reuse_outside_requested_time_scope(self):
        candidate = SemanticReuseCandidate(concept="retry backoff", entity="service-a", captured_at=T0, document=_document())
        result = resolve_semantic_reuse(
            candidate, requested_concept="retry backoff", requested_entity="service-a",
            requested_time_scope=(T0 + timedelta(days=1), T0 + timedelta(days=2)),
        )
        self.assertIsNone(result)

    def test_rejects_reuse_below_similarity_floor(self):
        candidate = SemanticReuseCandidate(concept="retry backoff", entity="service-a", captured_at=T0, document=_document())
        result = resolve_semantic_reuse(
            candidate, requested_concept="completely unrelated topic", requested_entity="service-a",
            requested_time_scope=None,
        )
        self.assertIsNone(result)

    def test_accepts_reuse_when_entity_time_and_similarity_all_match(self):
        document = _document()
        candidate = SemanticReuseCandidate(concept="retry backoff", entity="service-a", captured_at=T0, document=document)
        result = resolve_semantic_reuse(
            candidate, requested_concept="retry backoff", requested_entity="service-a",
            requested_time_scope=(T0 - timedelta(days=1), T0 + timedelta(days=1)),
        )
        self.assertIs(result, document)


if __name__ == "__main__":
    unittest.main()
