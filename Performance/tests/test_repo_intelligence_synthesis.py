"""Evidence synthesis: grounding, contradictions, freshness, and source safety."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import EvidenceBundle, EvidenceItem, evidence_bundle_identity
from midnight_performance.repo_intelligence.sources import SourceClass, TrustClass
from midnight_performance.repo_intelligence.synthesis import ClaimCandidate, synthesize

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "synthesis-alpha")
OTHER = deterministic_identity(EntityKind.PROJECT, "synthesis-beta")
PERF = deterministic_identity(EntityKind.VERIFICATION_RUN, "synthesis-run").canonical
ENTITY = "ri:v1:project_entity_ref:00000000-0000-0000-0000-000000000001"

def bundle(captured=T0):
    items = (
        EvidenceItem(PERF, SourceClass.PERFORMANCE_EVIDENCE, TrustClass.FIRST_PARTY_LOCAL, captured),
        EvidenceItem(ENTITY, SourceClass.LIVE_REPOSITORY, TrustClass.FIRST_PARTY_LOCAL, captured),
    )
    return EvidenceBundle(evidence_bundle_identity(PROJECT, items), PROJECT, items, T0)

def claim(*, supports=True, refs=(PERF, ENTITY), topic="retry"):
    return ClaimCandidate(topic, "the authentication retry path has repeated verification friction", ClaimKind.INFERRED, refs, supports, "compare retry/backoff patterns before the next change")

class SynthesisTests(unittest.TestCase):
    def test_creates_a_bounded_regrounded_insight_without_raw_evidence(self):
        result = synthesize(bundle(), (claim(),), RepoIntelligenceAuthorization(PROJECT), now=T0)
        self.assertIsNotNone(result.insight)
        self.assertEqual(result.cited_evidence_refs, tuple(sorted((PERF, ENTITY))))
        self.assertNotIn("prompt", result.insight.statement.lower())
        self.assertEqual(result.actionable_learning_direction, "compare retry/backoff patterns before the next change")

    def test_hallucinated_citation_is_rejected_before_insight_creation(self):
        with self.assertRaises(ValueError):
            synthesize(bundle(), (claim(refs=(PERF, "ri:v1:external_source_ref:00000000-0000-0000-0000-000000000999")),), RepoIntelligenceAuthorization(PROJECT), now=T0)

    def test_contradiction_becomes_an_honest_gap(self):
        result = synthesize(bundle(), (claim(supports=True), claim(supports=False)), RepoIntelligenceAuthorization(PROJECT), now=T0)
        self.assertIsNone(result.insight)
        self.assertTrue(result.contradictions)
        self.assertIn("contradictory", result.gaps[0])

    def test_stale_evidence_does_not_produce_an_insight(self):
        result = synthesize(bundle(T0 - timedelta(days=31)), (claim(),), RepoIntelligenceAuthorization(PROJECT), now=T0)
        self.assertIsNone(result.insight)
        self.assertIn("stale evidence", result.gaps[0])

    def test_cross_project_authorization_fails_closed(self):
        with self.assertRaises(PermissionError):
            synthesize(bundle(), (claim(),), RepoIntelligenceAuthorization(OTHER), now=T0)

if __name__ == "__main__": unittest.main()
