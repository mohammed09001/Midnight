"""Repo Intelligent's orchestrator: wires the already-correct stage functions together.

Implements OBSERVE -> DETECT SIGNAL -> SCORE NEED -> RETRIEVE INTERNAL ->
DECIDE EXTERNAL NEED -> DISCOVER -> VERIFY -> SYNTHESIZE -> GRAPH-LINK ->
RANK -> EXPOSE -> RECORD OUTCOME -> LEARN by literally sequencing the
existing, independently-tested pure functions in ``repo_intelligence/``.
This module contains no new domain logic of its own beyond the glue: every
decision (whether internal evidence already answers a need, whether a
question compiles, whether discovery is eligible, whether an insight earns
proactive exposure) is made by the function that already owns that rule.

Counterfactual Relevance Gate: a signal only gets a compiled, OPEN research
question when Memory/internal context does not already answer it --
``compile_question`` itself refuses to open a question once
``internal_answer_status`` is ``SUFFICIENT`` (see its docstring). External
discovery is attempted only for an OPEN question, and only when
``external_discovery`` is configured and authorized; ``discover()`` degrades
to an honest "provider unavailable" result otherwise -- the required
internal-only-capable behavior, not a special case handled here.

An insight is never queued for terminal exposure without a
``LineageReceipt``: every internal signal already carries its own receipt
from ``scan_signals``, and only a signal with a receipt is ever passed to
:func:`synthesize` as this pipeline's ``lineage_receipt``.

Scope note (confirmed for this integration pass): ``external_discovery``
stays unconfigured in production (:func:`repo_intelligence_adapters.production_providers`),
so discovered candidates are never promoted into an evidence bundle here --
a ``DiscoveredSource`` pointer without a fetched, content-digested document
is not yet evidence ("external records remain evidence, never automatically
trusted knowledge"). The optional ``fetch_parse`` branch below exists so
tests can exercise the two-sided Evidence Triangle path with fixture ports;
production never configures it this pass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .contracts import ClaimKind, EntityKind, Identity
from .privacy import PrivacyPolicy
from .query_api import QueryAuthorization
from .repo_intelligence.authorization import RepoIntelligenceAuthorization, ensure_same_project
from .repo_intelligence.contracts import (
    AssociationKind,
    BudgetCeiling,
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
from .repo_intelligence.identities import RepoIntelligenceKind
from .repo_intelligence.ports import RepoIntelligenceProviders
from .repo_intelligence.project_graph import ProjectKnowledgeGraph, build_project_graph
from .repo_intelligence.question_compiler import abstract_concept, compile_question
from .repo_intelligence.signals import ScoredSignal, scan_signals
from .repo_intelligence.sources import DEFAULT_SOURCE_TRUST, SourceClass, TrustClass
from .repo_intelligence.synthesis import ClaimCandidate, synthesize
from .repo_intelligence.terminal_learning import TerminalCandidate, TerminalContext, TerminalDecision, decide_terminal_card
from .repo_intelligence_evidence_bridge import resolve_entity_refs_by_path
from .repo_intelligence_store import RepoIntelligenceStore
from .repository_capture import RepositorySnapshot

DERIVATION_METHOD = "repo-intelligence-pipeline"
DERIVATION_VERSION = "1"
DEFAULT_JOB_BUDGET = BudgetCeiling(max_model_calls=2, max_network_requests=5, max_seconds=120.0)


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


def _memory_answer_status(providers: RepoIntelligenceProviders, project_key: str) -> InternalAnswerStatus:
    """Coarse internal-sufficiency check: any qualified Memory context at all.

    A finer per-question check (asking Memory the compiled question text)
    would require compiling the question first; ``score_path_pressure``'s
    ``knowledge_deficit`` factor and ``compile_question``'s own
    ``internal_answer_status`` gate both run on this coarser project-level
    signal this pass -- a documented simplification, not a missing gate
    (the gate that matters, "never spend external budget when internal
    evidence already answers," still holds: see ``compile_question``'s
    refusal to open a question when this status is ``SUFFICIENT``).
    """
    if providers.memory_bridge is None:
        return InternalAnswerStatus.ABSENT
    result = providers.memory_bridge.read_context(project_key, size=5)
    if not result.available:
        return InternalAnswerStatus.ABSENT
    return InternalAnswerStatus.PARTIAL if result.records else InternalAnswerStatus.ABSENT


def _build_job(project: Identity, *, now: datetime, budget: BudgetCeiling, idempotency_key: str, user_pull: bool = False) -> ProjectIntelligenceJob:
    identity = project_intelligence_job_identity(project, "continuous_learning", idempotency_key)
    return ProjectIntelligenceJob(
        identity=identity,
        project=project,
        job_kind="continuous_learning",
        idempotency_key=idempotency_key,
        trigger=JobTrigger.USER_PULL if user_pull else JobTrigger.MAINTENANCE,
        status=JobStatus.RUNNING,
        stop_condition="stop on marginal gain saturation or any configured ceiling",
        budget=budget,
        derivation_method=DERIVATION_METHOD,
        derivation_version=DERIVATION_VERSION,
        requested_at=now,
        started_at=now,
    )


def _evidence_bundle_for_signal(scored: ScoredSignal, *, project: Identity, now: datetime) -> tuple[EvidenceBundle, tuple[str, ...]]:
    """Ground one signal's own evidence as the internal (first-party) side of the bundle."""
    items = [
        EvidenceItem(
            ref=scored.signal.identity.canonical,
            source_class=SourceClass.PERFORMANCE_EVIDENCE,
            trust_class=TrustClass.FIRST_PARTY_LOCAL,
            captured_at=now,
        )
    ]
    identity = evidence_bundle_identity(project, tuple(items))
    bundle = EvidenceBundle(identity=identity, project=project, items=tuple(items), created_at=now, gaps=scored.signal.gaps)
    return bundle, (scored.signal.identity.canonical,)


def _augment_with_external_evidence(
    bundle: EvidenceBundle,
    candidates: list[ClaimCandidate],
    *,
    discovery: DiscoveryRun | None,
    providers: RepoIntelligenceProviders,
    project: Identity,
    now: datetime,
) -> EvidenceBundle:
    """Test-only two-sided path: promote one fetched, digested source into evidence.

    Never runs in production this pass (``fetch_parse`` is unconfigured
    there); exists so the Evidence Triangle's external side is exercised by
    fixture tests without requiring a real network/model adapter.
    """
    if discovery is None or not discovery.ranked or providers.fetch_parse is None:
        return bundle
    top = discovery.ranked[0]
    if not providers.fetch_parse.available().available:
        return bundle
    document = providers.fetch_parse.fetch(top.canonical_locator, top.source.source_class)
    from .repo_intelligence.contracts import ExternalSourceRef, external_source_ref_identity

    ref_identity = external_source_ref_identity(top.source.provider, top.canonical_locator, document.text.content_digest)
    external_ref = ExternalSourceRef(
        identity=ref_identity,
        project=project,
        source_class=top.source.source_class,
        provider=top.source.provider,
        locator=top.canonical_locator,
        title=top.source.title,
        content_digest=document.text.content_digest,
        captured_at=now,
        retrieval_method="fixture-fetch",
        retrieval_version="1",
        trust_class=DEFAULT_SOURCE_TRUST.get(top.source.source_class, TrustClass.UNVERIFIED),
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
    new_identity = evidence_bundle_identity(project, items)
    return EvidenceBundle(identity=new_identity, project=project, items=items, created_at=now, gaps=bundle.gaps)


def _terminal_candidate(
    insight: ProjectInsight,
    question: ResearchQuestion | None,
    scored: ScoredSignal,
    *,
    dismissal_count: int,
) -> TerminalCandidate:
    confidence = insight.confidence if insight.confidence is not None else 0.5
    why_now = question.why_now if question is not None else (
        f"{scored.signal.signal_kind} signal observed in the window ending {scored.signal.window_end.isoformat()}"
    )
    next_action = question.stop_condition if question is not None else "review the cited internal evidence"
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
    """Run one bounded OBSERVE-through-LEARN pass and persist everything it produces."""
    ensure_same_project(authorization, project=project)
    if now.tzinfo is None:
        raise ValueError("pipeline run time must be timezone-aware")
    window_start = now - window
    project_key = project_key or repository_key
    effective_privacy_policy = privacy_policy if privacy_policy is not None else PrivacyPolicy()

    clock = providers.clock_or_default()
    snapshot = RepositorySnapshot.capture(repo_root) if repo_root.exists() else RepositorySnapshot({})
    refs_by_path = resolve_entity_refs_by_path(project, repository_key, snapshot, now=now)

    envelopes: tuple = ()
    if providers.performance_reads is not None:
        read_authorization = QueryAuthorization(project=project, allowed_kinds=frozenset(EntityKind))
        page = providers.performance_reads.query(read_authorization, limit=100)
        envelopes = page.items

    idempotency_key = hashlib.sha256(
        f"{project.canonical}|{window_start.isoformat()}|{now.isoformat()}|{len(envelopes)}".encode()
    ).hexdigest()
    job = _build_job(project, now=now, budget=DEFAULT_JOB_BUDGET, idempotency_key=idempotency_key, user_pull=user_pull)
    store.upsert_job(job)

    memory_status = _memory_answer_status(providers, project_key)
    scan_result = scan_signals(
        project, repository_key, envelopes=envelopes, refs_by_path=refs_by_path,
        window_start=window_start, window_end=now, now=now, memory_status=memory_status, job=job,
    )
    for cost in scan_result.cost_records:
        if providers.budget_meter is not None:
            providers.budget_meter.record(cost)

    existing_status_by_key = store.question_status_by_dedup_key(project)
    compiled_questions: list[ResearchQuestion] = []
    discovery_runs: list[DiscoveryRun] = []
    insights: list[ProjectInsight] = []
    insight_bundles: list[tuple[ProjectInsight, EvidenceBundle]] = []
    # Insight identity -> (originating signal, its compiled question, if any). Built
    # directly at synthesis time rather than reverse-looked-up afterward, since a
    # LineageReceipt's identity is derived from evidence refs alone and multiple
    # signal kinds detected from the same underlying evidence can legitimately
    # share one receipt identity.
    insight_context: dict[str, tuple[ScoredSignal, ResearchQuestion | None]] = {}

    for scored in scan_result.signals:
        store.upsert_signal(scored.signal)
        store.upsert_lineage_receipt(scored.receipt)
        store.link_signal_receipt(project, scored.signal.identity, scored.receipt.identity)

        compiled = compile_question(
            scored, project=project, repository_key=repository_key, authorization=authorization,
            internal_answer_status=memory_status, now=now, budget=DEFAULT_JOB_BUDGET,
            existing=existing_status_by_key,
        )
        question = compiled.question
        if question is not None:
            store.upsert_research_question(question)
            compiled_questions.append(question)
            existing_status_by_key[question.dedup_key] = question.status
            if question.status is QuestionStatus.OPEN:
                store.record_question_job(project, question.dedup_key, job.identity)

        discovery: DiscoveryRun | None = None
        if (
            question is not None
            and question.status is QuestionStatus.OPEN
            and authorization.external_access
            and effective_privacy_policy.allow_export
        ):
            # discover() itself raises PrivacyViolation rather than degrading when
            # export is disabled, so that check is made here, before calling it --
            # "export disabled" is this pipeline's honest internal-only decision,
            # not a crash. discover() already records its own CostRecord via
            # providers.budget_meter.
            discovery = discover(
                question, job, authorization, providers,
                seen_locators=frozenset(), privacy_policy=effective_privacy_policy,
                lineage_receipt=scored.receipt,
            )
            discovery_runs.append(discovery)

        bundle, evidence_refs = _evidence_bundle_for_signal(scored, project=project, now=now)
        candidates = [
            ClaimCandidate(
                topic=abstract_concept(scored.paths[0], repository_key=repository_key) if scored.paths else scored.signal.signal_kind,
                statement=scored.signal.summary,
                claim_kind=ClaimKind.DERIVED,
                evidence_refs=evidence_refs,
                supports=True,
            )
        ]
        bundle = _augment_with_external_evidence(
            bundle, candidates, discovery=discovery, providers=providers, project=project, now=now
        )

        result = synthesize(bundle, tuple(candidates), authorization, now=now, lineage_receipt=scored.receipt)
        if result.insight is not None:
            store.upsert_insight(result.insight)
            insights.append(result.insight)
            insight_bundles.append((result.insight, bundle))
            insight_context[result.insight.identity.canonical] = (scored, question)

    graph = build_project_graph(
        project, repository_key,
        entity_refs=refs_by_path.values(),
        signals=scan_result.signals,
        insights=insight_bundles,
        questions=compiled_questions,
        exposures=store.list_exposures(project),
        outcomes=store.list_learning_outcomes(project),
        now=now,
    )
    if providers.graph_projection is not None:
        providers.graph_projection.rebuild(project, graph.links)

    decision: TerminalDecision | None = None
    decision_candidate: TerminalCandidate | None = None
    exposable = [insight for insight in store.list_insights(project) if insight.proactively_exposable()]
    if exposable:
        candidates_by_insight = []
        for insight in exposable:
            context = insight_context.get(insight.identity.canonical)
            if context is None:
                # A previously-persisted insight whose signal no longer detects this
                # run (e.g. its evidence aged out of the window): excluded from this
                # run's terminal-card contention rather than guessed at.
                continue
            scored, question = context
            dismissals = store.dismissal_count(project, insight.identity.canonical)
            candidates_by_insight.append(_terminal_candidate(insight, question, scored, dismissal_count=dismissals))
        if candidates_by_insight:
            decision = decide_terminal_card(
                tuple(candidates_by_insight), authorization, now=now,
                history=store.list_exposures(project), context=terminal_context, user_pull=user_pull,
            )
            store.append_exposure(decision.exposure)
            decision_candidate = next(
                (c for c in candidates_by_insight if c.insight.identity == decision.exposure.insight), None
            )

    completed_job = replace(job, status=JobStatus.COMPLETED, completed_at=now)
    store.upsert_job(completed_job)
    store.record_pipeline_run(project, now=now, window_end=now, memory_status=memory_status)
    stopped_reason = "bounded pipeline pass completed"
    return PipelineRunResult(
        project=project, job=completed_job, signals_detected=len(scan_result.signals),
        questions_compiled=tuple(compiled_questions), discovery_runs=tuple(discovery_runs),
        insights_synthesized=tuple(insights), graph=graph, decision=decision,
        decision_candidate=decision_candidate, stopped_reason=stopped_reason,
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
    """Close the feedback loop on one already-exposed insight; unknown ids fail closed.

    Two records are written: the feedback-lookup row (keyed by this specific
    exposure id, for the bridge's "what did the user do with THIS card"
    read), and a fresh ``Exposure`` history event carrying the outcome --
    ``decide_terminal_card``'s own dismissal-limit/cooldown gate reads
    exposure *history*, not a side table, so a dismissal must appear there
    to actually suppress future proactive pushes of the same insight.
    """
    ensure_same_project(authorization, project=project)
    exposure = store.get_exposure(project, exposure_identity_canonical)
    if exposure is None:
        raise KeyError(f"unknown exposure: {exposure_identity_canonical}")
    store.record_exposure_feedback(project, exposure_identity_canonical, outcome, now=now)
    if outcome is not exposure.outcome:
        feedback_event = Exposure(
            identity=new_event_identity(RepoIntelligenceKind.EXPOSURE),
            project=project, insight=exposure.insight, channel=ExposureChannel.USER_PULL,
            outcome=outcome, surface=exposure.surface, occurred_at=now,
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
    """Record a later Performance association with an exposure, never a causal claim."""
    ensure_same_project(authorization, project=project)
    exposure = store.get_exposure(project, exposure_identity_canonical)
    if exposure is None:
        raise KeyError(f"unknown exposure: {exposure_identity_canonical}")
    identity = new_event_identity(RepoIntelligenceKind.LEARNING_OUTCOME)
    outcome = LearningOutcome(
        identity=identity, project=project, exposure=exposure.identity, insight=exposure.insight,
        association=association, claim_kind=ClaimKind.STATISTICAL if association is not AssociationKind.INCONCLUSIVE else ClaimKind.UNKNOWN,
        method=DERIVATION_METHOD, method_version=DERIVATION_VERSION, uncertainty="association observed after exposure; not evidence of causality",
        window_start=exposure.occurred_at, window_end=exposure.occurred_at + window, created_at=now,
        associated_performance_refs=performance_refs,
    )
    store.append_learning_outcome(outcome)
    return outcome


__all__ = [
    "PipelineRunResult",
    "associate_learning_outcome",
    "record_feedback",
    "run_pipeline",
]
