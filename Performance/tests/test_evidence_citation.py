import unittest
from datetime import datetime, timezone

from midnight_performance import (
    EvidenceCitation,
    FeedbackReason,
    Judgment,
    OutcomeProvider,
    OutcomeReference,
    VerificationSource,
    feedback_citation,
    outcome_citation,
    verification_citation,
)
from midnight_performance.feedback import FeedbackRecord
from midnight_performance.verification import VerificationEvidence

PROJECT = "mp:v1:project:test"


class EvidenceCitationTests(unittest.TestCase):
    def test_citation_requires_reference_id_kind_and_project(self):
        with self.assertRaises(ValueError):
            EvidenceCitation("", "verification_run", PROJECT)
        with self.assertRaises(ValueError):
            EvidenceCitation("id", "", PROJECT)
        with self.assertRaises(ValueError):
            EvidenceCitation("id", "verification_run", "")

    def test_citation_rejects_naive_timestamps(self):
        with self.assertRaises(ValueError):
            EvidenceCitation("id", "verification_run", PROJECT, observed_at=datetime(2026, 1, 1))

    def test_citation_summary_is_bounded(self):
        with self.assertRaises(ValueError):
            EvidenceCitation("id", "verification_run", PROJECT, summary="x" * 281)
        EvidenceCitation("id", "verification_run", PROJECT, summary="x" * 280)  # exactly at the bound is fine

    def test_verification_citation_never_includes_raw_output(self):
        evidence = VerificationEvidence(
            "ver-1", VerificationSource.EXECUTED, "passed", 250, 0,
            "raw command output that must never leave this object", ("a.py", "b.py"),
        )
        citation = verification_citation(evidence, project=PROJECT)
        self.assertEqual(citation.reference_id, "ver-1")
        self.assertEqual(citation.evidence_kind, "verification_run")
        self.assertEqual(citation.source, "executed")
        self.assertTrue(citation.detail_available)
        self.assertNotIn("raw command output", citation.summary or "")
        self.assertIn("status=passed", citation.summary or "")
        self.assertIn("changed_files=2", citation.summary or "")

    def test_verification_citation_detail_available_false_when_no_output(self):
        evidence = VerificationEvidence("ver-2", VerificationSource.AGENT_REPORTED, "passed", None, None, "")
        citation = verification_citation(evidence, project=PROJECT)
        self.assertFalse(citation.detail_available)

    def test_feedback_citation_never_includes_free_text(self):
        record = FeedbackRecord(
            "fb-1", "run-1", "user-actor", Judgment.PARTIAL, (FeedbackReason.CORRECTNESS, FeedbackReason.SCOPE),
            free_text="raw human commentary that must never leave this object",
            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        citation = feedback_citation(record, project=PROJECT)
        self.assertEqual(citation.reference_id, "fb-1")
        self.assertEqual(citation.source, "user-actor")
        self.assertTrue(citation.detail_available)
        self.assertNotIn("raw human commentary", citation.summary or "")
        self.assertIn("judgment=partially_achieved", citation.summary or "")
        self.assertIn("correctness", citation.summary or "")

    def test_feedback_citation_detail_available_false_when_no_free_text(self):
        record = FeedbackRecord("fb-2", "run-1", "user-actor", Judgment.ACHIEVED)
        citation = feedback_citation(record, project=PROJECT)
        self.assertFalse(citation.detail_available)

    def test_outcome_citation_is_fully_structural(self):
        reference = OutcomeReference(OutcomeProvider.SECURITY, "finding", "finding-123", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        citation = outcome_citation(reference, project=PROJECT)
        self.assertEqual(citation.reference_id, "finding-123")
        self.assertEqual(citation.source, "security")
        self.assertEqual(citation.summary, "kind=finding")


if __name__ == "__main__":
    unittest.main()
