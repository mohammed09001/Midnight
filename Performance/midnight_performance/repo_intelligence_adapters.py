"""Real port adapters wiring Midnight Repo Intelligent to canonical Performance systems.

``repo_intelligence/ports.py`` defines provider-neutral Protocols and ships
no adapter code in the core. This module is the one place those Protocols
meet real Performance systems: ``query_api``, ``memory_bridge``, repository
entity resolution, accounting, and Repo Intelligent's own derived-state
store. Nothing here opens Memory or Performance storage behind those
canonical surfaces.

External network/model providers are opt-in and disabled by default
(``enable_external_intelligence=False``): Repo Intelligent 02/03 wires a real
GitHub search+fetch adapter here — network/HTTP imports belong at this
adapter layer, never inside ``repo_intelligence/`` itself (enforced by
``test_repo_intelligence_architecture.py``) — but the internal runtime must
remain fully useful with every external provider disabled.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import memory_bridge
from .contracts import Identity
from .memory_bridge import LessonDeliveryResult, MemoryReadResult
from .query_api import PerformanceQueryAPI, QueryAuthorization, QueryPage, QueryProjection
from .repo_intelligence.contracts import (
    CostResourceKind,
    ExternalSourceRef,
    ProjectIntelligenceJob,
    ResearchQuestion,
    external_source_ref_identity,
)
from .repo_intelligence.entity_resolution import classify_entity_kind
from .repo_intelligence.external_cache import NormalizedCacheEntry, NormalizedSourceCache, SearchResultCache
from .repo_intelligence.ports import (
    BudgetGrant,
    BudgetUsage,
    ClockPort,
    DiscoveredSource,
    FetchedDocument,
    GraphProjectionResult,
    PortAvailability,
    RepoIntelligenceProviders,
    SystemClock,
    UntrustedText,
)
from .repo_intelligence.research_security import (
    FetchLimits,
    FetchMetadata,
    SourcePolicy,
    authorize_source,
    validate_fetched_document,
)
from .repo_intelligence.sources import DEFAULT_SOURCE_TRUST, SourceClass, TrustClass
from .repo_intelligence_store import RepoIntelligenceStore


class PerformanceReadsAdapter:
    """Performance's canonical bounded read facade, including explicit paging."""

    def __init__(self, api: PerformanceQueryAPI) -> None:
        self._api = api

    def query(
        self,
        authorization: QueryAuthorization,
        *,
        kinds: frozenset | None = None,
        subject: Identity | None = None,
        claim_kinds: frozenset | None = None,
        limit: int = 50,
    ) -> QueryPage:
        # Compatibility surface for callers that intentionally need one page.
        return self._api.query_evidence(
            authorization, kinds=kinds, subject=subject, claim_kinds=claim_kinds,
            limit=limit, offset=0,
        )

    def query_page(
        self,
        authorization: QueryAuthorization,
        *,
        kinds: frozenset | None = None,
        subject: Identity | None = None,
        claim_kinds: frozenset | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> QueryPage:
        """Read one explicit slice; the orchestrator owns coverage policy."""
        return self._api.query_evidence(
            authorization, kinds=kinds, subject=subject, claim_kinds=claim_kinds,
            limit=limit, offset=offset,
        )

    def projection(self, authorization: QueryAuthorization, name: str) -> QueryProjection:
        return self._api.projection(authorization, name)


class MemoryBridgeAdapter:
    """Memory access strictly through the supported Memory bridge calls."""

    def __init__(self, memory_repo_path: Path | None = None) -> None:
        self._memory_repo_path = memory_repo_path

    def read_context(self, project_key: str, *, size: int = 20, query: str | None = None) -> MemoryReadResult:
        if self._memory_repo_path is None or not self._memory_repo_path.exists():
            return MemoryReadResult(
                available=False, error_code="MEMORY_REPO_NOT_CONFIGURED",
                error_message="no Memory repository path configured for this adapter",
            )
        extra = {"query": query} if query else {}
        return memory_bridge.read_performance_context(
            project_key, size=size, memory_repo_path=self._memory_repo_path, **extra
        )

    def propose_lesson(self, envelope) -> LessonDeliveryResult:
        return memory_bridge.propose_lesson_or_degrade(
            envelope, memory_repo_path=self._memory_repo_path
        )


class RepositoryIntelligenceAdapter:
    """File/module/package-level live-repository rollup.

    Performance's deeper per-changeset symbol/region resolver needs before/
    after file content and is not silently emulated by this path-only query.
    The deeper integration remains an explicit later gap.
    """

    def __init__(self, repository_key: str, repo_root: Path, *, clock) -> None:
        self._repository_key = repository_key
        self._repo_root = repo_root
        self._clock = clock

    def available(self) -> PortAvailability:
        if not self._repo_root.exists():
            return PortAvailability(
                port="repository_intelligence", available=False,
                reason=f"repository root not found: {self._repo_root}",
            )
        return PortAvailability(port="repository_intelligence", available=True)

    def resolve_entity_refs(self, repository_key: str, paths: tuple[str, ...]) -> tuple:
        return tuple((path, classify_entity_kind(path)) for path in paths)


class AIAccountingBudgetMeter:
    """Repo Intelligent cost ledger using Performance-compatible accounting vocabulary."""

    def __init__(self, store: RepoIntelligenceStore, *, clock: ClockPort | None = None) -> None:
        self._store = store
        self._clock = clock or SystemClock()

    def authorize(self, job: ProjectIntelligenceJob) -> BudgetGrant:
        usage = self.usage(job.project)
        budget = job.budget
        if budget.max_model_calls is not None and usage.model_calls >= budget.max_model_calls:
            return BudgetGrant(job=job.identity, granted=False, reason="max_model_calls ceiling reached")
        if budget.max_network_requests is not None and usage.network_requests >= budget.max_network_requests:
            return BudgetGrant(job=job.identity, granted=False, reason="max_network_requests ceiling reached")
        if budget.max_cost_micros is not None and usage.cost_micros >= budget.max_cost_micros:
            return BudgetGrant(job=job.identity, granted=False, reason="max_cost_micros ceiling reached")
        if budget.max_fetched_documents is not None and usage.fetched_documents >= budget.max_fetched_documents:
            return BudgetGrant(job=job.identity, granted=False, reason="max_fetched_documents ceiling reached")
        if budget.max_seconds is not None and job.started_at is not None:
            elapsed = (self._clock.now() - job.started_at).total_seconds()
            if elapsed >= budget.max_seconds:
                return BudgetGrant(job=job.identity, granted=False, reason="max_seconds ceiling reached")
        return BudgetGrant(job=job.identity, granted=True)

    def record(self, cost) -> None:
        self._store.append_cost_record(cost)

    def usage(self, project: Identity) -> BudgetUsage:
        records = self._store.list_cost_records(project)
        model_calls = sum(
            1 for r in records if r.resource.value in ("model_inference", "embedding", "rerank")
        )
        network_requests = sum(
            1 for r in records if r.resource.value in ("external_search", "external_fetch")
        )
        fetched_documents = sum(
            1 for r in records if r.resource is CostResourceKind.EXTERNAL_FETCH
        )
        cost_micros = sum(r.cost_micros or 0 for r in records)
        return BudgetUsage(
            project=project, model_calls=model_calls,
            network_requests=network_requests, cost_micros=cost_micros,
            fetched_documents=fetched_documents,
        )


class GraphProjectionAdapter:
    """Persist Repo Intelligent's own rebuildable graph overlay."""

    def __init__(self, store: RepoIntelligenceStore) -> None:
        self._store = store

    def available(self) -> PortAvailability:
        return PortAvailability(port="graph_projection", available=True)

    def rebuild(self, project: Identity, links: tuple) -> GraphProjectionResult:
        digest_material = "|".join(sorted(link.identity.canonical for link in links)) or "empty"
        generation = hashlib.sha256(digest_material.encode("utf-8")).hexdigest()
        self._store.replace_graph_links(project, links)
        return GraphProjectionResult(
            project=project, link_count=len(links), generation=generation
        )


_GITHUB_API = "https://api.github.com"
_USER_AGENT = "midnight-repo-intelligence/1 (+https://github.com)"
_RATE_LIMITED_CODES = (403, 429)
_GITHUB_RAW_CONTENT_TYPES = frozenset({"text/plain", "text/markdown", "application/vnd.github.raw+json"})

_QUESTION_SCAFFOLDING_WORDS = frozenset(
    {
        "what", "are", "is", "the", "a", "an", "for", "of", "to", "in", "on",
        "and", "or", "how", "can", "should", "be", "been", "being", "this",
        "that", "these", "those", "established", "approaches", "approach",
        "patterns", "pattern", "reliable", "prevent", "recurring", "failures",
        "failure", "safer", "alternatives", "alternative", "changes",
        "change", "had", "reverted", "whether", "their", "between", "divided",
        "responsibilities", "keep", "healthy", "coupling", "observed",
        "reflects", "boundary", "missing", "shared", "contract",
        "authoritative", "confirm", "replace", "current", "local", "not", "no",
    }
)


def _search_terms(question_text: str, *, max_terms: int = 4) -> str:
    """Reduce a compiled question sentence to a handful of keyword terms.

    GitHub repository search ANDs terms against name/description/topics and
    returns nothing for a full natural-language sentence; falls back to the
    original tokens if stripping scaffolding words leaves nothing.
    """
    tokens = [token.strip(".,()'\"") for token in question_text.lower().split()]
    significant = [token for token in tokens if token and token not in _QUESTION_SCAFFOLDING_WORDS]
    return " ".join((significant or tokens)[:max_terms])


def _github_headers(token: str | None, *, accept: str) -> dict[str, str]:
    headers = {"User-Agent": _USER_AGENT, "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get(url: str, headers: dict[str, str], *, timeout_seconds: float, max_retries: int) -> tuple[bytes, dict[str, str], float]:
    """One bounded GET with a fixed retry budget for transient 5xx only.

    Rate-limit responses (403/429) fail fast — no blind backoff, since
    honoring GitHub's reset window could stall a bounded job far past its
    own time budget.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        request = urllib.request.Request(url, headers=headers)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
                elapsed = time.monotonic() - started
                return body, dict(response.headers.items()), elapsed
        except urllib.error.HTTPError as exc:
            if exc.code in _RATE_LIMITED_CODES:
                raise
            if exc.code >= 500 and attempt < max_retries:
                last_error = exc
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < max_retries:
                continue
            raise
    assert last_error is not None
    raise last_error


def _relevance_from_stars(stars: int) -> float:
    """A bounded, monotonic hint — never a popularity ranking substitute.

    ``discovery.rank_discoveries`` treats this as one input among several and
    explicitly excludes popularity from its own scoring; this only keeps the
    field within its required [0, 1] range.
    """
    if stars <= 0:
        return 0.5
    return min(1.0, 0.5 + (stars.bit_length() / 40.0))


class GitHubSearchAdapter:
    """``ExternalDiscoveryPort`` over GitHub's public repository search API."""

    def __init__(
        self,
        *,
        token: str | None = None,
        cache: SearchResultCache | None = None,
        max_retries: int = 1,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._token = token
        self._cache = cache
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds

    def available(self) -> PortAvailability:
        return PortAvailability(port="external_discovery", available=True)

    def search(self, question: ResearchQuestion, *, limit: int = 10) -> tuple[DiscoveredSource, ...]:
        # discover() already produced a privacy-minimized, length-bounded
        # question_text via prepare_outbound_query before this is called.
        # GitHub's repository search is a strict AND over a handful of
        # searchable fields, not a semantic query — the full question
        # sentence ("what are established approaches for X") almost always
        # returns zero results, so only the concept's own keywords are sent.
        query = _search_terms(question.question_text)
        source_classes = (SourceClass.GITHUB_REPOSITORY,)
        now = datetime.now(timezone.utc)
        if self._cache is not None:
            cached = self._cache.get(query, source_classes, now=now)
            if cached is not None:
                return cached[:limit]

        bounded_limit = max(1, min(limit, 30))
        url = f"{_GITHUB_API}/search/repositories?{urllib.parse.urlencode({'q': query, 'per_page': bounded_limit})}"
        headers = _github_headers(self._token, accept="application/vnd.github+json")
        body, _, _ = _github_get(url, headers, timeout_seconds=self._timeout_seconds, max_retries=self._max_retries)
        payload = json.loads(body.decode("utf-8"))

        hits = tuple(
            DiscoveredSource(
                provider="github",
                locator=item["html_url"],
                title=item.get("full_name") or item["html_url"],
                source_class=SourceClass.GITHUB_REPOSITORY,
                relevance=_relevance_from_stars(item.get("stargazers_count", 0)),
            )
            for item in payload.get("items", [])[:bounded_limit]
        )
        if self._cache is not None:
            self._cache.put(query, source_classes, hits, now=now)
        return hits


class GitHubFetchAdapter:
    """``FetchParsePort`` fetching one repository's README over GitHub's API."""

    def __init__(
        self,
        project: Identity,
        *,
        token: str | None = None,
        cache: NormalizedSourceCache | None = None,
        limits: FetchLimits | None = None,
        source_policy: SourcePolicy | None = None,
        max_retries: int = 1,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._project = project
        self._token = token
        self._cache = cache
        self._limits = limits or FetchLimits(allowed_content_types=_GITHUB_RAW_CONTENT_TYPES)
        self._source_policy = source_policy or SourcePolicy(
            allowed_domains=frozenset({"github.com"}),
            allowed_github_repositories=frozenset({"*"}),
        )
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds

    def available(self) -> PortAvailability:
        return PortAvailability(port="fetch_parse", available=True)

    def fetch(self, locator: str, source_class: SourceClass) -> FetchedDocument:
        trust = DEFAULT_SOURCE_TRUST.get(source_class, TrustClass.UNVERIFIED)
        canonical = authorize_source(locator, source_class, trust, self._source_policy)
        owner_repo = canonical.split("github.com/", 1)[1].strip("/")

        cached = self._cache.get(owner_repo) if self._cache is not None else None
        headers = _github_headers(self._token, accept="application/vnd.github.raw+json")
        if cached is not None and cached.etag:
            headers["If-None-Match"] = cached.etag

        url = f"{_GITHUB_API}/repos/{owner_repo}/readme"
        try:
            body, response_headers, elapsed = _github_get(
                url, headers, timeout_seconds=self._timeout_seconds, max_retries=self._max_retries
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and cached is not None:
                content = cached.normalized_text
                elapsed = 0.0
                etag = cached.etag
                digest = cached.content_digest
                content_type = "text/plain"
            else:
                raise
        else:
            if len(body) > self._limits.maximum_bytes:
                raise ValueError("decoded fetch size exceeds limit")
            content = body.decode("utf-8", errors="replace")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            etag = response_headers.get("ETag")
            content_type = response_headers.get("Content-Type", "text/plain")

        now = datetime.now(timezone.utc)
        text = UntrustedText(content=content, content_digest=digest, source_class=source_class)
        ref_identity = external_source_ref_identity("github", canonical, digest)
        source_ref = ExternalSourceRef(
            identity=ref_identity,
            project=self._project,
            source_class=source_class,
            provider="github",
            locator=canonical,
            title=owner_repo,
            content_digest=digest,
            captured_at=now,
            retrieval_method="github-readme-fetch",
            retrieval_version="1",
            trust_class=trust,
        )
        document = FetchedDocument(source_ref=source_ref, text=text)
        metadata = FetchMetadata(
            content_type=content_type,
            declared_bytes=len(content.encode("utf-8")),
            elapsed_seconds=elapsed,
        )
        validate_fetched_document(document, metadata, self._limits, self._source_policy)

        if self._cache is not None:
            self._cache.put(
                owner_repo,
                NormalizedCacheEntry(etag=etag, content_digest=digest, fetched_at=now, normalized_text=content),
            )
        return document


def production_providers(
    *,
    project: Identity,
    query_api: PerformanceQueryAPI,
    store: RepoIntelligenceStore,
    repository_key: str,
    repo_root: Path,
    memory_repo_path: Path | None = None,
    enable_external_intelligence: bool = False,
    github_token: str | None = None,
) -> RepoIntelligenceProviders:
    """Real internal providers. External intelligence is opt-in and disabled
    by default (``enable_external_intelligence=False``) — core operation must
    remain fully usable with every external provider disabled."""
    clock = SystemClock()
    resolved_memory_path = (
        memory_repo_path if memory_repo_path is not None else (repo_root / "Memory")
    )
    return RepoIntelligenceProviders(
        repository_intelligence=RepositoryIntelligenceAdapter(
            repository_key, repo_root, clock=clock
        ),
        performance_reads=PerformanceReadsAdapter(query_api),
        memory_bridge=MemoryBridgeAdapter(resolved_memory_path),
        external_discovery=GitHubSearchAdapter(token=github_token) if enable_external_intelligence else None,
        fetch_parse=GitHubFetchAdapter(project, token=github_token) if enable_external_intelligence else None,
        embeddings=None,
        model_generation=None,
        graph_projection=GraphProjectionAdapter(store),
        clock=clock,
        budget_meter=AIAccountingBudgetMeter(store),
    )


__all__ = [
    "AIAccountingBudgetMeter",
    "GitHubFetchAdapter",
    "GitHubSearchAdapter",
    "GraphProjectionAdapter",
    "MemoryBridgeAdapter",
    "PerformanceReadsAdapter",
    "RepositoryIntelligenceAdapter",
    "production_providers",
]
