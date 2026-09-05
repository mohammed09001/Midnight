"""Real port adapters wiring Midnight Repo Intelligent to canonical Performance systems.

``repo_intelligence/ports.py`` defines provider-neutral Protocols and ships
no adapter code in the core. This module is the one place those Protocols
meet real Performance systems: ``query_api``, ``memory_bridge``, repository
entity resolution, accounting, and Repo Intelligent's own derived-state
store. Nothing here opens Memory or Performance storage behind those
canonical surfaces.

External network/model providers remain deliberately unconfigured in this
Execution; Repo Intelligent 02/03 owns production external-intelligence
wiring. The internal runtime must remain useful without them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import memory_bridge
from .contracts import Identity
from .memory_bridge import LessonDeliveryResult, MemoryReadResult
from .query_api import PerformanceQueryAPI, QueryAuthorization, QueryPage, QueryProjection
from .repo_intelligence.contracts import ProjectIntelligenceJob
from .repo_intelligence.entity_resolution import classify_entity_kind
from .repo_intelligence.ports import (
    BudgetGrant,
    BudgetUsage,
    GraphProjectionResult,
    PortAvailability,
    RepoIntelligenceProviders,
)
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

    def read_context(self, project_key: str, *, size: int = 20) -> MemoryReadResult:
        if self._memory_repo_path is None or not self._memory_repo_path.exists():
            return MemoryReadResult(
                available=False, error_code="MEMORY_REPO_NOT_CONFIGURED",
                error_message="no Memory repository path configured for this adapter",
            )
        return memory_bridge.read_performance_context(
            project_key, size=size, memory_repo_path=self._memory_repo_path
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

    def __init__(self, store: RepoIntelligenceStore) -> None:
        self._store = store

    def authorize(self, job: ProjectIntelligenceJob) -> BudgetGrant:
        usage = self.usage(job.project)
        budget = job.budget
        if budget.max_model_calls is not None and usage.model_calls >= budget.max_model_calls:
            return BudgetGrant(job=job.identity, granted=False, reason="max_model_calls ceiling reached")
        if budget.max_network_requests is not None and usage.network_requests >= budget.max_network_requests:
            return BudgetGrant(job=job.identity, granted=False, reason="max_network_requests ceiling reached")
        if budget.max_cost_micros is not None and usage.cost_micros >= budget.max_cost_micros:
            return BudgetGrant(job=job.identity, granted=False, reason="max_cost_micros ceiling reached")
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
        cost_micros = sum(r.cost_micros or 0 for r in records)
        return BudgetUsage(
            project=project, model_calls=model_calls,
            network_requests=network_requests, cost_micros=cost_micros,
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


def production_providers(
    *,
    query_api: PerformanceQueryAPI,
    store: RepoIntelligenceStore,
    repository_key: str,
    repo_root: Path,
    memory_repo_path: Path | None = None,
) -> RepoIntelligenceProviders:
    """Real internal providers; external/model ports are intentionally optional."""
    from .repo_intelligence.ports import SystemClock

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
        external_discovery=None,
        fetch_parse=None,
        embeddings=None,
        model_generation=None,
        graph_projection=GraphProjectionAdapter(store),
        clock=clock,
        budget_meter=AIAccountingBudgetMeter(store),
    )


__all__ = [
    "AIAccountingBudgetMeter",
    "GraphProjectionAdapter",
    "MemoryBridgeAdapter",
    "PerformanceReadsAdapter",
    "RepositoryIntelligenceAdapter",
    "production_providers",
]
