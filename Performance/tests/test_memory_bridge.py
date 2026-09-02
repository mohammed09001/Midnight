"""Tests for midnight_performance.memory_bridge (Midnight Memory Executions
02-05). Built incrementally: identity mapping (Task 4), envelope
construction + the Memory CLI subprocess client (Task 5), sealed-evidence
lesson hardening (Task 6), the QualifiedClaim lesson exporter (Task 8),
bounded-retry delivery semantics (Task 9), truthful degraded-mode
proposals/reads replacing the removed local duplicate-authority path
(Tasks 11-12), the typed bounded read client (Task 14), and by-reference
Memory citations (Task 15).
"""
import shutil
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import mkdtemp
from unittest import mock
from uuid import UUID

from midnight_performance import (
    AnalysisDescriptor,
    AnalysisResult,
    ClaimKind,
    ClaimType,
    EntityKind,
    EvidenceSource,
    ExternalReference,
    Observation,
    ObservationEnvelope,
    ObservationLayer,
    ObservationType,
    QualifiedClaim,
    Reprocessor,
    deterministic_identity,
    new_identity,
    redact_sensitive_text,
    seal,
    Identity,
)
from midnight_performance.memory_bridge import (
    MEMORY_CONTRACT_VERSION,
    LessonDeliveryResult,
    MemoryContractError,
    MemoryReadResult,
    MemoryUnavailableError,
    build_context_envelope,
    build_propose_envelope,
    call_memory_cli,
    call_memory_cli_with_retry,
    citation_from_memory_record,
    identity_from_project_key,
    lesson_from_qualified_claim,
    lesson_from_sealed_envelope,
    project_key_for_identity,
    propose_lesson_or_degrade,
    read_memory_context_or_none,
    read_performance_context,
)
import midnight_performance.memory as _memory_module
import midnight_performance.memory_bridge as _memory_bridge_module
from midnight_performance.ledger import EvidenceLedger
from midnight_performance.privacy import PrivacyGuard, PrivacyPolicy

_MEMORY_REPO_PATH = Path(__file__).resolve().parents[2] / "Memory"
_NODE_AVAILABLE = shutil.which("node") is not None


class MemoryBridgeIdentityTests(unittest.TestCase):
    """Task 4: bijective mapping between Performance identities and Memory projectKeys."""

    def test_project_key_round_trip(self):
        identity = deterministic_identity(EntityKind.PROJECT, "test-project")
        key = project_key_for_identity(identity)
        self.assertRegex(key, r"^[\w][\w.-]*$")
        self.assertEqual(identity_from_project_key(key), identity)

    def test_workspace_identity_also_supported(self):
        identity = deterministic_identity(EntityKind.WORKSPACE, "test-workspace")
        key = project_key_for_identity(identity)
        self.assertEqual(identity_from_project_key(key), identity)

    def test_rejects_non_project_workspace_kind(self):
        identity = deterministic_identity(EntityKind.TOOL_OBSERVATION, "x")
        with self.assertRaises(ValueError):
            project_key_for_identity(identity)

    def test_rejects_malformed_project_key(self):
        with self.assertRaises(ValueError):
            identity_from_project_key("not-a-performance-key")

    def test_rejects_project_key_of_wrong_kind_after_split(self):
        identity = deterministic_identity(EntityKind.MEMORY_RECORD, "x")
        key = identity.canonical.replace(":", ".")
        with self.assertRaises(ValueError):
            identity_from_project_key(key)

    def test_cross_language_agreement_fixture(self):
        # Same literal fixture asserted in Memory/test/t50_performance_identity.test.ts —
        # proves both independent implementations agree on the exact wire value.
        identity = Identity(
            EntityKind.PROJECT,
            UUID("00000000-0000-4000-8000-000000000000"),
            version=1,
        )
        self.assertEqual(
            project_key_for_identity(identity),
            "mp.v1.project.00000000-0000-4000-8000-000000000000",
        )


class MemoryBridgeEnvelopeTests(unittest.TestCase):
    """Task 5: the versioned contract envelope and the Memory CLI subprocess client."""

    def test_build_propose_envelope_shape(self):
        envelope = build_propose_envelope(
            "mp.v1.project.00000000-0000-4000-8000-000000000000",
            [{"subject": "S", "content": "C", "evidenceRefs": ["mp:v1:tool_observation:x"]}],
        )
        self.assertEqual(envelope["contractVersion"], MEMORY_CONTRACT_VERSION)
        self.assertEqual(envelope["operation"], "memory.performance.propose")
        self.assertEqual(envelope["request"]["scope"], "mp.v1.project.00000000-0000-4000-8000-000000000000")
        self.assertEqual(len(envelope["request"]["lessons"]), 1)
        self.assertNotIn("caller", envelope["request"])

    def test_build_propose_envelope_includes_caller_when_given(self):
        envelope = build_propose_envelope("proj", [], caller={"kind": "engine", "name": "performance"})
        self.assertEqual(envelope["request"]["caller"], {"kind": "engine", "name": "performance"})

    def test_build_context_envelope_shape(self):
        envelope = build_context_envelope("proj", size=10, minConfidence=0.5)
        self.assertEqual(envelope["operation"], "memory.context")
        self.assertEqual(envelope["request"], {"scope": "proj", "size": 10, "minConfidence": 0.5})

    def test_memory_unavailable_when_node_missing(self):
        envelope = build_context_envelope("proj")
        with self.assertRaises(MemoryUnavailableError):
            call_memory_cli(
                envelope,
                memory_repo_path=_MEMORY_REPO_PATH,
                node_executable="definitely-not-a-real-binary-xyz",
            )

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_end_to_end_propose_and_read_back(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project." + "11111111-1111-4111-8111-111111111111"

        # Scope creation is not part of the versioned envelope surface
        # (Memory has no memory.scope.create operation) — this is test
        # scaffolding via the CLI's dedicated `scope create` subcommand, not
        # part of the contract under test.
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        lesson = {
            "subject": "Retry storms",
            "content": "Backoff caps retry storms",
            "evidenceRefs": ["mp:v1:tool_observation:22222222-2222-4222-8222-222222222222"],
        }
        propose_envelope = build_propose_envelope(project_key, [lesson])
        response = call_memory_cli(propose_envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(response["ok"])
        self.assertEqual(len(response["result"]["accepted"]), 1)
        self.assertEqual(len(response["result"]["rejected"]), 0)

        list_envelope = {
            "contractVersion": MEMORY_CONTRACT_VERSION,
            "operation": "memory.candidates",
            "request": {"scope": project_key, "status": "open"},
        }
        listed = call_memory_cli(list_envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(listed["ok"])
        subjects = [c["subject"] for c in listed["result"]["candidates"]]
        self.assertIn("Retry storms", subjects)

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_contract_version_mismatch_is_typed(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project." + "33333333-3333-4333-8333-333333333333"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        envelope = build_propose_envelope(project_key, [])
        envelope["contractVersion"] = "99.0.0"
        with self.assertRaises(MemoryContractError) as ctx:
            call_memory_cli(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertEqual(ctx.exception.code, "MEMORY_CONTRACT_MISMATCH")


def subprocess_run_scope_create(project_key: str, *, store_path: str):
    import subprocess

    cli_path = str(_MEMORY_REPO_PATH / "src" / "cli" / "cli.ts")
    return subprocess.run(
        [
            "node", "--experimental-strip-types", cli_path,
            "scope", "create", "--key", project_key, "--name", "Bridge Test",
            "--store", store_path,
        ],
        capture_output=True, text=True, timeout=30,
    )


def subprocess_run_scope_policy(project_key: str, *, store_path: str, allow: list[str]):
    import subprocess

    cli_path = str(_MEMORY_REPO_PATH / "src" / "cli" / "cli.ts")
    argv = [
        "node", "--experimental-strip-types", cli_path,
        "scope", "policy", "--key", project_key, "--mode", "allowlist",
        "--store", store_path,
    ]
    for actor_key in allow:
        argv += ["--allow", actor_key]
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def subprocess_run_record_add(project_key: str, *, store_path: str, subject: str, content: str):
    import subprocess

    cli_path = str(_MEMORY_REPO_PATH / "src" / "cli" / "cli.ts")
    return subprocess.run(
        [
            "node", "--experimental-strip-types", cli_path,
            "record", "add", "--scope", project_key, "--subject", subject, "--content", content,
            "--evidence", "external:test-1", "--source-kind", "user_note", "--store", store_path,
        ],
        capture_output=True, text=True, timeout=30,
    )


def subprocess_run_record_revise(record_id: str, *, store_path: str, content: str, reason: str):
    import subprocess

    cli_path = str(_MEMORY_REPO_PATH / "src" / "cli" / "cli.ts")
    return subprocess.run(
        [
            "node", "--experimental-strip-types", cli_path,
            "record", "revise", "--id", record_id, "--content", content, "--reason", reason,
            "--actor-kind", "human", "--actor-name", "kim", "--store", store_path,
        ],
        capture_output=True, text=True, timeout=30,
    )


def subprocess_run_events(*, store_path: str, limit: int = 50):
    import subprocess

    cli_path = str(_MEMORY_REPO_PATH / "src" / "cli" / "cli.ts")
    return subprocess.run(
        ["node", "--experimental-strip-types", cli_path, "events", "--limit", str(limit), "--store", store_path],
        capture_output=True, text=True, timeout=30,
    )


def _sealed_test_envelope() -> ObservationEnvelope:
    project = deterministic_identity(EntityKind.PROJECT, "bridge-test-project")
    observation = Observation(
        identity=new_identity(EntityKind.TOOL_OBSERVATION),
        claim_kind=ClaimKind.OBSERVED,
        subject=new_identity(EntityKind.AGENT_RUN),
        payload={"secret": "do-not-leak"},
        observed_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    envelope = ObservationEnvelope(
        observation=observation,
        project=project,
        observation_type=ObservationType.TOOL,
        layer=ObservationLayer.RAW,
        provider="test-provider",
        provider_event_id="event-1",
    )
    return seal(envelope)


class MemoryBridgeEvidenceHardeningTests(unittest.TestCase):
    """Task 6: the "inaccessible" enforcement point — lesson_from_sealed_envelope."""

    def test_lesson_rejects_unsealed_envelope(self):
        project = deterministic_identity(EntityKind.PROJECT, "bridge-test-project")
        observation = Observation(
            identity=new_identity(EntityKind.TOOL_OBSERVATION),
            claim_kind=ClaimKind.OBSERVED,
            subject=new_identity(EntityKind.AGENT_RUN),
            payload={},
        )
        unsealed = ObservationEnvelope(
            observation=observation, project=project,
            observation_type=ObservationType.TOOL, layer=ObservationLayer.RAW,
            provider="test-provider", provider_event_id="event-1",
        )
        with self.assertRaisesRegex(ValueError, "never sealed"):
            lesson_from_sealed_envelope(unsealed, subject="S", content="C")

    def test_lesson_rejects_tampered_envelope(self):
        sealed = _sealed_test_envelope()
        tampered = replace(sealed, integrity_checksum="0" * 64)
        with self.assertRaisesRegex(ValueError, "tampered"):
            lesson_from_sealed_envelope(tampered, subject="S", content="C")

    def test_lesson_from_sealed_envelope_shape_and_content_minimization(self):
        sealed = _sealed_test_envelope()
        lesson = lesson_from_sealed_envelope(sealed, subject="Retry storms", content="Backoff caps retry storms")
        self.assertEqual(lesson["subject"], "Retry storms")
        self.assertEqual(lesson["content"], "Backoff caps retry storms")
        self.assertEqual(lesson["evidenceRefs"], [sealed.observation.identity.canonical])
        # The raw payload is never echoed into the lesson content.
        self.assertNotIn("do-not-leak", lesson["content"])
        self.assertNotIn("payload", lesson)
        # Task 9: default idempotencyKey is the envelope's own stable identity.
        self.assertEqual(lesson["idempotencyKey"], sealed.observation.identity.canonical)

    def test_lesson_idempotency_key_override(self):
        sealed = _sealed_test_envelope()
        lesson = lesson_from_sealed_envelope(sealed, subject="S", content="C", idempotency_key="custom-key")
        self.assertEqual(lesson["idempotencyKey"], "custom-key")


def _qualified_claim(**overrides) -> QualifiedClaim:
    fields = dict(
        claim_type=ClaimType.REPOSITORY_CHANGE,
        source=EvidenceSource.REPOSITORY_SNAPSHOT,
        claim_kind=ClaimKind.OBSERVED,
    )
    fields.update(overrides)
    return QualifiedClaim(**fields)


class MemoryBridgeQualifiedClaimExporterTests(unittest.TestCase):
    """Task 8: the lesson exporter — QualifiedClaim + sealed evidence -> lesson."""

    def test_epistemic_class_mapping_never_upgrades_claim_strength(self):
        expected = {
            ClaimKind.OBSERVED: "observed",
            ClaimKind.DERIVED: "derived",
            ClaimKind.INFERRED: "inferred",
            ClaimKind.STATISTICAL: "inferred",
            ClaimKind.PREDICTED: "inferred",
            ClaimKind.RECOMMENDED: "recommendation",
            ClaimKind.UNKNOWN: "unknown",
        }
        for claim_kind, epistemic_class in expected.items():
            with self.subTest(claim_kind=claim_kind):
                kwargs = {"claim_kind": claim_kind}
                if claim_kind in (ClaimKind.INFERRED, ClaimKind.STATISTICAL, ClaimKind.PREDICTED, ClaimKind.RECOMMENDED):
                    kwargs.update(method="m", method_version="1", confidence=0.5, uncertainty="u")
                claim = _qualified_claim(**kwargs)
                lesson = lesson_from_qualified_claim(claim, [_sealed_test_envelope()], subject="S")
                self.assertEqual(lesson["epistemicClass"], epistemic_class)

    def test_rejects_zero_envelopes(self):
        with self.assertRaises(ValueError):
            lesson_from_qualified_claim(_qualified_claim(), [], subject="S")

    def test_rejects_unsealed_grounding_envelope(self):
        project = deterministic_identity(EntityKind.PROJECT, "bridge-test-project")
        unsealed = ObservationEnvelope(
            observation=Observation(
                identity=new_identity(EntityKind.TOOL_OBSERVATION), claim_kind=ClaimKind.OBSERVED,
                subject=new_identity(EntityKind.AGENT_RUN), payload={},
            ),
            project=project, observation_type=ObservationType.TOOL, layer=ObservationLayer.RAW,
            provider="test-provider", provider_event_id="event-1",
        )
        with self.assertRaises(ValueError):
            lesson_from_qualified_claim(_qualified_claim(), [unsealed], subject="S")

    def test_deterministic_export_same_claim_same_evidence(self):
        envelope = _sealed_test_envelope()
        claim = _qualified_claim()
        first = lesson_from_qualified_claim(claim, [envelope], subject="S")
        second = lesson_from_qualified_claim(claim, [envelope], subject="S")
        self.assertEqual(first["idempotencyKey"], second["idempotencyKey"])
        self.assertEqual(first["content"], second["content"])

    def test_multi_evidence_lesson_carries_all_distinct_refs(self):
        envelopes = [_sealed_test_envelope(), _sealed_test_envelope()]
        lesson = lesson_from_qualified_claim(_qualified_claim(), envelopes, subject="S")
        self.assertEqual(
            sorted(lesson["evidenceRefs"]),
            sorted(e.observation.identity.canonical for e in envelopes),
        )

    def test_content_is_never_the_raw_payload_and_carries_confidence(self):
        claim = _qualified_claim(
            claim_kind=ClaimKind.INFERRED, method="heuristic", method_version="2",
            confidence=0.75, uncertainty="small sample",
        )
        lesson = lesson_from_qualified_claim(claim, [_sealed_test_envelope()], subject="S")
        self.assertNotIn("do-not-leak", lesson["content"])
        self.assertIn("heuristic", lesson["content"])
        self.assertEqual(lesson["confidence"], 0.75)

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_end_to_end_exported_claim_lands_correctly_in_memory(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.44444444-4444-4444-8444-444444444444"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        claim = _qualified_claim(
            claim_kind=ClaimKind.INFERRED, method="heuristic", method_version="1",
            confidence=0.9, uncertainty="single sample",
        )
        lesson = lesson_from_qualified_claim(claim, [_sealed_test_envelope()], subject="Exported claim")
        envelope = build_propose_envelope(project_key, [lesson])
        response = call_memory_cli(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(response["ok"])
        self.assertEqual(len(response["result"]["accepted"]), 1)

        listed = call_memory_cli(
            {"contractVersion": MEMORY_CONTRACT_VERSION, "operation": "memory.candidates",
             "request": {"scope": project_key, "status": "open"}},
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        candidate = next(c for c in listed["result"]["candidates"] if c["subject"] == "Exported claim")
        self.assertEqual(candidate["epistemicClass"], "inferred")
        self.assertEqual(candidate["confidence"], 0.9)
        self.assertEqual(candidate["evidenceRefs"][0]["ref"], lesson["evidenceRefs"][0])

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_speculative_claim_cannot_auto_promote_through_repetition_via_the_real_bridge(self):
        # Task 16 (Execution 06): a PREDICTED claim maps to epistemicClass
        # "recommendation" (lesson_from_qualified_claim's never-upgrade
        # mapping) and is grounded in 2 distinct evidence refs — enough
        # evidence to have matched repeated_evidence_backed_lesson before
        # Memory's policies.ts fix. Proves the fix holds through the real
        # propose -> promote round trip, not just Memory's own unit tests.
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.66666666-1111-4111-8111-111111111166"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        claim = _qualified_claim(
            claim_kind=ClaimKind.RECOMMENDED, method="model", method_version="1",
            confidence=0.4, uncertainty="speculative",
        )
        envelopes = [_sealed_test_envelope(), _sealed_test_envelope()]
        lesson = lesson_from_qualified_claim(claim, envelopes, subject="Speculative prediction")
        self.assertEqual(lesson["epistemicClass"], "recommendation")
        propose_response = call_memory_cli(
            build_propose_envelope(project_key, [lesson]),
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        self.assertTrue(propose_response["ok"])
        candidate_id = propose_response["result"]["accepted"][0]["candidateId"]

        # No explicit policy, engine actor: if repeated_evidence_backed_lesson
        # still matched (the pre-fix bug), this would auto-promote. It must
        # instead be refused as unmatched/ambiguous.
        promote_envelope = {
            "contractVersion": MEMORY_CONTRACT_VERSION,
            "operation": "memory.promote",
            "request": {"candidateId": candidate_id, "actor": {"kind": "engine", "name": "performance"}},
        }
        with self.assertRaises(MemoryContractError) as ctx:
            call_memory_cli(promote_envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertEqual(ctx.exception.code, "MEMORY_CONFLICT")


class MemoryBridgePrivacyRedactionTests(unittest.TestCase):
    """Task 17 (Execution 06): content-minimization has a structural
    backstop at the Performance-Memory boundary itself, not just caller
    discipline."""

    def test_lesson_from_sealed_envelope_redacts_a_leaked_secret_in_content(self):
        lesson = lesson_from_sealed_envelope(
            _sealed_test_envelope(), subject="S", content="the api_key: sk-abc123 leaked",
        )
        self.assertIn("[REDACTED]", lesson["content"])
        self.assertNotIn("sk-abc123", lesson["content"])

    def test_lesson_from_sealed_envelope_redacts_an_email_in_subject_and_note(self):
        lesson = lesson_from_sealed_envelope(
            _sealed_test_envelope(), subject="Contact bob@example.com about it", content="c",
            note="cc jane@example.com",
        )
        self.assertNotIn("bob@example.com", lesson["subject"])
        self.assertIn("[REDACTED_EMAIL]", lesson["subject"])
        self.assertNotIn("jane@example.com", lesson["note"])

    def test_lesson_from_qualified_claim_redacts_caller_supplied_content(self):
        claim = _qualified_claim()
        lesson = lesson_from_qualified_claim(
            claim, [_sealed_test_envelope()], subject="S",
            content="password: hunter2 was used",
        )
        self.assertIn("[REDACTED]", lesson["content"])
        self.assertNotIn("hunter2", lesson["content"])

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_a_leaked_secret_never_reaches_memory_records_or_events(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.77777777-2222-4222-8222-222222222277"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        secret = "sk-super-secret-token-999"
        lesson = lesson_from_sealed_envelope(
            _sealed_test_envelope(), subject="Leaky lesson",
            content=f"observed behavior; api_key: {secret} appeared in logs",
        )
        self.assertNotIn(secret, lesson["content"], "redaction must already have happened before the wire call")

        propose_response = call_memory_cli(
            build_propose_envelope(project_key, [lesson]),
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        self.assertTrue(propose_response["ok"])

        # The stored candidate's content never carries the raw secret.
        listed = call_memory_cli(
            {"contractVersion": MEMORY_CONTRACT_VERSION, "operation": "memory.candidates",
             "request": {"scope": project_key, "status": "open"}},
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        candidate = next(c for c in listed["result"]["candidates"] if c["subject"] == "Leaky lesson")
        self.assertNotIn(secret, candidate["content"])
        self.assertIn("[REDACTED]", candidate["content"])

        # The emitted event stream never carries it either.
        events = subprocess_run_events(store_path=store_path)
        self.assertEqual(events.returncode, 0, events.stderr)
        self.assertNotIn(secret, events.stdout)


class MemoryBridgeRetryTests(unittest.TestCase):
    """Task 9: bounded retry — retries transient failures, never deterministic ones."""

    def test_gives_up_after_max_retries_on_repeated_unavailability(self):
        envelope = build_context_envelope("proj")
        with mock.patch(
            "midnight_performance.memory_bridge.call_memory_cli",
            side_effect=MemoryUnavailableError("down"),
        ) as mocked:
            with self.assertRaises(MemoryUnavailableError):
                call_memory_cli_with_retry(envelope, max_retries=2, backoff_seconds=0)
        self.assertEqual(mocked.call_count, 3)  # initial attempt + 2 retries

    def test_never_retries_a_contract_error(self):
        envelope = build_context_envelope("proj")
        with mock.patch(
            "midnight_performance.memory_bridge.call_memory_cli",
            side_effect=MemoryContractError("MEMORY_VALIDATION_FAILED", "bad request"),
        ) as mocked:
            with self.assertRaises(MemoryContractError):
                call_memory_cli_with_retry(envelope, max_retries=3, backoff_seconds=0)
        self.assertEqual(mocked.call_count, 1, "a deterministic failure must never be retried")

    def test_succeeds_after_transient_failures_within_bound(self):
        envelope = build_context_envelope("proj")
        responses = [MemoryUnavailableError("down"), MemoryUnavailableError("down"), {"ok": True}]
        with mock.patch(
            "midnight_performance.memory_bridge.call_memory_cli",
            side_effect=responses,
        ) as mocked:
            result = call_memory_cli_with_retry(envelope, max_retries=3, backoff_seconds=0)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mocked.call_count, 3)


class MemoryBridgeDeliverySemanticsTests(unittest.TestCase):
    """Task 9: real, live-subprocess proofs of duplicate/partial/timeout/auth behavior."""

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_duplicate_delivery_creates_no_uncontrolled_duplicate_candidate(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.55555555-5555-4555-8555-555555555555"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        sealed = _sealed_test_envelope()
        lesson = lesson_from_sealed_envelope(sealed, subject="Duplicate-safe lesson", content="c")
        envelope = build_propose_envelope(project_key, [lesson])

        first = call_memory_cli(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        second = call_memory_cli(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(
            first["result"]["accepted"][0]["candidateId"],
            second["result"]["accepted"][0]["candidateId"],
        )

        listed = call_memory_cli(
            {"contractVersion": MEMORY_CONTRACT_VERSION, "operation": "memory.candidates",
             "request": {"scope": project_key, "status": "open"}},
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        matching = [c for c in listed["result"]["candidates"] if c["subject"] == "Duplicate-safe lesson"]
        self.assertEqual(len(matching), 1, "duplicate delivery must not create an uncontrolled duplicate candidate")

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_partial_failure_preserved_end_to_end(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.66666666-6666-4666-8666-666666666666"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        good = lesson_from_sealed_envelope(_sealed_test_envelope(), subject="Good lesson", content="c")
        malformed = {"subject": "Malformed", "content": "c", "evidenceRefs": []}
        envelope = build_propose_envelope(project_key, [malformed, good])
        response = call_memory_cli(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(response["ok"])
        self.assertEqual(len(response["result"]["accepted"]), 1)
        self.assertEqual(response["result"]["accepted"][0]["subject"], "Good lesson")
        self.assertEqual(len(response["result"]["rejected"]), 1)
        self.assertEqual(response["result"]["rejected"][0]["code"], "MEMORY_VALIDATION_FAILED")

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_real_timeout_is_distinguishable_from_policy_rejection(self):
        envelope = build_context_envelope("proj")
        with self.assertRaises(MemoryUnavailableError):
            call_memory_cli(envelope, memory_repo_path=_MEMORY_REPO_PATH, timeout_seconds=0.001)

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_unauthorized_caller_is_typed_and_distinguishable(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.77777777-7777-4777-8777-777777777777"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)
        # Allowlist excludes the default Performance caller (engine:performance).
        policy = subprocess_run_scope_policy(project_key, store_path=store_path, allow=["human:kim"])
        self.assertEqual(policy.returncode, 0, policy.stderr)

        lesson = lesson_from_sealed_envelope(_sealed_test_envelope(), subject="S", content="c")
        envelope = build_propose_envelope(project_key, [lesson])
        response = call_memory_cli(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        # The dispatcher itself never throws (Memory/src/engine/dispatcher.ts) —
        # per-lesson authorization failure surfaces in `rejected`, ok stays true.
        self.assertTrue(response["ok"])
        self.assertEqual(len(response["result"]["accepted"]), 0)
        self.assertEqual(response["result"]["rejected"][0]["code"], "MEMORY_INTAKE_UNAUTHORIZED")


class MemoryBridgeDegradedProposalTests(unittest.TestCase):
    """Task 11 (Execution 04): explicit proposals to / reads from Memory,
    replacing the removed local KnowledgeRecord/promote()/supersede()
    duplicate-authority path."""

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_propose_lesson_or_degrade_delivers_on_a_real_round_trip(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.88888888-8888-4888-8888-888888888888"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        lesson = lesson_from_sealed_envelope(_sealed_test_envelope(), subject="Degraded-path lesson", content="c")
        envelope = build_propose_envelope(project_key, [lesson])
        result = propose_lesson_or_degrade(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertIsInstance(result, LessonDeliveryResult)
        self.assertTrue(result.delivered)
        self.assertIsNotNone(result.candidate_id)
        self.assertIsNone(result.degraded_reason)

    def test_propose_lesson_or_degrade_never_raises_when_memory_is_unreachable(self):
        envelope = build_propose_envelope("proj", [])
        result = propose_lesson_or_degrade(
            envelope, memory_repo_path=_MEMORY_REPO_PATH, node_executable="definitely-not-a-real-binary-xyz",
        )
        self.assertFalse(result.delivered)
        self.assertIsNone(result.candidate_id)
        self.assertIsNotNone(result.degraded_reason)
        self.assertIn("memory_unavailable", result.degraded_reason)

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_read_memory_context_or_none_reads_real_data_and_none_when_unreachable(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.99999999-9999-4999-8999-999999999999"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        envelope = build_context_envelope(project_key)
        real = read_memory_context_or_none(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertIsNotNone(real)
        self.assertIn("records", real["result"])

        unreachable = read_memory_context_or_none(
            envelope, memory_repo_path=_MEMORY_REPO_PATH, node_executable="definitely-not-a-real-binary-xyz",
        )
        self.assertIsNone(unreachable)


class MemoryBridgeStandaloneOperationTests(unittest.TestCase):
    """Task 12 (Execution 04): Performance stays useful, and truthful, when
    Memory is absent, stopped, incompatible, or policy-denied."""

    def test_standalone_ledger_operation_is_unaffected_by_memory_being_unreachable(self):
        # Memory unreachable in the same test as an ordinary, wholly
        # Memory-independent Performance ledger write+replay — proves core
        # Performance evidence workflow doesn't degrade just because Memory
        # is unreachable elsewhere in the same process.
        envelope = build_propose_envelope("proj", [])
        degraded = propose_lesson_or_degrade(
            envelope, memory_repo_path=_MEMORY_REPO_PATH, node_executable="definitely-not-a-real-binary-xyz",
        )
        self.assertFalse(degraded.delivered)

        project = deterministic_identity(EntityKind.PROJECT, "standalone-project")
        guard = PrivacyGuard(PrivacyPolicy(allowed_categories=frozenset()), {})
        ledger_dir = mkdtemp()
        ledger = EvidenceLedger(Path(ledger_dir) / "evidence.jsonl", project, guard)
        observation = Observation(
            identity=new_identity(EntityKind.TOOL_OBSERVATION), claim_kind=ClaimKind.OBSERVED,
            subject=new_identity(EntityKind.AGENT_RUN), payload={},
        )
        appended = ledger.append(ObservationEnvelope(
            observation=observation, project=project, observation_type=ObservationType.TOOL,
            layer=ObservationLayer.RAW, provider="test-provider", provider_event_id="event-1",
        ))
        self.assertTrue(appended)
        self.assertEqual(len(list(ledger.replay())), 1)

    def test_no_local_duplicate_authority_survives(self):
        for removed in ("KnowledgeRecord", "promote", "supersede"):
            self.assertFalse(
                hasattr(_memory_module, removed),
                f"{removed} must not be reintroduced into midnight_performance.memory",
            )

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_policy_denial_is_a_truthful_degraded_path_not_a_crash(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)
        policy = subprocess_run_scope_policy(project_key, store_path=store_path, allow=["human:kim"])
        self.assertEqual(policy.returncode, 0, policy.stderr)

        lesson = lesson_from_sealed_envelope(_sealed_test_envelope(), subject="S", content="c")
        envelope = build_propose_envelope(project_key, [lesson])
        result = propose_lesson_or_degrade(envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertFalse(result.delivered)
        self.assertIsNotNone(result.degraded_reason)
        self.assertIn("MEMORY_INTAKE_UNAUTHORIZED", result.degraded_reason)


class MemoryBridgeReadClientTests(unittest.TestCase):
    """Task 14: the typed, bounded Performance Memory read client."""

    def test_size_out_of_bounds_fails_closed_without_a_subprocess_call(self):
        # No node_executable/memory_repo_path is even needed here — the
        # client-side bound check runs before any call is attempted, so
        # this test is not node-gated and proves the check is real.
        for bad_size in (0, 101, -5):
            with self.subTest(size=bad_size):
                result = read_performance_context("proj", size=bad_size, memory_repo_path=_MEMORY_REPO_PATH)
                self.assertFalse(result.available)
                self.assertEqual(result.error_code, "CLIENT_SIZE_OUT_OF_BOUNDS")
                self.assertEqual(result.records, ())

    def test_memory_unavailable_is_typed_and_never_raises(self):
        result = read_performance_context(
            "proj", memory_repo_path=_MEMORY_REPO_PATH, node_executable="definitely-not-a-real-binary-xyz",
        )
        self.assertFalse(result.available)
        self.assertEqual(result.error_code, "MEMORY_UNAVAILABLE")
        self.assertIsNotNone(result.error_message)

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_contract_mismatch_is_typed(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        # Build the envelope by hand with a bad major version, since
        # read_performance_context's own envelope builder always uses the
        # correct pinned version.
        result = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(result.available)  # sanity: the happy path works first
        bad_envelope = build_context_envelope(project_key)
        bad_envelope["contractVersion"] = "99.0.0"
        try:
            call_memory_cli(bad_envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
            self.fail("expected MemoryContractError")
        except MemoryContractError as exc:
            self.assertEqual(exc.code, "MEMORY_CONTRACT_MISMATCH")

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_real_round_trip_returns_task_13_provenance_fields(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)
        added = subprocess_run_record_add(
            project_key, store_path=store_path, subject="Read-client record", content="content",
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        result = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(result.available)
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        # Task 13's additive provenance fields are present on the read path.
        self.assertIn("contradiction", record)
        self.assertIn("evidenceGaps", record)
        self.assertIn("trace", record)
        self.assertEqual(record["record"]["subject"], "Read-client record")

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_no_caching_two_reads_reflect_store_changes_between_them(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        first = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(first.available)
        self.assertEqual(len(first.records), 0)

        added = subprocess_run_record_add(
            project_key, store_path=store_path, subject="Freshly added", content="content",
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        second = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(second.available)
        self.assertEqual(len(second.records), 1)
        self.assertNotEqual(first.records, second.records, "a cached read would not see the new record")


class MemoryCitationTests(unittest.TestCase):
    """Task 15: Performance analyses cite specific Memory record revisions
    by reference, never a copy, and a later Memory change never silently
    rewrites what a historical citation points at."""

    def test_citation_shape_from_a_context_record(self):
        context_record = {"record": {"recordId": "mem_x", "revision": 1}}
        citation = citation_from_memory_record(context_record)
        self.assertEqual(citation, ExternalReference(provider="memory", kind="record", value="mem_x#rev1"))

    def test_citation_shape_from_a_bare_memory_record(self):
        bare_record = {"recordId": "mem_y", "revision": 3}
        citation = citation_from_memory_record(bare_record)
        self.assertEqual(citation.value, "mem_y#rev3")

    def test_memory_references_do_not_affect_the_reproducibility_fingerprint(self):
        descriptor = AnalysisDescriptor("d", "1", "k", {})
        citation = ExternalReference(provider="memory", kind="record", value="mem_x#rev1")
        without = Reprocessor().run(descriptor, (), lambda inputs: {})
        with_citation = Reprocessor().run(descriptor, (), lambda inputs: {}, memory_references=(citation,))
        self.assertEqual(without.input_fingerprint, with_citation.input_fingerprint)
        self.assertEqual(without.memory_references, ())
        self.assertEqual(with_citation.memory_references, (citation,))

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_a_later_memory_revision_does_not_rewrite_the_historical_citation(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)
        added = subprocess_run_record_add(
            project_key, store_path=store_path, subject="Citable record", content="original content",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        import json as _json
        original = _json.loads(added.stdout)
        record_id = original["recordId"]
        self.assertEqual(original["revision"], 1)

        # Performance reads the record and cites this exact revision as
        # evidence for an analysis result.
        read = read_performance_context(project_key, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(read.available)
        cited_record = next(r for r in read.records if r["record"]["recordId"] == record_id)
        citation = citation_from_memory_record(cited_record)
        self.assertEqual(citation.value, f"{record_id}#rev1")
        result = Reprocessor().run(
            AnalysisDescriptor("cites-memory", "1", "k", {}), (), lambda inputs: {"summary": "ok"},
            memory_references=(citation,),
        )
        self.assertEqual(result.memory_references, (citation,))

        # Memory later revises the SAME record — the current record content
        # moves on, but the citation (#rev1) must still be reproducible.
        revised = subprocess_run_record_revise(
            record_id, store_path=store_path, content="revised content", reason="correction",
        )
        self.assertEqual(revised.returncode, 0, revised.stderr)

        history = call_memory_cli(
            {"contractVersion": MEMORY_CONTRACT_VERSION, "operation": "memory.history", "request": {"recordId": record_id}},
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        self.assertTrue(history["ok"])
        revisions = history["result"]["revisions"]
        rev1 = next(r for r in revisions if r["revision"] == 1)
        # The citation's target content is still exactly reproducible —
        # unchanged by the later revision.
        self.assertEqual(rev1["content"], "original content")
        # The citation string itself is immutable — it was built before the
        # revision and still names rev1, never silently repointed at rev2.
        self.assertEqual(citation.value, f"{record_id}#rev1")


class MemoryPromotionAuthorityTests(unittest.TestCase):
    """Task 18 (Execution 06): Performance, agents, and this bridge can
    propose but can never bypass Memory's promotion/resolution authority.
    No code gap was found here (verified during planning) — these are
    adversarial proofs of already-correct architecture, plus one structural
    regression guard."""

    def test_structural_no_promote_or_lifecycle_call_in_the_bridge_source(self):
        source = Path(_memory_bridge_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"memory.promote"', source)
        self.assertNotIn('"memory.lifecycle"', source)

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_adversarial_self_promotion_via_the_real_bridge_is_refused(self):
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.88888888-3333-4333-8333-333333333388"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        # An explicit agent caller override — the adversarial angle: what if
        # a careless Performance integration proposed AND then tried to
        # approve its own lesson as the same agent actor?
        lesson = lesson_from_sealed_envelope(_sealed_test_envelope(), subject="Self-promotion attempt", content="c")
        propose_response = call_memory_cli(
            build_propose_envelope(project_key, [lesson], caller={"kind": "agent", "name": "performance-bot"}),
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        self.assertTrue(propose_response["ok"])
        candidate_id = propose_response["result"]["accepted"][0]["candidateId"]

        promote_envelope = {
            "contractVersion": MEMORY_CONTRACT_VERSION,
            "operation": "memory.promote",
            "request": {"candidateId": candidate_id, "actor": {"kind": "agent", "name": "performance-bot"}},
        }
        with self.assertRaises(MemoryContractError) as ctx:
            call_memory_cli(promote_envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertEqual(ctx.exception.code, "MEMORY_PROMOTION_FORBIDDEN")

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_contradiction_resolution_is_not_reachable_through_the_bridges_only_channel(self):
        # Confirmed during planning: resolveContradiction has no
        # `contract call` operation at all (MEMORY_OPERATIONS has no
        # resolve op; memory.contradictions is read-only detect/list) — the
        # bridge's ONLY channel to Memory structurally cannot self-resolve,
        # not merely because of an actor check. The actor-kind rule itself
        # (agents refused with MEMORY_PROMOTION_FORBIDDEN) is already proven
        # directly against the engine in Memory/test/t10_contradictions.test.ts
        # ("agents cannot resolve contradictions") — reused as evidence, not
        # duplicated here.
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.99999999-4444-4444-8444-444444444499"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        bogus_envelope = {
            "contractVersion": MEMORY_CONTRACT_VERSION,
            "operation": "memory.contradiction.resolve",
            "request": {"groupId": "ctg_nonexistent", "action": "supersede", "winnerRecordId": "mem_x", "reason": "x"},
        }
        with self.assertRaises(MemoryContractError) as ctx:
            call_memory_cli(bogus_envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertEqual(ctx.exception.code, "MEMORY_VALIDATION_FAILED")
        self.assertIn("unknown operation", ctx.exception.message)

    @unittest.skipUnless(_NODE_AVAILABLE, "node not available in this environment")
    def test_positive_control_human_actor_with_a_matched_policy_promotes_successfully(self):
        # Proves the refusals above are genuinely about actor kind, not a
        # broken test fixture: the identical flow succeeds for a human.
        store_dir = mkdtemp()
        store_path = str(Path(store_dir) / "memory.db")
        project_key = "mp.v1.project.aaaaaaaa-5555-4555-8555-555555555511"
        create = subprocess_run_scope_create(project_key, store_path=store_path)
        self.assertEqual(create.returncode, 0, create.stderr)

        lesson = lesson_from_sealed_envelope(_sealed_test_envelope(), subject="Legitimately promotable", content="c")
        propose_response = call_memory_cli(
            build_propose_envelope(project_key, [lesson]),
            memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path,
        )
        self.assertTrue(propose_response["ok"])
        candidate_id = propose_response["result"]["accepted"][0]["candidateId"]

        promote_envelope = {
            "contractVersion": MEMORY_CONTRACT_VERSION,
            "operation": "memory.promote",
            "request": {
                "candidateId": candidate_id,
                "actor": {"kind": "human", "name": "kim"},
                "policy": "explicit_user_decision",
            },
        }
        response = call_memory_cli(promote_envelope, memory_repo_path=_MEMORY_REPO_PATH, store_path=store_path)
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["record"]["status"], "active")


if __name__ == "__main__":
    unittest.main()
