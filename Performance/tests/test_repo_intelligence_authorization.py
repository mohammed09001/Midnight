"""Repo Intelligent authorization: project isolation and cache-key fail-closure."""

import unittest
from datetime import datetime, timezone
from pathlib import Path

from midnight_performance.contracts import deterministic_identity, EntityKind
from midnight_performance.repo_intelligence.authorization import (
    CrossProjectAccessError,
    REPO_INTELLIGENCE_STATE_DIRNAME,
    RepoIntelligenceAuthorization,
    cache_key,
    ensure_record_project,
    ensure_same_project,
    project_state_dir,
    require_external_access,
    require_model_access,
)
from midnight_performance.repo_intelligence.contracts import EvidenceBundle, EvidenceItem
from midnight_performance.repo_intelligence.contracts import evidence_bundle_identity
from midnight_performance.repo_intelligence.sources import SourceClass, TrustClass

PROJECT_ALPHA = deterministic_identity(EntityKind.PROJECT, "alpha")
PROJECT_BETA = deterministic_identity(EntityKind.PROJECT, "beta")


def auth(project=PROJECT_ALPHA, **overrides) -> RepoIntelligenceAuthorization:
    fields = dict(project=project, external_access=False, model_access=False)
    fields.update(overrides)
    return RepoIntelligenceAuthorization(**fields)


class AuthorizationRuleTests(unittest.TestCase):
    def test_authorization_requires_a_project_identity(self):
        with self.assertRaises(ValueError):
            RepoIntelligenceAuthorization(
                project=deterministic_identity(EntityKind.PROMPT_RUN, "alpha|1")
            )

    def test_cross_project_access_is_rejected(self):
        with self.assertRaises(CrossProjectAccessError):
            ensure_same_project(auth(), project=PROJECT_BETA)

    def test_same_project_access_is_accepted(self):
        ensure_same_project(auth(), project=PROJECT_ALPHA)

    def test_stored_records_from_another_project_fail_closed(self):
        items = (
            EvidenceItem(
                ref=deterministic_identity(EntityKind.PROMPT_RUN, "beta|1").canonical,
                source_class=SourceClass.PERFORMANCE_EVIDENCE,
                trust_class=TrustClass.FIRST_PARTY_LOCAL,
                captured_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            ),
        )
        beta_bundle = EvidenceBundle(
            identity=evidence_bundle_identity(PROJECT_BETA, items),
            project=PROJECT_BETA,
            items=items,
        )
        with self.assertRaises(CrossProjectAccessError):
            ensure_record_project(auth(project=PROJECT_ALPHA), beta_bundle.project)

    def test_external_and_model_access_are_denied_by_default(self):
        with self.assertRaises(PermissionError):
            require_external_access(auth())
        with self.assertRaises(PermissionError):
            require_model_access(auth())
        require_external_access(auth(external_access=True))
        require_model_access(auth(model_access=True))


class StateIsolationTests(unittest.TestCase):
    def test_state_dirs_are_project_isolated(self):
        data_dir = Path("Performance/data")
        alpha = project_state_dir(data_dir, PROJECT_ALPHA)
        beta = project_state_dir(data_dir, PROJECT_BETA)
        self.assertNotEqual(alpha, beta)
        self.assertEqual(alpha.parent, data_dir / REPO_INTELLIGENCE_STATE_DIRNAME)
        self.assertEqual(alpha.name, PROJECT_ALPHA.value.hex)
        with self.assertRaises(ValueError):
            project_state_dir(data_dir, deterministic_identity(EntityKind.PROMPT_RUN, "alpha|1"))

    def test_cache_keys_never_collide_across_projects(self):
        digest = "a" * 64
        alpha_key = cache_key("research-answers", PROJECT_ALPHA, digest)
        beta_key = cache_key("research-answers", PROJECT_BETA, digest)
        self.assertNotEqual(alpha_key, beta_key)
        self.assertEqual(alpha_key, cache_key("research-answers", PROJECT_ALPHA, digest))
        with self.assertRaises(ValueError):
            cache_key(" ", PROJECT_ALPHA, digest)
        with self.assertRaises(ValueError):
            cache_key("ns", PROJECT_ALPHA, " ")
        with self.assertRaises(ValueError):
            cache_key("ns", deterministic_identity(EntityKind.PROMPT_RUN, "alpha|1"), digest)


if __name__ == "__main__":
    unittest.main()
