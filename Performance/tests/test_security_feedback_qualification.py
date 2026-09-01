from datetime import datetime, timezone

from midnight_performance import (
    FeedbackFailure, FeedbackRecord, Judgment, MultiSignalLabel, OutcomeProvider,
    OutcomeReference, QuestionCandidate, SecurityFailure, SecurityFeedbackQualificationState,
    SecurityQualificationInput, bounded_security_context, qualify_feedback, qualify_security,
)


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def _security(**changes):
    values = dict(prompt_run_id="run-1", episode_id="episode-1", finding=OutcomeReference(OutcomeProvider.SECURITY, "finding", "sec-1"), candidate_change_set_ids=("change-1",), remediation=OutcomeReference(OutcomeProvider.SECURITY, "remediation_verified", "remediation-1"))
    values.update(changes)
    return SecurityQualificationInput(**values)


def test_security_links_only_references_and_returns_bounded_context():
    result = qualify_security(_security())
    assert result.state is SecurityFeedbackQualificationState.QUALIFIED
    assert result.association is not None
    assert result.association.outcome.external_id == "sec-1"
    assert "authoritative" in result.association.uncertainty

    context = bounded_security_context(_security(candidate_change_set_ids=("a", "b", "c")), maximum_change_sets=2)
    assert context.change_set_ids == ("a", "b")
    assert context.truncated


def test_security_adversarial_failures_degrade_or_reject_without_copying_findings():
    degraded = qualify_security(_security(candidate_change_set_ids=("a", "b"), remediation=None, failed_verification_ids=("verify-1",), finding_reintroduced=True))
    assert degraded.state is SecurityFeedbackQualificationState.DEGRADED
    assert set(degraded.failures) == {SecurityFailure.MULTIPLE_CANDIDATE_CHANGE_SETS, SecurityFailure.FAILED_REMEDIATION, SecurityFailure.FINDING_REINTRODUCED, SecurityFailure.REMEDIATION_UNCONFIRMED}

    unavailable = qualify_security(_security(security_available=False))
    assert unavailable.state is SecurityFeedbackQualificationState.REJECTED
    assert unavailable.association is None
    assert unavailable.claim_kind.value == "unknown"

    unverified = qualify_security(_security(remediation=OutcomeReference(OutcomeProvider.SECURITY, "remediation_claimed", "remediation-2")))
    assert unverified.state is SecurityFeedbackQualificationState.DEGRADED
    assert SecurityFailure.REMEDIATION_UNCONFIRMED in unverified.failures


def test_feedback_qualification_preserves_revision_uncertainty_question_selection_and_disagreement():
    original = FeedbackRecord("f1", "run-1", "user", Judgment.NOT_ACHIEVED, submitted_at=NOW)
    revised = FeedbackRecord("f2", "run-1", "user", Judgment.UNCERTAIN, confidence=.3, uncertainty="not enough evidence", submitted_at=NOW.replace(second=1), revises_id="f1")
    result = qualify_feedback("run-1", (original, revised), (QuestionCandidate("run-1", .9, .7, .8, .8),), (MultiSignalLabel("1", "not_achieved", "passed", "changed", None),))
    assert result.current_feedback == (revised,)
    assert result.active_question is not None
    assert result.state is SecurityFeedbackQualificationState.DEGRADED
    assert result.failures == (FeedbackFailure.SIGNAL_DISAGREEMENT,)
    assert "ground truth" in result.uncertainty


def test_feedback_revision_failures_and_absence_are_explicit():
    cross = FeedbackRecord("f1", "other", "user", Judgment.ACHIEVED, submitted_at=NOW)
    child = FeedbackRecord("f2", "run-1", "user", Judgment.PARTIAL, submitted_at=NOW.replace(second=1), revises_id="f1")
    result = qualify_feedback("run-1", (cross, child))
    assert FeedbackFailure.CROSS_RUN_REVISION in result.failures
    assert qualify_feedback("missing", ()).failures == (FeedbackFailure.NO_FEEDBACK,)
