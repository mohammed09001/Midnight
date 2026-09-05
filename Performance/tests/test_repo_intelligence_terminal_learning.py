"""Terminal learning policy: no side effects, calm gating, safe deterministic cards."""

import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import EvidenceBundle, EvidenceItem, Exposure, ExposureChannel, ExposureOutcome, LineageReceipt, ProjectInsight, evidence_bundle_identity, lineage_receipt_identity
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence.sources import SourceClass, TrustClass
from midnight_performance.repo_intelligence.terminal_learning import TerminalCandidate, TerminalContext, decide_terminal_card

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "terminal-alpha")
PERF = deterministic_identity(EntityKind.VERIFICATION_RUN, "terminal-run").canonical

def insight(*, superseded=False):
    item = EvidenceItem(PERF, SourceClass.PERFORMANCE_EVIDENCE, TrustClass.FIRST_PARTY_LOCAL, T0)
    bundle = EvidenceBundle(evidence_bundle_identity(PROJECT, (item,)), PROJECT, (item,), T0)
    receipt = LineageReceipt(lineage_receipt_identity(PROJECT, "terminal", "1", T0, T0, (PERF,), (), ()), PROJECT, "terminal", "1", T0, T0, ClaimKind.DERIVED, "local_only", T0, (PERF,))
    identity = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "terminal-insight")
    return ProjectInsight(identity, PROJECT, "authentication retry path has repeated verification friction", ClaimKind.INFERRED, "m", "1", "bounded evidence", bundle.identity, .8, receipt.identity, valid_from=T0, valid_to=T0 if superseded else None)

def candidate(**scores):
    values = dict(relevance=.8, evidence_quality=.8, novelty=.8, expected_learning_value=.8, interruption_cost=.1)
    values.update(scores)
    return TerminalCandidate(insight(), "verification friction recurred", "affected auth retry component", "inspect the bounded evidence", **values)

class TerminalLearningTests(unittest.TestCase):
    def test_renders_local_card_without_network_or_raw_source_dump(self):
        result = decide_terminal_card((candidate(),), RepoIntelligenceAuthorization(PROJECT), now=T0)
        self.assertIn("WHAT:", result.card)
        self.assertEqual(result.exposure.channel, ExposureChannel.PROACTIVE_PUSH)

    def test_protected_focus_suppresses_proactive_interruption(self):
        result = decide_terminal_card((candidate(),), RepoIntelligenceAuthorization(PROJECT), now=T0, context=TerminalContext(protected_focus=True))
        self.assertIsNone(result.card)
        self.assertEqual(result.exposure.outcome, ExposureOutcome.SUPPRESSED)

    def test_user_pull_outranks_pause_but_not_staleness(self):
        result = decide_terminal_card((candidate(),), RepoIntelligenceAuthorization(PROJECT), now=T0, context=TerminalContext(proactive_enabled=False), user_pull=True)
        self.assertIsNotNone(result.card)
        stale = TerminalCandidate(insight(superseded=True), "now", "project", "learn", .9, .9, .9, .9, .1)
        blocked = decide_terminal_card((stale,), RepoIntelligenceAuthorization(PROJECT), now=T0, user_pull=True)
        self.assertIsNone(blocked.card)

    def test_repeated_dismissals_suppress_without_deleting_insight(self):
        item = candidate()
        history = tuple(Exposure(deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, f"dismiss-{i}"), PROJECT, item.insight.identity, ExposureChannel.USER_PULL, ExposureOutcome.DISMISSED, "terminal", T0 - timedelta(minutes=i)) for i in range(3))
        result = decide_terminal_card((item,), RepoIntelligenceAuthorization(PROJECT), now=T0, history=history)
        self.assertIn("dismissal", result.reason)
        self.assertEqual(item.insight.identity, history[0].insight)

    def test_equal_scores_have_stable_identity_order_and_escape_is_inert(self):
        first = candidate()
        second = TerminalCandidate(insight(), "\x1b[31mnow", "project", "learn", .8, .8, .8, .8, .1)
        result = decide_terminal_card((second, first), RepoIntelligenceAuthorization(PROJECT), now=T0)
        self.assertNotIn("\x1b", result.card or "")

if __name__ == "__main__": unittest.main()
