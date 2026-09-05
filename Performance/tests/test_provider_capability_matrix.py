import unittest

from midnight_performance import (
    AdapterHealth,
    Capability,
    CODEX_ADAPTER,
    build_capability_matrix,
    CURRENT_PROVIDER_MANIFESTS,
)


class ProviderCapabilityMatrixTests(unittest.TestCase):
    def test_matrix_covers_all_three_providers(self):
        entries = build_capability_matrix(provider_versions={"claude-code": "1", "codex": "2", "opencode": "1"})
        self.assertEqual({entry.provider for entry in entries}, {"claude-code", "codex", "opencode"})

    def test_healthy_when_provider_version_matches_and_confirmed_capabilities_are_implemented(self):
        entries = build_capability_matrix(provider_versions={"claude-code": "1", "codex": "2", "opencode": "1"})
        by_provider = {entry.provider: entry for entry in entries}
        for entry in by_provider.values():
            self.assertEqual(entry.health.health, AdapterHealth.HEALTHY, f"{entry.provider}: {entry.health.gaps}")

    def test_missing_provider_version_is_reported_unavailable_not_negative_evidence(self):
        entries = build_capability_matrix(provider_versions={})
        for entry in entries:
            self.assertEqual(entry.health.health, AdapterHealth.UNAVAILABLE)
            self.assertIn("unavailable:provider_version", entry.health.gaps)

    def test_unsupported_codex_provider_version_is_flagged(self):
        entries = build_capability_matrix(provider_versions={"codex": "999"})
        codex_entry = next(entry for entry in entries if entry.provider == "codex")
        self.assertEqual(codex_entry.health.health, AdapterHealth.UNSUPPORTED_VERSION)

    def test_codex_prompt_capability_is_confirmed_and_no_longer_over_claims_verification(self):
        codex_manifest = CURRENT_PROVIDER_MANIFESTS["codex"]
        self.assertIn(Capability.PROMPT, codex_manifest.capabilities)
        self.assertIn(Capability.PROMPT, CODEX_ADAPTER.capabilities)
        entries = build_capability_matrix(provider_versions={"codex": "2"})
        codex_entry = next(entry for entry in entries if entry.provider == "codex")
        self.assertEqual(codex_entry.unconfirmed_by_research, frozenset())
        self.assertNotIn(Capability.VERIFICATION, codex_entry.implemented)
        self.assertNotIn(Capability.NATIVE_DIFF, codex_entry.implemented)

    def test_opencode_over_claims_are_surfaced_honestly_not_silently_stripped(self):
        entries = build_capability_matrix(provider_versions={"opencode": "1"})
        opencode_entry = next(entry for entry in entries if entry.provider == "opencode")
        # Confirmed by name-level research: session/prompt/tool/command/file.
        # Not stripped from the adapter on incomplete evidence, but honestly
        # flagged as not positively confirmed by this research pass.
        self.assertIn(Capability.COMPLETION, opencode_entry.unconfirmed_by_research)
        self.assertIn(Capability.SESSION_LIFECYCLE, opencode_entry.currently_confirmed)


if __name__ == "__main__":
    unittest.main()
