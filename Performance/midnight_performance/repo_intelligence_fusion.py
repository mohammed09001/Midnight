"""Execution RI-13: fusion helpers that reuse Performance's own canonical modules.

Lives outside ``repo_intelligence/`` (the provider-neutral foundation
package, whose own architecture test restricts it to a narrow canonical
Performance surface) alongside ``repo_intelligence_pipeline.py``,
``repo_intelligence_store.py``, and ``repo_intelligence_adapters.py`` --
the integration layer that is allowed to reach further into Performance's
own modules, the same way ``repo_intelligence_adapters.AIAccountingBudgetMeter``
already reaches ``ai_accounting``.

Neither function here invents a second unusualness heuristic or a second
user-history matcher. ``classify_unusualness`` calls straight into
``midnight_performance.anomaly`` (the same median/MAD robust-z baseline used
for prompt-run anomalies); ``match_prior_internal_answer`` calls straight
into ``midnight_performance.personal_learning`` (the same component/task_type
matcher used for advisory next-time suggestions). Both degrade honestly --
too little history yields an unmeasured baseline or no match, never an
invented value.
"""

from __future__ import annotations

from .anomaly import AnomalyReport, DEFAULT_MIN_BASELINE, build_baseline, detect_anomalies
from .dataset import DatasetRow
from .personal_learning import ExperienceRecord, MatchedExperience, match_history
from .repo_intelligence.contracts import InternalSignal, QuestionStatus, ResearchQuestion

_UNUSUALNESS_FEATURES = ("confidence",)


def _signal_row(signal: InternalSignal) -> DatasetRow:
    return DatasetRow(
        prompt_run_id=signal.identity.canonical,
        observed_at=signal.window_end,
        features={
            "confidence": signal.confidence if signal.confidence is not None else 0.0,
        },
        label=None,
        label_confidence=None,
        agent_metadata={},
        lineage=tuple(signal.evidence_ids[:8]),
    )


def classify_unusualness(
    history: tuple[InternalSignal, ...],
    current: InternalSignal,
    *,
    min_baseline: int = DEFAULT_MIN_BASELINE,
) -> AnomalyReport:
    """Is ``current`` statistically unusual against same-entity history?

    Callers must pre-scope ``history`` to signals for the same entity/path as
    ``current`` -- this function does no entity resolution of its own.
    Unusual is never automatically bad: pair this with the signal's own
    friction factor (``LearningPressure.factor(FRICTION)``) to tell "an
    unusually large healthy refactor" apart from "an unusually large chronic
    failure."
    """
    rows = tuple(_signal_row(item) for item in history)
    profile = build_baseline(rows, list(_UNUSUALNESS_FEATURES), min_baseline=min_baseline)
    return detect_anomalies(profile, (_signal_row(current),))


def _question_to_experience(question: ResearchQuestion, project_id: str) -> ExperienceRecord:
    task_type, _, component = question.dedup_key.partition("|")
    return ExperienceRecord(
        id=question.identity.canonical,
        user_id=None,
        project_id=project_id,
        component=component or question.dedup_key,
        task_type=task_type or "unknown",
        provider=None,
        observed_at=question.created_at,
        measures={},
        evidence=question.triggered_by,
    )


def match_prior_internal_answer(
    signal_kind: str,
    concept: str,
    project_id: str,
    answered_questions: tuple[ResearchQuestion, ...],
    *,
    minimum: float = 0.75,
) -> MatchedExperience | None:
    """Does a prior internally-answered question already cover this need?

    Only questions closed as ``ANSWERED_INTERNAL`` are eligible history --
    an open or externally-researched question is not yet a "prior answer."
    ``minimum`` defaults to 0.75 (three of ``match_history``'s four
    dimensions) so that a bare project+task_type match is not mistaken for
    "the same component" -- the component itself must also match.
    Freshness of the match is the caller's call (compare the matched
    question's ``created_at`` against a staleness window); this function
    only answers "is there a match at all," reusing
    ``personal_learning.match_history`` for that comparison.
    """
    answered = tuple(q for q in answered_questions if q.status is QuestionStatus.ANSWERED_INTERNAL)
    if not answered:
        return None
    query = ExperienceRecord(
        id="__query__", user_id=None, project_id=project_id, component=concept,
        task_type=signal_kind, provider=None, observed_at=answered[0].created_at,
        measures={}, evidence=(),
    )
    history = tuple(_question_to_experience(q, project_id) for q in answered)
    matches = match_history(query, history, minimum=minimum)
    return matches[0] if matches else None


__all__ = ["classify_unusualness", "match_prior_internal_answer"]
