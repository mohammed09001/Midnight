"""Repo Intelligent foundation contracts: round-trip, identity, claim rules."""

import json
import unittest
from datetime import datetime, timedelta, timezone

from midnight_performance.contracts import ClaimKind, ExternalReference, Identity, deterministic_identity, EntityKind
from midnight_performance.repo_intelligence.contracts import (
    AssociationKind,
    BudgetCeiling,
    CacheStatus,
    CostRecord,
    CostResourceKind,
    EdgeClass,
    EvidenceBundle,
    EvidenceItem,
    Exposure,
    ExposureChannel,
    ExposureOutcome,
    GraphLink,
    GraphRelation,
    InternalAnswerStatus,
    InternalSignal,
    JobStatus,
    JobTrigger,
    LearningOutcome,
    LineageReceipt,
    PressureDimension,
    ProjectEntityRef,
    ProjectEntityRefKind,
    ProjectInsight,
    ProjectIntelligenceJob,
    QuestionStatus,
    ResearchQuestion,
    UnsupportedSchemaVersionError,
    evidence_bundle_identity,
    lineage_receipt_identity,
    new_event_identity,
    project_entity_ref_identity,
    validate_insight_against_bundle,
)
from midnight_performance.repo_intelligence.identities import (
    RepoIdentity,
    RepoIntelligenceKind,
    deterministic_repo_identity,
)
from midnight_performance.repo_intelligence.sources import (
    EvidenceSide,
    Freshness,
    SourceClass,
    TrustClass,
)

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)

PROJECT_A = deterministic_identity(EntityKind.PROJECT, "alpha")


def performance_ref(suffix: str) -> str:
    return deterministic_identity(EntityKind.PROMPT_RUN, f"alpha|{suffix}").canonical


def entity_ref(suffix: str) -> str:
    return deterministic_repo_identity(
        RepoIntelligenceKind.PROJECT_ENTITY_REF, f"alpha|entity|{suffix}"
    ).canonical


def budget(**overrides) -> BudgetCeiling:
    fields = {"max_model_calls": 2, "max_network_requests": 3, "max_cost_micros": 1000, "max_seconds": 30.0}
    fields.update(overrides)
    return BudgetCeiling(**fields)


def make_job(**overrides) -> ProjectIntelligenceJob:
    fields = dict(
        identity=deterministic_repo_identity(
            RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB, f"{PROJECT_A.canonical}|signal_scan|job-1"
        ),
        project=PROJECT_A,
        job_kind="signal_scan",
        idempotency_key="job-1",
        trigger=JobTrigger.USER_PULL,
        status=JobStatus.PENDING,
        stop_condition="stop when signals for the current window are scored",
        budget=budget(),
        derivation_method="signal-scan",
        derivation_version="1",
        requested_at=T0,
    )
    fields.update(overrides)
    return ProjectIntelligenceJob(**fields)


def make_item(ref: str, source_class: SourceClass, trust: TrustClass, digest: str | None = None) -> EvidenceItem:
    return EvidenceItem(ref=ref, source_class=source_class, trust_class=trust, captured_at=T0, content_digest=digest)


def internal_bundle() -> EvidenceBundle:
    items = (
        make_item(performance_ref("run-1"), SourceClass.PERFORMANCE_EVIDENCE, TrustClass.FIRST_PARTY_LOCAL),
        make_item(entity_ref("file-a"), SourceClass.LIVE_REPOSITORY, TrustClass.FIRST_PARTY_LOCAL),
    )
    return EvidenceBundle(
        identity=evidence_bundle_identity(PROJECT_A, items),
        project=PROJECT_A,
        items=items,
        created_at=T0,
    )


def external_bundle(
    trust: TrustClass = TrustClass.VENDOR_AUTHORITATIVE,
    source_class: SourceClass = SourceClass.OFFICIAL_DOCS,
) -> EvidenceBundle:
    items = (
        make_item(
            "ri:v1:external_source_ref:00000000-0000-0000-0000-000000000001",
            source_class,
            trust,
            "a" * 64,
        ),
    )
    return EvidenceBundle(
        identity=evidence_bundle_identity(PROJECT_A, items),
        project=PROJECT_A,
        items=items,
        created_at=T0,
    )


def make_insight(bundle: EvidenceBundle, **overrides) -> ProjectInsight:
    statement = "the retry helper in auth is edited repeatedly around failed verifications"
    fields = dict(
        identity=deterministic_repo_identity(
            RepoIntelligenceKind.PROJECT_INSIGHT,
            f"{bundle.project.canonical}|{bundle.identity.canonical}|insight-method|1|statement",
        ),
        project=bundle.project,
        statement=statement,
        claim_kind=ClaimKind.INFERRED,
        method="insight-method",
        method_version="1",
        uncertainty="inferred from bounded evidence; may not generalize",
        evidence_bundle=bundle.identity,
        confidence=0.6,
        valid_from=T0,
    )
    fields.update(overrides)
    return ProjectInsight(**fields)


def make_receipt(**overrides) -> LineageReceipt:
    fields = dict(
        project=PROJECT_A,
        derivation_method="insight-synthesis",
        derivation_version="1",
        window_start=T0,
        window_end=T1,
        claim_kind=ClaimKind.DERIVED,
        privacy_decision="local_only",
        created_at=T0,
        performance_evidence_ids=(performance_ref("run-1"),),
        repository_change_refs=(),
        memory_refs=(),
    )
    fields.update(overrides)
    fields["identity"] = lineage_receipt_identity(
        fields["project"],
        fields["derivation_method"],
        fields["derivation_version"],
        fields["window_start"],
        fields["window_end"],
        fields["performance_evidence_ids"],
        fields["repository_change_refs"],
        fields["memory_refs"],
    )
    return LineageReceipt(**fields)


def round_trip(record):
    restored = type(record).from_dict(json.loads(json.dumps(record.to_dict(), sort_keys=True)))
    return restored, restored == record


class IdentityTests(unittest.TestCase):
    def test_deterministic_identities_are_stable_and_namespaced(self):
        first = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "alpha|x")
        second = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "alpha|x")
        other_kind = deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, "alpha|x")
        other_project = deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "beta|x")
        self.assertEqual(first, second)
        self.assertEqual(first.canonical, "ri:v1:project_insight:" + str(first.value))
        self.assertNotEqual(first, other_kind)
        self.assertNotEqual(first, other_project)

    def test_parse_round_trip_and_rejection(self):
        identity = deterministic_repo_identity(RepoIntelligenceKind.LINEAGE_RECEIPT, "alpha|r")
        self.assertEqual(RepoIdentity.parse(identity.canonical), identity)
        with self.assertRaises(ValueError):
            RepoIdentity.parse("mp:v1:project:00000000-0000-0000-0000-000000000000")
        with self.assertRaises(ValueError):
            RepoIdentity.parse("ri:v1:not_a_kind:00000000-0000-0000-0000-000000000000")

    def test_blank_stable_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, "  ")

    def test_performance_identity_namespace_stays_distinct(self):
        performance = deterministic_identity(EntityKind.PROJECT, "alpha")
        self.assertTrue(performance.canonical.startswith("mp:"))
        with self.assertRaises(ValueError):
            RepoIdentity.parse(performance.canonical)


class SerializationTests(unittest.TestCase):
    def test_every_record_round_trips_deterministically(self):
        bundle = internal_bundle()
        receipt = make_receipt()
        insight = make_insight(bundle, lineage_receipt=receipt.identity)
        job = make_job()
        records = [
            job,
            InternalSignal(
                identity=deterministic_repo_identity(RepoIntelligenceKind.INTERNAL_SIGNAL, "alpha|signal|1"),
                project=PROJECT_A,
                signal_kind="rework",
                dimensions=(PressureDimension.FRICTION, PressureDimension.RECURRENCE),
                window_start=T0,
                window_end=T1,
                claim_kind=ClaimKind.DERIVED,
                method="signal-scan",
                method_version="1",
                uncertainty="windowed observation",
                summary="repeated edits with failed verification on auth retry helper",
                performance_refs=(performance_ref("run-1"),),
                entity_refs=(entity_ref("file-a"),),
                evidence_ids=(performance_ref("run-1"),),
                confidence=0.7,
            ),
            ProjectEntityRef(
                identity=project_entity_ref_identity(
                    "alpha", ProjectEntityRefKind.FILE, "src/auth.py", None, "stdlib-ast", "1"
                ),
                project=PROJECT_A,
                ref_kind=ProjectEntityRefKind.FILE,
                repository_key="alpha",
                resolver_tool="stdlib-ast",
                resolver_version="1",
                first_seen_at=T0,
                last_seen_at=T1,
                path="src/auth.py",
            ),
            ResearchQuestion(
                identity=deterministic_repo_identity(
                    RepoIntelligenceKind.RESEARCH_QUESTION, f"{PROJECT_A.canonical}|dedup-1"
                ),
                project=PROJECT_A,
                question_text="what are proven retry/backoff patterns for token refresh",
                privacy_minimized=True,
                why_now="third failed verification in two weeks on the refresh path",
                triggered_by=(performance_ref("run-1"),),
                what_is_already_known="local helper retries twice with no backoff",
                what_is_unknown="whether standard backoff applies to this provider",
                what_external_evidence_would_change="vendor guidance on refresh retry intervals",
                stop_condition="stop after one authoritative doc answer",
                budget=budget(max_model_calls=None),
                internal_answer_status=InternalAnswerStatus.ABSENT,
                dedup_key="dedup-1",
                status=QuestionStatus.OPEN,
                created_at=T0,
            ),
            bundle,
            insight,
            receipt,
            GraphLink(
                identity=deterministic_repo_identity(RepoIntelligenceKind.GRAPH_LINK, "alpha|link|1"),
                project=PROJECT_A,
                source=entity_ref("file-a"),
                target=performance_ref("run-1"),
                relation=GraphRelation.CHANGED_IN,
                edge_class=EdgeClass.STRUCTURAL,
                claim_kind=ClaimKind.DERIVED,
                method="graph-rebuild",
                method_version="1",
                uncertainty="direct reification of a typed reference",
                evidence_ids=(performance_ref("run-1"),),
                first_seen=T0,
                last_seen=T1,
                valid_from=T0,
            ),
            Exposure(
                identity=new_event_identity(RepoIntelligenceKind.EXPOSURE),
                project=PROJECT_A,
                insight=insight.identity,
                channel=ExposureChannel.PROACTIVE_PUSH,
                outcome=ExposureOutcome.OFFERED,
                surface="terminal",
                occurred_at=T1,
                relevance_justification="hiding it would leave the retry failure pattern unexplained",
            ),
            LearningOutcome(
                identity=deterministic_repo_identity(RepoIntelligenceKind.LEARNING_OUTCOME, "alpha|outcome|1"),
                project=PROJECT_A,
                exposure=deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, "alpha|exposure|1"),
                insight=insight.identity,
                association=AssociationKind.POSITIVE_ASSOCIATION,
                claim_kind=ClaimKind.STATISTICAL,
                method="outcome-association",
                method_version="1",
                uncertainty="association is not causality",
                window_start=T1,
                window_end=T1 + timedelta(days=7),
                created_at=T1 + timedelta(days=7),
                associated_performance_refs=(performance_ref("run-2"),),
            ),
            CostRecord(
                identity=new_event_identity(RepoIntelligenceKind.COST_RECORD),
                project=PROJECT_A,
                job=job.identity,
                resource=CostResourceKind.EXTERNAL_SEARCH,
                provider="fixture-search",
                latency_ms=12.5,
                occurred_at=T0,
                cache_status=CacheStatus.MISS,
                cost_micros=150,
            ),
        ]
        for record in records:
            with self.subTest(record=type(record).__name__):
                restored, equal = round_trip(record)
                self.assertTrue(equal, f"{type(record).__name__} round trip changed the record")
                self.assertEqual(restored.to_dict(), record.to_dict())
                re_reserialized, equal_again = round_trip(restored)
                self.assertTrue(equal_again)
                self.assertEqual(re_reserialized, restored)

    def test_lineage_receipt_round_trips_memory_refs(self):
        receipt = make_receipt(
            memory_refs=(ExternalReference(provider="memory", kind="record", value="r1#rev2"),)
        )
        restored, equal = round_trip(receipt)
        self.assertTrue(equal)
        self.assertEqual(restored.memory_refs[0].value, "r1#rev2")

    def test_unknown_fields_fail_closed(self):
        document = internal_bundle().to_dict()
        document["sneaky_extra"] = True
        with self.assertRaises(ValueError) as ctx:
            EvidenceBundle.from_dict(document)
        self.assertIn("unknown fields", str(ctx.exception))

    def test_all_records_reject_unknown_fields(self):
        payloads = {
            ProjectIntelligenceJob: make_job().to_dict(),
            InternalSignal: InternalSignal(
                identity=deterministic_repo_identity(RepoIntelligenceKind.INTERNAL_SIGNAL, "alpha|s"),
                project=PROJECT_A,
                signal_kind="rework",
                dimensions=(PressureDimension.FRICTION,),
                window_start=T0,
                window_end=T0,
                claim_kind=ClaimKind.DERIVED,
                method="m",
                method_version="1",
                uncertainty="u",
                summary="s",
            ).to_dict(),
            ProjectEntityRef: ProjectEntityRef(
                identity=project_entity_ref_identity(
                    "alpha", ProjectEntityRefKind.FILE, "p.py", None, "t", "1"
                ),
                project=PROJECT_A,
                ref_kind=ProjectEntityRefKind.FILE,
                repository_key="alpha",
                resolver_tool="t",
                resolver_version="1",
                first_seen_at=T0,
                last_seen_at=T0,
                path="p.py",
            ).to_dict(),
            EvidenceBundle: internal_bundle().to_dict(),
            LineageReceipt: make_receipt().to_dict(),
        }
        for record_type, payload in payloads.items():
            with self.subTest(record=record_type.__name__):
                payload["intruder"] = 1
                with self.assertRaises(ValueError) as ctx:
                    record_type.from_dict(payload)
                self.assertIn("unknown fields", str(ctx.exception))

    def test_schema_version_mismatch_is_rejected(self):
        payload = internal_bundle().to_dict()
        payload["schema_version"] = 2
        with self.assertRaises(UnsupportedSchemaVersionError) as ctx:
            EvidenceBundle.from_dict(payload)
        self.assertEqual(ctx.exception.found, 2)
        self.assertEqual(ctx.exception.supported, 1)

    def test_schema_version_zero_and_missing_are_rejected(self):
        payload = internal_bundle().to_dict()
        payload["schema_version"] = 0
        with self.assertRaises(UnsupportedSchemaVersionError):
            EvidenceBundle.from_dict(payload)
        del payload["schema_version"]
        with self.assertRaises(UnsupportedSchemaVersionError):
            EvidenceBundle.from_dict(payload)


class ClaimKindRuleTests(unittest.TestCase):
    def test_insights_can_never_claim_observed(self):
        with self.assertRaises(ValueError):
            make_insight(internal_bundle(), claim_kind=ClaimKind.OBSERVED, confidence=None)

    def test_weak_insight_kinds_require_confidence(self):
        for kind in (ClaimKind.INFERRED, ClaimKind.STATISTICAL, ClaimKind.PREDICTED, ClaimKind.RECOMMENDED):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                make_insight(internal_bundle(), claim_kind=kind, confidence=None)

    def test_recommended_requires_user_action_and_only_recommended_requires_it(self):
        with self.assertRaises(ValueError):
            make_insight(internal_bundle(), claim_kind=ClaimKind.RECOMMENDED, confidence=0.5)
        with self.assertRaises(ValueError):
            make_insight(
                internal_bundle(), claim_kind=ClaimKind.INFERRED, confidence=0.5, requires_user_action=True
            )
        recommended = make_insight(
            internal_bundle(), claim_kind=ClaimKind.RECOMMENDED, confidence=0.5, requires_user_action=True
        )
        self.assertTrue(recommended.requires_user_action)

    def test_external_only_bundle_cannot_support_observed_or_derived_claims(self):
        bundle = external_bundle()
        with self.assertRaises(ValueError):
            make_insight(bundle, claim_kind=ClaimKind.OBSERVED, confidence=None, disclosure="d")
        derived = make_insight(bundle, claim_kind=ClaimKind.DERIVED, confidence=0.5, disclosure="d")
        with self.assertRaises(ValueError):
            validate_insight_against_bundle(derived, bundle)

    def test_one_sided_external_requires_authority_and_disclosure(self):
        weak_bundle = external_bundle(trust=TrustClass.COMMUNITY, source_class=SourceClass.WEB)
        insight = make_insight(weak_bundle, disclosure="a web post said so")
        with self.assertRaises(ValueError):
            validate_insight_against_bundle(insight, weak_bundle)

        authoritative = external_bundle()
        undisclosed = make_insight(authoritative)
        with self.assertRaises(ValueError):
            validate_insight_against_bundle(undisclosed, authoritative)

        disclosed = make_insight(authoritative, disclosure="vendor documentation, retrieved 2026-09")
        validate_insight_against_bundle(disclosed, authoritative)

    def test_two_sided_internal_bundle_passes_validation(self):
        bundle = internal_bundle()
        insight = make_insight(bundle)
        validate_insight_against_bundle(insight, bundle)

    def test_bundle_triangle_sides(self):
        self.assertEqual(
            internal_bundle().sides_covered(),
            frozenset({EvidenceSide.PERFORMANCE_HISTORY, EvidenceSide.PROJECT_STRUCTURE}),
        )
        self.assertTrue(external_bundle().external_only())
        self.assertTrue(external_bundle().one_sided_external())

    def test_lineage_gates_proactive_exposure(self):
        bundle = internal_bundle()
        orphan = make_insight(bundle)
        self.assertFalse(orphan.proactively_exposable())

        receipted = make_insight(bundle, lineage_receipt=make_receipt().identity)
        self.assertTrue(receipted.proactively_exposable())

        superseded = make_insight(
            bundle, lineage_receipt=make_receipt().identity, superseded_by=receipted.identity
        )
        self.assertFalse(superseded.proactively_exposable())

        expired = make_insight(bundle, lineage_receipt=make_receipt().identity, valid_to=T1)
        self.assertFalse(expired.proactively_exposable())


class RecordRuleTests(unittest.TestCase):
    def test_job_requires_timestamps_by_status(self):
        with self.assertRaises(ValueError):
            make_job(status=JobStatus.RUNNING)
        with self.assertRaises(ValueError):
            make_job(status=JobStatus.COMPLETED, started_at=T0)
        with self.assertRaises(ValueError):
            make_job(status=JobStatus.FAILED, started_at=T0, completed_at=T1)
        with self.assertRaises(ValueError):
            make_job(failure_reason="boom")

    def test_budget_ceiling_requires_at_least_one_bound(self):
        with self.assertRaises(ValueError):
            BudgetCeiling()
        self.assertEqual(budget(max_model_calls=None).max_network_requests, 3)

    def test_signal_claim_kinds_are_limited(self):
        kwargs = dict(
            identity=deterministic_repo_identity(RepoIntelligenceKind.INTERNAL_SIGNAL, "alpha|x"),
            project=PROJECT_A,
            signal_kind="churn",
            dimensions=(PressureDimension.ATTENTION,),
            window_start=T0,
            window_end=T0,
            method="m",
            method_version="1",
            uncertainty="u",
            summary="s",
        )
        with self.assertRaises(ValueError):
            InternalSignal(**kwargs, claim_kind=ClaimKind.OBSERVED)
        with self.assertRaises(ValueError):
            InternalSignal(**kwargs, claim_kind=ClaimKind.RECOMMENDED)
        with self.assertRaises(ValueError):
            InternalSignal(**kwargs, claim_kind=ClaimKind.INFERRED, confidence=None)

    def test_sufficient_internal_answer_closes_the_question(self):
        kwargs = dict(
            identity=deterministic_repo_identity(
                RepoIntelligenceKind.RESEARCH_QUESTION, f"{PROJECT_A.canonical}|d"
            ),
            project=PROJECT_A,
            question_text="q",
            privacy_minimized=True,
            why_now="n",
            triggered_by=(performance_ref("run-1"),),
            what_is_already_known="k",
            what_is_unknown="u",
            what_external_evidence_would_change="c",
            stop_condition="s",
            budget=budget(),
            internal_answer_status=InternalAnswerStatus.SUFFICIENT,
            dedup_key="d",
            created_at=T0,
        )
        with self.assertRaises(ValueError):
            ResearchQuestion(**kwargs, status=QuestionStatus.OPEN)
        with self.assertRaises(ValueError):
            ResearchQuestion(**kwargs, status=QuestionStatus.RESEARCHING)
        ResearchQuestion(**kwargs, status=QuestionStatus.ANSWERED_INTERNAL)

    def test_question_must_be_privacy_minimized(self):
        with self.assertRaises(ValueError):
            ResearchQuestion(
                identity=deterministic_repo_identity(
                    RepoIntelligenceKind.RESEARCH_QUESTION, f"{PROJECT_A.canonical}|d2"
                ),
                project=PROJECT_A,
                question_text="q",
                privacy_minimized=False,
                why_now="n",
                triggered_by=(performance_ref("run-1"),),
                what_is_already_known="k",
                what_is_unknown="u",
                what_external_evidence_would_change="c",
                stop_condition="s",
                budget=budget(),
                internal_answer_status=InternalAnswerStatus.ABSENT,
                dedup_key="d2",
                status=QuestionStatus.OPEN,
                created_at=T0,
            )

    def test_entity_ref_identity_is_content_independent_and_verified(self):
        fields = dict(
            project=PROJECT_A,
            ref_kind=ProjectEntityRefKind.FILE,
            repository_key="alpha",
            resolver_tool="stdlib-ast",
            resolver_version="1",
            first_seen_at=T0,
            last_seen_at=T0,
            path="src/auth.py",
        )
        expected_identity = project_entity_ref_identity(
            "alpha", ProjectEntityRefKind.FILE, "src/auth.py", None, "stdlib-ast", "1"
        )
        ref = ProjectEntityRef(identity=expected_identity, **fields)
        restored, equal = round_trip(ref)
        self.assertTrue(equal)
        self.assertEqual(restored.identity, expected_identity)
        with self.assertRaises(ValueError):
            ProjectEntityRef(
                identity=deterministic_repo_identity(
                    RepoIntelligenceKind.PROJECT_ENTITY_REF, "alpha|mismatch"
                ),
                **fields,
            )

    def test_graph_links_reject_self_edges_and_observed_claims(self):
        kwargs = dict(
            identity=deterministic_repo_identity(RepoIntelligenceKind.GRAPH_LINK, "alpha|g"),
            project=PROJECT_A,
            source=entity_ref("file-a"),
            target=performance_ref("run-1"),
            relation=GraphRelation.RELATED_TO,
            edge_class=EdgeClass.SEMANTIC,
            method="m",
            method_version="1",
            uncertainty="u",
            evidence_ids=(performance_ref("run-1"),),
            first_seen=T0,
            last_seen=T0,
            confidence=0.4,
        )
        with self.assertRaises(ValueError):
            GraphLink(**{**kwargs, "source": kwargs["target"], "claim_kind": ClaimKind.DERIVED})
        with self.assertRaises(ValueError):
            GraphLink(**kwargs, claim_kind=ClaimKind.OBSERVED)
        with self.assertRaises(ValueError):
            GraphLink(**{**kwargs, "claim_kind": ClaimKind.INFERRED, "confidence": None})

    def test_graph_links_go_stale_by_supersession_and_validity(self):
        link = GraphLink(
            identity=deterministic_repo_identity(RepoIntelligenceKind.GRAPH_LINK, "alpha|g2"),
            project=PROJECT_A,
            source=entity_ref("file-a"),
            target=performance_ref("run-1"),
            relation=GraphRelation.RELATED_TO,
            edge_class=EdgeClass.STRUCTURAL,
            claim_kind=ClaimKind.DERIVED,
            method="m",
            method_version="1",
            uncertainty="u",
            evidence_ids=(performance_ref("run-1"),),
            first_seen=T0,
            last_seen=T0,
            valid_to=T1,
        )
        self.assertFalse(link.is_stale(T0))
        self.assertTrue(link.is_stale(T1 + timedelta(seconds=1)))

    def test_exposure_attention_budget_rules(self):
        kwargs = dict(
            identity=new_event_identity(RepoIntelligenceKind.EXPOSURE),
            project=PROJECT_A,
            insight=deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "alpha|i"),
            surface="terminal",
            occurred_at=T0,
        )
        with self.assertRaises(ValueError):
            Exposure(**kwargs, channel=ExposureChannel.PROACTIVE_PUSH, outcome=ExposureOutcome.OFFERED)
        with self.assertRaises(ValueError):
            Exposure(
                **kwargs,
                channel=ExposureChannel.PROACTIVE_PUSH,
                outcome=ExposureOutcome.OFFERED,
                relevance_justification="because",
                focus_protected=True,
            )
        with self.assertRaises(ValueError):
            Exposure(**kwargs, channel=ExposureChannel.USER_PULL, outcome=ExposureOutcome.SUPPRESSED)
        Exposure(
            **kwargs,
            channel=ExposureChannel.PROACTIVE_PUSH,
            outcome=ExposureOutcome.OFFERED,
            relevance_justification="the user would lose the pattern explanation",
        )
        Exposure(
            **kwargs,
            channel=ExposureChannel.QUIET_QUEUE,
            outcome=ExposureOutcome.SUPPRESSED,
            suppression_reason="dismissed three times previously",
        )

    def test_learning_outcomes_cannot_claim_causal_strength(self):
        kwargs = dict(
            identity=deterministic_repo_identity(RepoIntelligenceKind.LEARNING_OUTCOME, "alpha|o"),
            project=PROJECT_A,
            exposure=deterministic_repo_identity(RepoIntelligenceKind.EXPOSURE, "alpha|e"),
            insight=deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INSIGHT, "alpha|i"),
            association=AssociationKind.POSITIVE_ASSOCIATION,
            method="m",
            method_version="1",
            uncertainty="association is not causality",
            window_start=T0,
            window_end=T1,
            created_at=T1,
        )
        for kind in (ClaimKind.OBSERVED, ClaimKind.DERIVED, ClaimKind.INFERRED, ClaimKind.RECOMMENDED):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                LearningOutcome(**kwargs, claim_kind=kind)
        LearningOutcome(**kwargs, claim_kind=ClaimKind.STATISTICAL)

    def test_cost_records_account_cache_and_budget(self):
        kwargs = dict(
            identity=new_event_identity(RepoIntelligenceKind.COST_RECORD),
            project=PROJECT_A,
            job=deterministic_repo_identity(RepoIntelligenceKind.PROJECT_INTELLIGENCE_JOB, "alpha|j"),
            resource=CostResourceKind.EMBEDDING,
            provider="fixture-embeddings",
            latency_ms=1.0,
            occurred_at=T0,
        )
        with self.assertRaises(ValueError):
            CostRecord(**kwargs, cache_status=CacheStatus.HIT)
        with self.assertRaises(ValueError):
            CostRecord(**kwargs, cache_status=CacheStatus.MISS, cache_key="k")
        hit = CostRecord(**kwargs, cache_status=CacheStatus.HIT, cache_key="k")
        self.assertEqual(hit.cache_key, "k")

    def test_lineage_receipts_require_sources_and_valid_windows(self):
        with self.assertRaises(ValueError):
            make_receipt(performance_evidence_ids=(), repository_change_refs=())
        with self.assertRaises(ValueError):
            make_receipt(privacy_decision="publish_everything")
        with self.assertRaises(ValueError):
            make_receipt(window_start=T1, window_end=T0)
        receipt = make_receipt(repository_change_refs=("snapshot-123",))
        self.assertEqual(
            receipt.identity,
            lineage_receipt_identity(
                PROJECT_A,
                receipt.derivation_method,
                receipt.derivation_version,
                receipt.window_start,
                receipt.window_end,
                receipt.performance_evidence_ids,
                receipt.repository_change_refs,
                receipt.memory_refs,
            ),
        )


class FreshnessTests(unittest.TestCase):
    def test_freshness_windows_are_evaluated_against_injected_clock(self):
        window = Freshness(captured_at=T0, valid_from=T0, valid_to=T1)
        self.assertTrue(window.is_current(T0))
        self.assertTrue(window.is_current(T1))
        self.assertFalse(window.is_current(T1 + timedelta(seconds=1)))

    def test_freshness_rejects_naive_times_and_inverted_windows(self):
        with self.assertRaises(ValueError):
            Freshness(captured_at=datetime(2026, 9, 1))
        with self.assertRaises(ValueError):
            Freshness(captured_at=T0, valid_from=T1, valid_to=T0)
        with self.assertRaises(ValueError):
            Freshness(captured_at=T1, valid_from=T1 + timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
