"""Execution RI-13's fusion query surfaces: composed, project-scoped reads.

Mirrors ``query_api.PerformanceQueryAPI``'s shape exactly: a small read
facade with no storage of its own, backed by an already-open
``RepoIntelligenceStore``, authorized before every read. Every method here
composes records the store already persists (signals, receipts, questions,
jobs, exposures, outcomes) -- it never derives a new fact the pipeline
itself did not already produce and persist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .repo_intelligence.attention import AttentionBudgetLimits, AttentionSpend, attention_budget_allows, attention_spend
from .repo_intelligence.authorization import RepoIntelligenceAuthorization, ensure_same_project
from .repo_intelligence.contracts import (
    AnalogyRecord,
    Exposure,
    Identity,
    InternalAnswerStatus,
    InternalSignal,
    LearningOutcome,
    LineageReceipt,
    ProjectIntelligenceJob,
    ResearchQuestion,
)
from .repo_intelligence.release_metric import ReleaseMetric, compute_release_metric
from .repo_intelligence_fusion import classify_unusualness, match_prior_internal_answer
from .repo_intelligence_store import RepoIntelligenceStore


@dataclass(frozen=True, slots=True)
class TopicNow:
    """Why a signal is surfaced now: its own basis plus any compiled question's why-now.

    ``unusual`` and ``prior_internal_answer_reference`` are best-effort
    annotations (Execution RI-13, reusing ``anomaly.py``/``personal_learning.py``
    via ``repo_intelligence_fusion``) -- ``None`` means "not enough same-kind
    history to say," never a fabricated "no."
    """

    signal_summary: str
    signal_window_end_iso: str
    question_why_now: str | None
    question_status: str | None
    unusual: bool | None = None
    prior_internal_answer_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ExposureWithOutcomes:
    exposure: Exposure
    outcomes: tuple[LearningOutcome, ...]


class RepoIntelligenceQueryAPI:
    """Read-only fusion facade over one project's already-persisted Repo Intelligent state."""

    def __init__(self, store: RepoIntelligenceStore, project: Identity) -> None:
        self._store = store
        self._project = project

    def _authorize(self, authorization: RepoIntelligenceAuthorization) -> None:
        ensure_same_project(authorization, project=self._project)

    def active_learning_pressures(
        self, authorization: RepoIntelligenceAuthorization, *, min_confidence: float = 0.0
    ) -> tuple[InternalSignal, ...]:
        """Currently-persisted signals at or above a confidence floor, most-confident first."""
        self._authorize(authorization)
        signals = self._store.list_signals(self._project)
        selected = tuple(s for s in signals if (s.confidence or 0.0) >= min_confidence)
        return tuple(sorted(selected, key=lambda s: (-(s.confidence or 0.0), s.identity.canonical)))

    def _questions_triggered_by(self, signal_identity_canonical: str) -> tuple[ResearchQuestion, ...]:
        questions = self._store.list_research_questions(self._project)
        return tuple(q for q in questions if signal_identity_canonical in q.triggered_by)

    def why_this_topic_now(self, authorization: RepoIntelligenceAuthorization, signal_identity_canonical: str) -> TopicNow | None:
        """Compose the signal's own basis with any compiled question's why-now field.

        Also annotates, best-effort: whether this signal is statistically
        unusual against same-kind history (``fusion.classify_unusualness``),
        and whether a prior internally-answered question already covers this
        need (``fusion.match_prior_internal_answer``) -- unusual is never
        automatically bad, and a match is not automatically fresh; both are
        just visible in the read, never invented when there isn't enough
        history to say.
        """
        self._authorize(authorization)
        signals = self._store.list_signals(self._project)
        signal = next((s for s in signals if s.identity.canonical == signal_identity_canonical), None)
        if signal is None:
            return None
        questions = self._questions_triggered_by(signal_identity_canonical)
        question = questions[0] if questions else None

        # ``classify_unusualness`` requires history pre-scoped to the same
        # entity -- same signal_kind alone would mix unrelated files/paths
        # into one baseline. No entity_refs at all means we cannot scope
        # safely, so history stays empty and ``unusual`` stays None rather
        # than fabricating a cross-entity comparison.
        same_entity = frozenset(signal.entity_refs)
        history = tuple(
            s for s in signals
            if s.signal_kind == signal.signal_kind
            and s.identity != signal.identity
            and same_entity
            and frozenset(s.entity_refs) & same_entity
        )
        unusual = bool(classify_unusualness(history, signal).findings) if history else None

        prior_reference = None
        if question is not None:
            concept = question.dedup_key.partition("|")[2] or question.dedup_key
            answered = self._store.list_research_questions(self._project)
            match = match_prior_internal_answer(signal.signal_kind, concept, self._project.canonical, answered)
            prior_reference = match.record_id if match is not None else None

        return TopicNow(
            signal_summary=signal.summary,
            signal_window_end_iso=signal.window_end.isoformat(),
            question_why_now=question.why_now if question is not None else None,
            question_status=question.status.value if question is not None else None,
            unusual=unusual,
            prior_internal_answer_reference=prior_reference,
        )

    def evidence_behind_pressure(
        self, authorization: RepoIntelligenceAuthorization, signal_identity_canonical: str
    ) -> LineageReceipt | None:
        """The Performance Lineage Receipt backing one signal, if it was ever linked."""
        self._authorize(authorization)
        receipt_id = self._store.receipt_identity_for_signal(self._project, signal_identity_canonical)
        if receipt_id is None:
            return None
        return self._store.get_lineage_receipt(self._project, receipt_id)

    def internal_knowledge_sufficiency(self, authorization: RepoIntelligenceAuthorization) -> InternalAnswerStatus | None:
        """The Memory/internal-sufficiency status recorded by the most recent pipeline pass; ``None`` if never run."""
        self._authorize(authorization)
        return self._store.last_memory_status(self._project)

    def research_jobs_for_pressure(
        self, authorization: RepoIntelligenceAuthorization, signal_identity_canonical: str
    ) -> tuple[ProjectIntelligenceJob, ...]:
        """Jobs whose run compiled an OPEN question from this signal."""
        self._authorize(authorization)
        job_ids: list[str] = []
        for question in self._questions_triggered_by(signal_identity_canonical):
            for job_id in self._store.job_identities_for_question(self._project, question.dedup_key):
                if job_id not in job_ids:
                    job_ids.append(job_id)
        jobs = (self._store.get_job(self._project, job_id) for job_id in job_ids)
        return tuple(job for job in jobs if job is not None)

    def exposure_outcomes(self, authorization: RepoIntelligenceAuthorization) -> tuple[ExposureWithOutcomes, ...]:
        """Every exposure paired with any later, still-associative learning outcomes."""
        self._authorize(authorization)
        outcomes = self._store.list_learning_outcomes(self._project)
        result = []
        for exposure in self._store.list_exposures(self._project):
            matched = tuple(o for o in outcomes if o.exposure == exposure.identity)
            result.append(ExposureWithOutcomes(exposure, matched))
        return tuple(result)

    def active_analogies(
        self, authorization: RepoIntelligenceAuthorization, *, now: datetime, min_confidence: float = 0.0
    ) -> tuple[AnalogyRecord, ...]:
        """Not-stale, not-superseded analogy records at or above a confidence floor (Execution RI-14)."""
        self._authorize(authorization)
        records = self._store.list_analogy_records(self._project)
        selected = tuple(
            r for r in records if r.confidence >= min_confidence and not r.is_stale(now)
        )
        return tuple(sorted(selected, key=lambda r: (-r.confidence, r.identity.canonical)))

    def attention_budget_status(
        self, authorization: RepoIntelligenceAuthorization, *, now: datetime, limits: AttentionBudgetLimits
    ) -> tuple[AttentionSpend, bool]:
        """Attention already spent in the ledger's window plus whether budget remains (Execution RI-14).

        Independent of any compute budget: this reads only durable
        ``Exposure`` history, never the cost ledger.
        """
        self._authorize(authorization)
        spend = attention_spend(self._store.list_exposures(self._project), now=now, window=limits.window)
        return spend, attention_budget_allows(spend, limits)

    def release_metric(self, authorization: RepoIntelligenceAuthorization) -> ReleaseMetric:
        """``useful_project_learning / (user_attention_cost + normalized_compute_cost)`` (Execution RI-14)."""
        self._authorize(authorization)
        return compute_release_metric(
            self._store.list_learning_outcomes(self._project),
            self._store.list_exposures(self._project),
            self._store.list_cost_records(self._project),
        )


__all__ = ["ExposureWithOutcomes", "RepoIntelligenceQueryAPI", "TopicNow"]
