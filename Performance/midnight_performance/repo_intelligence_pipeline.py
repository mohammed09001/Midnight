"""Canonical production orchestrator for Midnight Repo Intelligent.

Repo Intelligent 02/Execution 01 makes this module the single production
owner of stage sequencing. Domain rules remain in their existing modules;
this orchestrator owns coverage, stage visibility, idempotent replay policy,
and the decision about which existing engine is production-canonical versus
library-only/deferred.

The logical runtime contract is:

OBSERVE -> DETECT SIGNAL -> COMPUTE LEARNING PRESSURE ->
CHECK INTERNAL SUFFICIENCY -> PLAN RETRIEVAL ->
ROUTE CHEAPEST QUALIFIED RESOLVER -> OPTIONAL EXTERNAL DISCOVERY ->
VERIFY EVIDENCE -> SYNTHESIZE -> GRAPH/FUSION -> ATTENTION RANK -> EXPOSE ->
RECORD OUTCOME -> LEARN.

The current signal scorer consumes the coarse Memory status while computing
its knowledge-deficit factor, so the Memory read is preloaded before the local
scan. The returned stage trace remains in contract order and explicitly says
that this is a coarse preload; Repo Intelligent 02/Execution 02 owns the
per-question semantic sufficiency repair. Continuous background learning is
formally DEFERRED in this Execution rather than represented as production.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

from .contracts import ClaimKind, EntityKind, Identity
from .privacy import PrivacyPolicy
from .query_api import QueryAuthorization
from .repo_intelligence.authorization import RepoIntelligenceAuthorization, ensure_same_project
from .repo_intelligence.contracts import (
    AssociationKind,
    BudgetCeiling,
    CacheStatus,
    CostRecord,
    CostResourceKind,
    EvidenceBundle,
    EvidenceItem,
    Exposure,
    ExposureChannel,
    ExposureOutcome,
    InternalAnswerStatus,
    JobStatus,
    JobTrigger,
    LearningOutcome,
    ProjectInsight,
    ProjectIntelligenceJob,
    QuestionStatus,
    ResearchQuestion,
    evidence_bundle_identity,
    new_event_identity,
    project_intelligence_job_identity,
)
from .repo_intelligence.discovery import DiscoveryRun, discover
from .repo_intelligence.federated_retrieval import RetrievalPlan, RetrievalQuery, plan_retrieval
from .repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from .repo_intelligence.ports import RepoIntelligenceProviders
from .repo_intelligence.project_graph import ProjectKnowledgeGraph, build_project_graph
from .repo_intelligence.question_compiler import abstract_concept, compile_question
from .repo_intelligence.runtime_contract import (
    PerformanceEvidenceCoverage,
    RUNTIME_CONTRACT_VERSION,
    RuntimeStage,
    StageExecutionStatus,
    StageOutcome,
    StageReasonCode,
)
from .repo_intelligence.signals import ScoredSignal, SignalScanResult, scan_signals
from .repo_intelligence.sources import DEFAULT_SOURCE_TRUST, SourceClass, TrustClass
from .repo_intelligence.synthesis import ClaimCandidate, synthesize
from .repo_intelligence.terminal_learning import (
    TerminalCandidate,
    TerminalContext,
    TerminalDecision,
    decide_terminal_card,
)
from .repo_intelligence_evidence_bridge import resolve_entity_refs_by_path
from .repo_intelligence_store import RepoIntelligenceStore
from .repository_capture import RepositorySnapshot

DERIVATION_METHOD = "repo-intelligence-pipeline"
DERIVATION_VERSION = "2"
DEFAULT_JOB_BUDGET = BudgetCeiling(
    max_model_calls=2, max_network_requests=5, max_seconds=120.0
)
PERFORMANCE_PAGE_SIZE = 100
PERFORMANCE_HARD_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    project: Identity
    job: ProjectIntelligenceJob
    signals_detected: int
    questions_compiled: tuple[ResearchQuestion, ...]
    discovery_runs: tuple[DiscoveryRun, ...]
    insights_synthesized: tuple[ProjectInsight, ...]
    graph: ProjectKnowledgeGraph
    decision: TerminalDecision | None
    decision_candidate: TerminalCandidate | None
    stopped_reason: str
    runtime_contract_version: int = RUNTIME_CONTRACT_VERSION
    stage_outcomes: tuple[StageOutcome, ...] = ()
    performance_coverage: PerformanceEvidenceCoverage | None = None
    retrieval_plans: tuple[RetrievalPlan, ...] = ()


def _outcome(
    stage: RuntimeStage,
    status: StageExecutionStatus,
    owner: str,
    *,
    reason: StageReasonCode | None = None,
    detail: str = "",
) -> StageOutcome:
    return StageOutcome(stage, status, owner, reason, detail)


def _ordered_stage_outcomes(values: dict[RuntimeStage, StageOutcome]) -> tuple[StageOutcome, ...]:
    """Always return one result per contract stage, in contract order."""
    missing = [stage.value for stage in RuntimeStage if stage not in values]
    if missing:
        raise RuntimeError(f"canonical runtime omitted stage outcomes: {missing}")
    return tuple(values[stage] for stage in RuntimeStage)


def _read_performance_evidence(
    providers: RepoIntelligenceProviders,
    authorization: QueryAuthorization,
    *,
    page_size: int = PERFORMANCE_PAGE_SIZE,
    hard_limit: int = PERFORMANCE_HARD_LIMIT,
) -> tuple[tuple, PerformanceEvidenceCoverage, StageOutcome]:
    """Read a bounded, explicitly-accounted slice of canonical Performance evidence.

    Production adapters expose ``query_page``. Older/fake ports remain valid
    one-page readers; if they report more matches than they returned, the
    runtime continues locally but reports a degraded/truncated observation
    stage rather than silently treating the first page as complete.
    """
    port = providers.performance_reads
    if port is None:
        coverage = PerformanceEvidenceCoverage(
            0, 0, 0, hard_limit, False, "Performance read provider unavailable"
        )
        return (), coverage, _outcome(
            RuntimeStage.OBSERVE,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence_pipeline._read_performance_evidence",
            reason=StageReasonCode.PROVIDER_UNAVAILABLE,
            detail=coverage.reason,
        )

    first = port.query(authorization, limit=page_size)
    total = first.total_matching
    first_items = tuple(first.items)
    if total <= len(first_items):
        coverage = PerformanceEvidenceCoverage(
            total, len(first_items), 0, hard_limit, True,
            "all matching Performance evidence retrieved",
        )
        return first_items, coverage, _outcome(
            RuntimeStage.OBSERVE,
            StageExecutionStatus.COMPLETED,
            "repo_intelligence_pipeline._read_performance_evidence",
            detail=f"retrieved {len(first_items)} of {total} matching observations",
        )

    query_page = getattr(port, "query_page", None)
    if query_page is None:
        coverage = PerformanceEvidenceCoverage(
            total, len(first_items), 0, hard_limit, False,
            "reader has no pagination surface; bounded first page retained",
        )
        return first_items, coverage, _outcome(
            RuntimeStage.OBSERVE,
            StageExecutionStatus.DEGRADED,
            "repo_intelligence_pipeline._read_performance_evidence",
            reason=StageReasonCode.HARD_LIMIT,
            detail=f"retrieved {len(first_items)} of {total}; pagination unavailable",
        )

    start_offset = max(0, total - hard_limit)
    target = min(total, hard_limit)
    items: list = []
    offset = start_offset
    stale = False
    while len(items) < target:
        limit = min(page_size, target - len(items))
        page = query_page(authorization, limit=limit, offset=offset)
        if page.total_matching != total:
            stale = True
            break
        chunk = tuple(page.items)
        if not chunk:
            stale = True
            break
        items.extend(chunk)
        offset += len(chunk)

    retrieved = len(items)
    if stale:
        coverage = PerformanceEvidenceCoverage(
            total, retrieved, start_offset, hard_limit, False,
            "matching Performance evidence changed or pagination ended during the bounded read",
        )
        return tuple(items), coverage, _outcome(
            RuntimeStage.OBSERVE,
            StageExecutionStatus.DEGRADED,
            "repo_intelligence_pipeline._read_performance_evidence",
            reason=StageReasonCode.STALE_STATE,
            detail=f"retrieved {retrieved} of planned {target}; matching set was not stable",
        )

    if total > hard_limit:
        coverage = PerformanceEvidenceCoverage(
            total, retrieved, start_offset, hard_limit, False,
            f"hard limit retained the newest {retrieved} of {total} matching observations",
        )
        return tuple(items), coverage, _outcome(
            RuntimeStage.OBSERVE,
            StageExecutionStatus.DEGRADED,
            "repo_intelligence_pipeline._read_performance_evidence",
            reason=StageReasonCode.HARD_LIMIT,
            detail=coverage.reason,
        )

    complete = retrieved == total
    coverage = PerformanceEvidenceCoverage(
        total, retrieved, start_offset, hard_limit, complete,
        "all paginated Performance evidence retrieved" if complete else "pagination returned fewer observations than declared",
    )
    return tuple(items), coverage, _outcome(
        RuntimeStage.OBSERVE,
        StageExecutionStatus.COMPLETED if complete else StageExecutionStatus.DEGRADED,
        "repo_intelligence_pipeline._read_performance_evidence",
        reason=None if complete else StageReasonCode.STALE_STATE,
        detail=f"retrieved {retrieved} of {total} matching observations",
    )


def _memory_answer_status(
    providers: RepoIntelligenceProviders, project_key: str
) -> tuple[InternalAnswerStatus | None, StageOutcome, bool]:
    """Read the existing coarse Memory signal without pretending it is semantic sufficiency.

    The boolean says whether the internal-sufficiency check actually ran to a
    trustworthy result. If it did not, external spending is blocked for this
    pass. Repo Intelligent 02/Execution 02 replaces this coarse project-level
    status with per-question qualification.
    """
    owner = "repo_intelligence_pipeline._memory_answer_status"
    if providers.memory_bridge is None:
        return None, _outcome(
            RuntimeStage.CHECK_INTERNAL_SUFFICIENCY,
            StageExecutionStatus.SKIPPED,
            owner,
            reason=StageReasonCode.PROVIDER_UNAVAILABLE,
            detail="Memory bridge unavailable; knowledge deficit remains unknown",
        ), False
    try:
        result = providers.memory_bridge.read_context(project_key, size=5)
    except Exception as exc:  # provider boundary: degrade without leaking payload text
        return None, _outcome(
            RuntimeStage.CHECK_INTERNAL_SUFFICIENCY,
            StageExecutionStatus.FAILED,
            owner,
            reason=StageReasonCode.INTERNAL_ERROR,
            detail=f"Memory bridge failed with {type(exc).__name__}; external escalation blocked",
        ), False
    if not result.available:
        return None, _outcome(
            RuntimeStage.CHECK_INTERNAL_SUFFICIENCY,
            StageExecutionStatus.SKIPPED,
            owner,
            reason=StageReasonCode.PROVIDER_UNAVAILABLE,
            detail="Memory reported unavailable; knowledge deficit remains unknown",
        ), False
    status = InternalAnswerStatus.PARTIAL if result.records else InternalAnswerStatus.ABSENT
    return status, _outcome(
        RuntimeStage.CHECK_INTERNAL_SUFFICIENCY,
        StageExecutionStatus.COMPLETED,
        owner,
        detail=(
            "coarse Memory context exists; semantic per-question sufficiency is not claimed"
            if result.records
            else "Memory context check completed with no records"
        ),
    ), True


def _build_job(
    project: Identity,
    *,
    now: datetime,
    budget: BudgetCeiling,
    idempotency_key: str,
    user_pull: bool = False,
) -> ProjectIntelligenceJob:
    identity = project_intelligence_job_identity(project, "continuous_learning", idempotency_key)
    return ProjectIntelligenceJob(
        identity=identity,
        project=project,
        job_kind="continuous_learning",
        idempotency_key=idempotency_key,
        trigger=JobTrigger.USER_PULL if user_pull else JobTrigger.MAINTENANCE,
        status=JobStatus.RUNNING,
        stop_condition="stop on configured budget/coverage/policy boundaries",
        budget=budget,
        derivation_method=DERIVATION_METHOD,
        derivation_version=DERIVATION_VERSION,
        requested_at=now,
        started_at=now,
    )


def _stable_scan_result(
    scan_result: SignalScanResult,
    project: Identity,
    job: ProjectIntelligenceJob,
    *,
    latency_ms: float,
    now: datetime,
) -> SignalScanResult:
    """Attach one deterministic local-compute cost reference to every scan receipt."""
    cost_identity = deterministic_repo_identity(
        RepoIntelligenceKind.COST_RECORD,
        f"{job.identity.canonical}|signal-detection-local-compute",
    )
    cost = CostRecord(
        identity=cost_identity,
        project=project,
        job=job.identity,
        resource=CostResourceKind.LOCAL_COMPUTE,
        provider="deterministic-local",
        latency_ms=round(max(0.0, latency_ms), 4),
        occurred_at=now,
        cache_status=CacheStatus.MISS,
    )
    signals = tuple(
        replace(scored, receipt=replace(scored.receipt, cost_ref=cost_identity))
        for scored in scan_result.signals
    )
    return replace(scan_result, signals=signals, cost_records=(cost,))


def _evidence_bundle_for_signal(
    scored: ScoredSignal, *, project: Identity, now: datetime
) -> tuple[EvidenceBundle, tuple[str, ...]]:
    items = (
        EvidenceItem(
            ref=scored.signal.identity.canonical,
            source_class=SourceClass.PERFORMANCE_EVIDENCE,
            trust_class=TrustClass.FIRST_PARTY_LOCAL,
            captured_at=now,
        ),
    )
    identity = evidence_bundle_identity(project, items)
    return (
        EvidenceBundle(
            identity=identity, project=project, items=items,
            created_at=now, gaps=scored.signal.gaps,
        ),
        (scored.signal.identity.canonical,),
    )


def _augment_with_external_evidence(
    bundle: EvidenceBundle,
    candidates: list[ClaimCandidate],
    *,
    discovery: DiscoveryRun | None,
    providers: RepoIntelligenceProviders,
    project: Identity,
    now: datetime,
) -> EvidenceBundle:
    """Promote only a fetched, content-digested source into evidence."""
    if discovery is None or not discovery.ranked or providers.fetch_parse is None:
        return bundle
    top = discovery.ranked[0]
    if not providers.fetch_parse.available().available:
        return bundle
    document = providers.fetch_parse.fetch(top.canonical_locator, top.source.source_class)
    from .repo_intelligence.contracts import ExternalSourceRef, external_source_ref_identity

    ref_identity = external_source_ref_identity(
        top.source.provider, top.canonical_locator, document.text.content_digest
    )
    external_ref = ExternalSourceRef(
        identity=ref_identity,
        project=project,
        source_class=top.source.source_class,
        provider=top.source.provider,
        locator=top.canonical_locator,
        title=top.source.title,
        content_digest=document.text.content_digest,
        captured_at=now,
        retrieval_method="provider-fetch",
        retrieval_version="1",
        trust_class=DEFAULT_SOURCE_TRUST.get(
            top.source.source_class, TrustClass.UNVERIFIED
        ),
    )
    items = tuple(bundle.items) + (
        EvidenceItem(
            ref=ref_identity.canonical,
            source_class=external_ref.source_class,
            trust_class=external_ref.trust_class,
            captured_at=now,
            content_digest=document.text.content_digest,
        ),
    )
    candidates.append(
        ClaimCandidate(
            topic=top.source.title[:60],
            statement=f"external source '{top.source.title}' is a candidate reference for this need",
            claim_kind=ClaimKind.INFERRED,
            evidence_refs=(ref_identity.canonical,),
            supports=True,
        )
    )
    return EvidenceBundle(
        identity=evidence_bundle_identity(project, items),
        project=project,
        items=items,
        created_at=now,
        gaps=bundle.gaps,
    )


def _terminal_candidate(
    insight: ProjectInsight,
    question: ResearchQuestion | None,
    scored: ScoredSignal,
    *,
    dismissal_count: int,
) -> TerminalCandidate:
    confidence = insight.confidence if insight.confidence is not None else 0.5
    why_now = question.why_now if question is not None else (
        f"{scored.signal.signal_kind} signal observed in the window ending "
        f"{scored.signal.window_end.isoformat()}"
    )
    next_action = (
        question.stop_condition if question is not None
        else "review the cited internal evidence"
    )
    return TerminalCandidate(
        insight=insight,
        why_now=why_now,
        project_connection=f"affects {', '.join(scored.paths[:3])}",
        next_learning_action=next_action,
        relevance=min(1.0, confidence + 0.1),
        evidence_quality=confidence,
        novelty=1.0 if dismissal_count == 0 else max(0.0, 1.0 - 0.34 * dismissal_count),
        expected_learning_value=confidence,
        interruption_cost=0.2,
    )


def _stable_exposure(decision: TerminalDecision, job: ProjectIntelligenceJob) -> TerminalDecision:
    identity = deterministic_repo_identity(
        RepoIntelligenceKind.EXPOSURE,
        f"{job.identity.canonical}|terminal|{decision.exposure.insight.canonical}|"
        f"{decision.exposure.channel.value}|{decision.exposure.outcome.value}",
    )
    return replace(decision, exposure=replace(decision.exposure, identity=identity))


def run_pipeline(
    project: Identity,
    repository_key: str,
    repo_root: Path,
    providers: RepoIntelligenceProviders,
    authorization: RepoIntelligenceAuthorization,
    store: RepoIntelligenceStore,
    *,
    now: datetime,
    window: timedelta = timedelta(days=14),
    project_key: str | None = None,
    user_pull: bool = False,
    terminal_context: TerminalContext = TerminalContext(),
    privacy_policy: PrivacyPolicy | None = None,
) -> PipelineRunResult:
    """Run one bounded, observable canonical runtime pass."""
    ensure_same_project(authorization, project=project)
    if now.tzinfo is None:
        raise ValueError("pipeline run time must be timezone-aware")
    window_start = now - window
    project_key = project_key or repository_key
    effective_privacy_policy = privacy_policy if privacy_policy is not None else PrivacyPolicy()
    stages: dict[RuntimeStage, StageOutcome] = {}

    snapshot = (
        RepositorySnapshot.capture(repo_root)
        if repo_root.exists() else RepositorySnapshot({})
    )
    refs_by_path = resolve_entity_refs_by_path(
        project, repository_key, snapshot, now=now
    )

    read_authorization = QueryAuthorization(
        project=project, allowed_kinds=frozenset(EntityKind)
    )
    envelopes, coverage, observe_outcome = _read_performance_evidence(
        providers, read_authorization
    )
    stages[RuntimeStage.OBSERVE] = observe_outcome

    evidence_material = "|".join(
        envelope.observation.identity.canonical for envelope in envelopes
    )
    repository_material = "|".join(
        sorted(ref.identity.canonical for ref in refs_by_path.values())
    )
    idempotency_key = hashlib.sha256(
        (
            f"{project.canonical}|{window_start.isoformat()}|{now.isoformat()}|"
            f"{coverage.start_offset}|{coverage.retrieved}|{evidence_material}|{repository_material}"
        ).encode()
    ).hexdigest()
    new_job = _build_job(
        project, now=now, budget=DEFAULT_JOB_BUDGET,
        idempotency_key=idempotency_key, user_pull=user_pull,
    )
    existing_job = store.get_job(project, new_job.identity.canonical)
    replayed = existing_job is not None and existing_job.status is JobStatus.COMPLETED
    job = existing_job if replayed else new_job
    if not replayed:
        store.upsert_job(job)

    memory_status, memory_outcome, internal_check_safe = _memory_answer_status(
        providers, project_key
    )
    stages[RuntimeStage.CHECK_INTERNAL_SUFFICIENCY] = memory_outcome

    scan_started = perf_counter()
    raw_scan = scan_signals(
        project,
        repository_key,
        envelopes=envelopes,
        refs_by_path=refs_by_path,
        window_start=window_start,
        window_end=now,
        now=now,
        memory_status=memory_status,
        job=None,
    )
    scan_result = _stable_scan_result(
        raw_scan, project, job,
        latency_ms=(perf_counter() - scan_started) * 1000.0,
        now=now,
    )
    stages[RuntimeStage.DETECT_SIGNAL] = _outcome(
        RuntimeStage.DETECT_SIGNAL,
        StageExecutionStatus.COMPLETED,
        "repo_intelligence.signals.scan_signals",
        detail=f"detected {len(scan_result.signals)} derived signals",
    )
    stages[RuntimeStage.COMPUTE_LEARNING_PRESSURE] = _outcome(
        RuntimeStage.COMPUTE_LEARNING_PRESSURE,
        StageExecutionStatus.COMPLETED if scan_result.signals else StageExecutionStatus.SKIPPED,
        "repo_intelligence.signals.score_path_pressure",
        reason=None if scan_result.signals else StageReasonCode.ABSENCE,
        detail=(
            "pressure factors are embedded in the scored signals"
            if scan_result.signals else "no signal crossed a detector condition"
        ),
    )
    if not replayed and providers.budget_meter is not None:
        for cost in scan_result.cost_records:
            providers.budget_meter.record(cost)

    existing_status_by_key = store.question_status_by_dedup_key(project)
    compiled_questions: list[ResearchQuestion] = []
    retrieval_plans: list[RetrievalPlan] = []
    discovery_runs: list[DiscoveryRun] = []
    insights: list[ProjectInsight] = []
    insight_bundles: list[tuple[ProjectInsight, EvidenceBundle]] = []
    insight_context: dict[str, tuple[ScoredSignal, ResearchQuestion | None]] = {}
    open_questions = 0
    discovery_attempted = 0
    discovery_budget_stops = 0
    discovery_failures = 0
    verification_degraded = False
    synthesis_failures = 0

    compile_status = memory_status or InternalAnswerStatus.ABSENT
    for scored in scan_result.signals:
        store.upsert_signal(scored.signal)
        store.upsert_lineage_receipt(scored.receipt)
        store.link_signal_receipt(
            project, scored.signal.identity, scored.receipt.identity
        )

        compiled = compile_question(
            scored,
            project=project,
            repository_key=repository_key,
            authorization=authorization,
            internal_answer_status=compile_status,
            now=now,
            budget=DEFAULT_JOB_BUDGET,
            existing=existing_status_by_key,
        )
        question = compiled.question
        if question is not None:
            store.upsert_research_question(question)
            compiled_questions.append(question)
            existing_status_by_key[question.dedup_key] = question.status
            retrieval_plans.append(
                plan_retrieval(
                    RetrievalQuery(
                        text=question.question_text,
                        exact_identities=tuple(scored.signal.entity_refs[:1]),
                        allow_external=authorization.external_access,
                    )
                )
            )
            if question.status is QuestionStatus.OPEN:
                open_questions += 1
                store.record_question_job(project, question.dedup_key, job.identity)

        discovery: DiscoveryRun | None = None
        external_eligible = question is not None and question.status is QuestionStatus.OPEN
        if external_eligible and replayed:
            # Exact immutable replay must not pay a second network bill.
            pass
        elif external_eligible and not internal_check_safe:
            pass
        elif external_eligible and (
            not authorization.external_access or not effective_privacy_policy.allow_export
        ):
            pass
        elif external_eligible and providers.external_discovery is None:
            pass
        elif external_eligible:
            try:
                availability = providers.external_discovery.available()
                if availability.available:
                    discovery_attempted += 1
                    discovery = discover(
                        question,
                        job,
                        authorization,
                        providers,
                        seen_locators=frozenset(),
                        privacy_policy=effective_privacy_policy,
                        lineage_receipt=scored.receipt,
                    )
                    discovery_runs.append(discovery)
                    if "budget" in discovery.stopped_reason.lower():
                        discovery_budget_stops += 1
                else:
                    pass
            except Exception:
                # External failure never erases the valid internal branch.
                discovery_failures += 1

        bundle, evidence_refs = _evidence_bundle_for_signal(
            scored, project=project, now=now
        )
        candidates = [
            ClaimCandidate(
                topic=(
                    abstract_concept(scored.paths[0], repository_key=repository_key)
                    if scored.paths else scored.signal.signal_kind
                ),
                statement=scored.signal.summary,
                claim_kind=ClaimKind.DERIVED,
                evidence_refs=evidence_refs,
                supports=True,
            )
        ]
        try:
            bundle = _augment_with_external_evidence(
                bundle,
                candidates,
                discovery=discovery,
                providers=providers,
                project=project,
                now=now,
            )
        except Exception:
            verification_degraded = True
            # Keep the already-grounded internal bundle; do not fabricate an
            # external evidence item after a failed fetch/parse boundary.

        try:
            result = synthesize(
                bundle,
                tuple(candidates),
                authorization,
                now=now,
                lineage_receipt=scored.receipt,
            )
        except Exception:
            synthesis_failures += 1
            continue
        if result.insight is not None:
            store.upsert_insight(result.insight)
            insights.append(result.insight)
            insight_bundles.append((result.insight, bundle))
            insight_context[result.insight.identity.canonical] = (scored, question)

    stages[RuntimeStage.PLAN_RETRIEVAL] = _outcome(
        RuntimeStage.PLAN_RETRIEVAL,
        StageExecutionStatus.COMPLETED if retrieval_plans else StageExecutionStatus.SKIPPED,
        "repo_intelligence.federated_retrieval.plan_retrieval",
        reason=None if retrieval_plans else StageReasonCode.ABSENCE,
        detail=(
            f"planned {len(retrieval_plans)} bounded retrieval paths"
            if retrieval_plans else "no research question required a retrieval plan"
        ),
    )
    stages[RuntimeStage.ROUTE_CHEAPEST_QUALIFIED_RESOLVER] = _outcome(
        RuntimeStage.ROUTE_CHEAPEST_QUALIFIED_RESOLVER,
        StageExecutionStatus.COMPLETED if scan_result.signals else StageExecutionStatus.SKIPPED,
        "repo_intelligence_pipeline deterministic/local routing gate",
        reason=None if scan_result.signals else StageReasonCode.ABSENCE,
        detail=(
            "deterministic local evidence is canonical first rung; adaptive cost_quality.route is library-only until a production executor exists"
            if scan_result.signals else "no signal required a resolver"
        ),
    )

    if open_questions == 0:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence.discovery.discover",
            reason=StageReasonCode.ABSENCE,
            detail="no OPEN research question required external discovery",
        )
    elif replayed:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence.discovery.discover",
            reason=StageReasonCode.IDEMPOTENT_REPLAY,
            detail="identical completed job replay; external spend not repeated",
        )
    elif not internal_check_safe:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence.discovery.discover",
            reason=(
                StageReasonCode.INTERNAL_ERROR
                if memory_outcome.status is StageExecutionStatus.FAILED
                else StageReasonCode.PROVIDER_UNAVAILABLE
            ),
            detail="internal sufficiency could not be qualified; fail-closed external escalation",
        )
    elif not authorization.external_access or not effective_privacy_policy.allow_export:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence.discovery.discover",
            reason=StageReasonCode.POLICY_DENIAL,
            detail="project authorization or privacy policy denied external export",
        )
    elif providers.external_discovery is None:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence.discovery.discover",
            reason=StageReasonCode.PROVIDER_UNAVAILABLE,
            detail="external discovery provider is not configured",
        )
    elif discovery_failures:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.DEGRADED,
            "repo_intelligence.discovery.discover",
            reason=StageReasonCode.INTERNAL_ERROR,
            detail=f"{discovery_failures} external provider operation(s) failed; internal path retained",
        )
    elif discovery_budget_stops:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.DEGRADED,
            "repo_intelligence.discovery.discover",
            reason=StageReasonCode.BUDGET_STOP,
            detail=f"budget stopped {discovery_budget_stops} discovery operation(s)",
        )
    elif discovery_attempted:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.COMPLETED,
            "repo_intelligence.discovery.discover",
            detail=f"executed {discovery_attempted} bounded discovery operation(s)",
        )
    else:
        external_stage = _outcome(
            RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence.discovery.discover",
            reason=StageReasonCode.PROVIDER_UNAVAILABLE,
            detail="external provider reported unavailable",
        )
    stages[RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY] = external_stage

    stages[RuntimeStage.VERIFY_EVIDENCE] = _outcome(
        RuntimeStage.VERIFY_EVIDENCE,
        StageExecutionStatus.DEGRADED if verification_degraded else (
            StageExecutionStatus.COMPLETED if scan_result.signals else StageExecutionStatus.SKIPPED
        ),
        "repo_intelligence_pipeline._augment_with_external_evidence",
        reason=(
            StageReasonCode.INTERNAL_ERROR if verification_degraded else
            (None if scan_result.signals else StageReasonCode.ABSENCE)
        ),
        detail=(
            "an external fetch/parse failed; internal evidence remained authoritative"
            if verification_degraded else
            ("internal evidence bundles verified; only fetched digested external content may join" if scan_result.signals else "no evidence bundle required verification")
        ),
    )
    stages[RuntimeStage.SYNTHESIZE] = _outcome(
        RuntimeStage.SYNTHESIZE,
        StageExecutionStatus.DEGRADED if synthesis_failures else (
            StageExecutionStatus.COMPLETED if scan_result.signals else StageExecutionStatus.SKIPPED
        ),
        "repo_intelligence.synthesis.synthesize",
        reason=(
            StageReasonCode.INTERNAL_ERROR if synthesis_failures else
            (None if scan_result.signals else StageReasonCode.ABSENCE)
        ),
        detail=(
            f"{synthesis_failures} synthesis operation(s) failed; {len(insights)} insight(s) retained"
            if synthesis_failures else f"synthesized {len(insights)} evidence-backed insight(s)"
        ),
    )

    graph = build_project_graph(
        project,
        repository_key,
        entity_refs=refs_by_path.values(),
        signals=scan_result.signals,
        insights=insight_bundles,
        questions=compiled_questions,
        exposures=store.list_exposures(project),
        outcomes=store.list_learning_outcomes(project),
        now=now,
    )
    graph_degraded = False
    if providers.graph_projection is not None:
        try:
            providers.graph_projection.rebuild(project, graph.links)
        except Exception:
            graph_degraded = True
    stages[RuntimeStage.GRAPH_FUSION] = _outcome(
        RuntimeStage.GRAPH_FUSION,
        StageExecutionStatus.DEGRADED if graph_degraded else StageExecutionStatus.COMPLETED,
        "repo_intelligence.project_graph.build_project_graph",
        reason=StageReasonCode.INTERNAL_ERROR if graph_degraded else None,
        detail=(
            "local graph built but projection persistence failed"
            if graph_degraded else f"built canonical rebuildable graph with {len(graph.links)} link(s)"
        ),
    )

    decision: TerminalDecision | None = None
    decision_candidate: TerminalCandidate | None = None
    candidates_by_insight: list[TerminalCandidate] = []
    exposable = [
        insight for insight in store.list_insights(project)
        if insight.proactively_exposable()
    ]
    for insight in exposable:
        context = insight_context.get(insight.identity.canonical)
        if context is None:
            continue
        scored, question = context
        candidates_by_insight.append(
            _terminal_candidate(
                insight,
                question,
                scored,
                dismissal_count=store.dismissal_count(project, insight.identity.canonical),
            )
        )
    if candidates_by_insight:
        decision = decide_terminal_card(
            tuple(candidates_by_insight),
            authorization,
            now=now,
            history=store.list_exposures(project),
            context=terminal_context,
            user_pull=user_pull,
        )
        decision = _stable_exposure(decision, job)
        decision_candidate = next(
            (
                candidate for candidate in candidates_by_insight
                if candidate.insight.identity == decision.exposure.insight
            ),
            None,
        )
        stages[RuntimeStage.ATTENTION_RANK] = _outcome(
            RuntimeStage.ATTENTION_RANK,
            StageExecutionStatus.COMPLETED,
            "repo_intelligence.terminal_learning.decide_terminal_card",
            detail="terminal_learning is the sole production attention owner in Execution 01; RI-14 attention remains library-only",
        )
        if replayed:
            stages[RuntimeStage.EXPOSE] = _outcome(
                RuntimeStage.EXPOSE,
                StageExecutionStatus.SKIPPED,
                "repo_intelligence_pipeline + RepoIntelligenceStore.append_exposure",
                reason=StageReasonCode.IDEMPOTENT_REPLAY,
                detail="identical completed job replay; exposure history not duplicated",
            )
        else:
            store.append_exposure(decision.exposure)
            if decision.card is None:
                suppression = (decision.reason or "").lower()
                reason = (
                    StageReasonCode.BUDGET_STOP if "budget" in suppression else
                    StageReasonCode.STALE_STATE if "stale" in suppression or "superseded" in suppression else
                    StageReasonCode.POLICY_DENIAL
                )
                stages[RuntimeStage.EXPOSE] = _outcome(
                    RuntimeStage.EXPOSE,
                    StageExecutionStatus.SKIPPED,
                    "repo_intelligence_pipeline + RepoIntelligenceStore.append_exposure",
                    reason=reason,
                    detail=decision.reason,
                )
            else:
                stages[RuntimeStage.EXPOSE] = _outcome(
                    RuntimeStage.EXPOSE,
                    StageExecutionStatus.COMPLETED,
                    "repo_intelligence_pipeline + RepoIntelligenceStore.append_exposure",
                    detail=f"recorded one {decision.exposure.channel.value} exposure",
                )
    else:
        stages[RuntimeStage.ATTENTION_RANK] = _outcome(
            RuntimeStage.ATTENTION_RANK,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence.terminal_learning.decide_terminal_card",
            reason=StageReasonCode.ABSENCE,
            detail="no current insight had both lineage and current-run context",
        )
        stages[RuntimeStage.EXPOSE] = _outcome(
            RuntimeStage.EXPOSE,
            StageExecutionStatus.SKIPPED,
            "repo_intelligence_pipeline + RepoIntelligenceStore.append_exposure",
            reason=StageReasonCode.ABSENCE,
            detail="no attention candidate was available",
        )

    stages[RuntimeStage.RECORD_OUTCOME] = _outcome(
        RuntimeStage.RECORD_OUTCOME,
        StageExecutionStatus.SKIPPED,
        "repo_intelligence_pipeline.record_feedback / associate_learning_outcome",
        reason=StageReasonCode.NOT_APPLICABLE,
        detail="outcomes are recorded only when a real later user/Performance event occurs",
    )
    stages[RuntimeStage.LEARN] = _outcome(
        RuntimeStage.LEARN,
        StageExecutionStatus.SKIPPED,
        "repo_intelligence.learning_loop.ContinuousLearningLoop",
        reason=StageReasonCode.DEFERRED,
        detail="continuous background scheduler is not a production runtime owner; explicit bounded invocation remains canonical",
    )

    completed_job = job if replayed else replace(
        job, status=JobStatus.COMPLETED, completed_at=now
    )
    if not replayed:
        store.upsert_job(completed_job)
    store.record_pipeline_run(
        project,
        now=now,
        window_end=now,
        memory_status=memory_status,
    )
    ordered = _ordered_stage_outcomes(stages)
    degraded = sum(
        item.status in (StageExecutionStatus.DEGRADED, StageExecutionStatus.FAILED)
        for item in ordered
    )
    stopped_reason = (
        "bounded pipeline pass completed"
        + (" (idempotent replay; expensive/event writes suppressed)" if replayed else "")
        + (f" with {degraded} degraded/failed stage(s)" if degraded else "")
    )
    return PipelineRunResult(
        project=project,
        job=completed_job,
        signals_detected=len(scan_result.signals),
        questions_compiled=tuple(compiled_questions),
        discovery_runs=tuple(discovery_runs),
        insights_synthesized=tuple(insights),
        graph=graph,
        decision=decision,
        decision_candidate=decision_candidate,
        stopped_reason=stopped_reason,
        stage_outcomes=ordered,
        performance_coverage=coverage,
        retrieval_plans=tuple(retrieval_plans),
    )


def record_feedback(
    store: RepoIntelligenceStore,
    project: Identity,
    authorization: RepoIntelligenceAuthorization,
    exposure_identity_canonical: str,
    outcome: ExposureOutcome,
    *,
    now: datetime,
) -> Exposure:
    """Record a real user feedback event against an existing exposure."""
    ensure_same_project(authorization, project=project)
    exposure = store.get_exposure(project, exposure_identity_canonical)
    if exposure is None:
        raise KeyError(f"unknown exposure: {exposure_identity_canonical}")
    store.record_exposure_feedback(project, exposure_identity_canonical, outcome, now=now)
    if outcome is not exposure.outcome:
        feedback_event = Exposure(
            identity=new_event_identity(RepoIntelligenceKind.EXPOSURE),
            project=project,
            insight=exposure.insight,
            channel=ExposureChannel.USER_PULL,
            outcome=outcome,
            surface=exposure.surface,
            occurred_at=now,
        )
        store.append_exposure(feedback_event)
    return exposure


def associate_learning_outcome(
    store: RepoIntelligenceStore,
    project: Identity,
    authorization: RepoIntelligenceAuthorization,
    exposure_identity_canonical: str,
    *,
    now: datetime,
    window: timedelta = timedelta(days=7),
    performance_refs: tuple[str, ...] = (),
    association: AssociationKind = AssociationKind.INCONCLUSIVE,
) -> LearningOutcome:
    """Record a later Performance association, never a causal claim."""
    ensure_same_project(authorization, project=project)
    exposure = store.get_exposure(project, exposure_identity_canonical)
    if exposure is None:
        raise KeyError(f"unknown exposure: {exposure_identity_canonical}")
    identity = new_event_identity(RepoIntelligenceKind.LEARNING_OUTCOME)
    outcome = LearningOutcome(
        identity=identity,
        project=project,
        exposure=exposure.identity,
        insight=exposure.insight,
        association=association,
        claim_kind=(
            ClaimKind.STATISTICAL
            if association is not AssociationKind.INCONCLUSIVE
            else ClaimKind.UNKNOWN
        ),
        method=DERIVATION_METHOD,
        method_version=DERIVATION_VERSION,
        uncertainty="association observed after exposure; not evidence of causality",
        window_start=exposure.occurred_at,
        window_end=exposure.occurred_at + window,
        created_at=now,
        associated_performance_refs=performance_refs,
    )
    store.append_learning_outcome(outcome)
    return outcome


__all__ = [
    "PERFORMANCE_HARD_LIMIT",
    "PERFORMANCE_PAGE_SIZE",
    "PipelineRunResult",
    "associate_learning_outcome",
    "record_feedback",
    "run_pipeline",
]
