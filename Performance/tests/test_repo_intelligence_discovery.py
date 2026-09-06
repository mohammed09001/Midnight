"""Discovery runner: authorization, bounded spend, ranking, adversarial inputs."""

import unittest
from datetime import datetime, timezone

from midnight_performance.contracts import ClaimKind, EntityKind, deterministic_identity
from midnight_performance.privacy import PrivacyPolicy
from midnight_performance.repo_intelligence.authorization import RepoIntelligenceAuthorization
from midnight_performance.repo_intelligence.contracts import BudgetCeiling, JobStatus, JobTrigger, LineageReceipt, ProjectIntelligenceJob, ResearchQuestion, InternalAnswerStatus, QuestionStatus
from midnight_performance.repo_intelligence.discovery import canonical_locator, discover, rank_discoveries
from midnight_performance.repo_intelligence.identities import RepoIntelligenceKind, deterministic_repo_identity
from midnight_performance.repo_intelligence.ports import BudgetGrant, BudgetUsage, DiscoveredSource, PortAvailability, RepoIntelligenceProviders
from midnight_performance.repo_intelligence.runtime_contract import StageReasonCode
from midnight_performance.repo_intelligence.sources import SourceClass

T0 = datetime(2026, 9, 4, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "discovery-alpha")
EXPORT = PrivacyPolicy(allow_export=True)

def question(status=QuestionStatus.OPEN):
    return ResearchQuestion(deterministic_repo_identity(RepoIntelligenceKind.RESEARCH_QUESTION, "q"), PROJECT, "how can token refresh failures be prevented", True, "repeated failures", ("mp:v1:verification_run:00000000-0000-0000-0000-000000000001",), "no answer", "pattern unknown", "official guidance would change answer", "one authoritative source", BudgetCeiling(max_network_requests=1), InternalAnswerStatus.ABSENT, "q", status, T0)

def job(trigger=JobTrigger.USER_PULL):
    return ProjectIntelligenceJob(deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB, "job"), PROJECT, "research", "job", trigger, JobStatus.PENDING, "one source", BudgetCeiling(max_network_requests=1), "discovery", "1", T0)

def receipt(project=PROJECT):
    return LineageReceipt(
        identity=deterministic_repo_identity(RepoIntelligenceKind.LINEAGE_RECEIPT, "r"),
        project=project, derivation_method="signal-scan", derivation_version="1",
        window_start=T0, window_end=T0, claim_kind=ClaimKind.DERIVED, privacy_decision="local_only",
        created_at=T0, performance_evidence_ids=("mp:v1:verification_run:00000000-0000-0000-0000-000000000001",),
    )

class Search:
    def __init__(self): self.calls = 0
    def available(self): return PortAvailability("external_discovery", True)
    def search(self, _question, *, limit=10):
        self.calls += 1
        return (
            DiscoveredSource("fixture", "https://github.com/example/retry/", "Popular but weak", SourceClass.GITHUB_REPOSITORY, .7),
            DiscoveredSource("fixture", "https://docs.example.com/retry", "Official retry", SourceClass.OFFICIAL_DOCS, .7),
            DiscoveredSource("fixture", "https://docs.example.com/retry#fragment", "Duplicate official", SourceClass.OFFICIAL_DOCS, .6),
        )

class Meter:
    def authorize(self, target): return BudgetGrant(target.identity, True)
    def record(self, _cost): pass
    def usage(self, project): return BudgetUsage(project)

class DiscoveryTests(unittest.TestCase):
    def test_canonicalizes_duplicate_urls_and_ranks_authority_explainably(self):
        ranked = rank_discoveries(Search().search(question()), limit=10)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].source.title, "Official retry")
        self.assertIn("popularity excluded", ranked[0].explanation)
        self.assertEqual(canonical_locator("HTTPS://DOCS.EXAMPLE.COM/retry/#x"), "https://docs.example.com/retry")

    def test_denied_authorization_never_calls_provider(self):
        search = Search()
        with self.assertRaises(PermissionError):
            discover(question(), job(), RepoIntelligenceAuthorization(project=PROJECT), RepoIntelligenceProviders(external_discovery=search), privacy_policy=EXPORT)
        self.assertEqual(search.calls, 0)

    def test_non_external_provider_hit_is_rejected(self):
        hit = DiscoveredSource("fixture", "https://example.com/internal", "bad", SourceClass.LIVE_REPOSITORY, .8)
        with self.assertRaises(ValueError):
            rank_discoveries((hit,), limit=1)

    def test_closed_internal_question_never_spends_or_calls_provider(self):
        search = Search()
        result = discover(question(QuestionStatus.ANSWERED_INTERNAL), job(), RepoIntelligenceAuthorization(project=PROJECT, external_access=True), RepoIntelligenceProviders(external_discovery=search), privacy_policy=EXPORT)
        self.assertFalse(result.costs)
        self.assertEqual(search.calls, 0)
        self.assertIn("no external research", result.stopped_reason)
        self.assertIs(result.reason_code, StageReasonCode.INTERNAL_SUFFICIENT)

    def test_privacy_denied_export_never_calls_provider_and_is_distinguishable(self):
        # allow_export=False must surface PRIVACY_DENIED, never a code that
        # implies sufficiency, even for an OPEN question with export access.
        search = Search()
        result = discover(
            question(), job(), RepoIntelligenceAuthorization(project=PROJECT, external_access=True),
            RepoIntelligenceProviders(external_discovery=search), privacy_policy=PrivacyPolicy(allow_export=False),
        )
        self.assertFalse(result.costs)
        self.assertEqual(search.calls, 0)
        self.assertIs(result.reason_code, StageReasonCode.PRIVACY_DENIED)
        self.assertNotEqual(result.reason_code, StageReasonCode.INTERNAL_SUFFICIENT)

    def test_proactive_job_without_lineage_receipt_is_denied(self):
        """Critical invariant (RI-13): no proactive research without a receipt."""
        search = Search()
        with self.assertRaises(PermissionError):
            discover(question(), job(JobTrigger.MAINTENANCE), RepoIntelligenceAuthorization(project=PROJECT, external_access=True), RepoIntelligenceProviders(external_discovery=search), privacy_policy=EXPORT)
        self.assertEqual(search.calls, 0)

    def test_proactive_job_with_matching_lineage_receipt_is_allowed(self):
        search = Search()
        result = discover(question(), job(JobTrigger.MAINTENANCE), RepoIntelligenceAuthorization(project=PROJECT, external_access=True), RepoIntelligenceProviders(external_discovery=search, budget_meter=Meter()), privacy_policy=EXPORT, lineage_receipt=receipt())
        self.assertEqual(search.calls, 1)
        self.assertEqual(len(result.ranked), 2)

    def test_proactive_job_with_cross_project_lineage_receipt_is_denied(self):
        other_project = deterministic_identity(EntityKind.PROJECT, "discovery-beta")
        search = Search()
        with self.assertRaises(PermissionError):
            discover(question(), job(JobTrigger.MAINTENANCE), RepoIntelligenceAuthorization(project=PROJECT, external_access=True), RepoIntelligenceProviders(external_discovery=search), privacy_policy=EXPORT, lineage_receipt=receipt(other_project))
        self.assertEqual(search.calls, 0)

    def test_explicit_user_pull_needs_no_lineage_receipt(self):
        search = Search()
        result = discover(question(), job(JobTrigger.USER_PULL), RepoIntelligenceAuthorization(project=PROJECT, external_access=True), RepoIntelligenceProviders(external_discovery=search, budget_meter=Meter()), privacy_policy=EXPORT)
        self.assertEqual(search.calls, 1)

    def test_success_has_one_accounted_network_cost_and_no_fetch(self):
        search = Search()
        result = discover(question(), job(), RepoIntelligenceAuthorization(project=PROJECT, external_access=True), RepoIntelligenceProviders(external_discovery=search, budget_meter=Meter()), privacy_policy=EXPORT)
        self.assertEqual(search.calls, 1)
        self.assertEqual(len(result.costs), 1)
        self.assertEqual(result.costs[0].resource.value, "external_search")
        self.assertEqual(len(result.ranked), 2)

if __name__ == "__main__": unittest.main()
