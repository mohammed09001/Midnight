"""Repo Intelligent entity resolution: hierarchy, classification, incremental upsert."""

import unittest
from datetime import datetime, timezone

from midnight_performance.contracts import deterministic_identity, EntityKind
from midnight_performance.repository_capture import RepositorySnapshot
from midnight_performance.repository_entity_resolution import (
    FileChangeStatus,
    resolve_file_change,
)
from midnight_performance.repo_intelligence.contracts import ProjectEntityRefKind
from midnight_performance.repo_intelligence.entity_resolution import (
    ENTITY_RESOLVER_TOOL,
    bootstrap_entity_refs,
    classify_entity_kind,
    entity_ref,
    index_refs_by_path,
    package_dirs_from_snapshot,
    symbol_refs_from_resolved,
    upsert_entity_refs,
)

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
PROJECT = deterministic_identity(EntityKind.PROJECT, "alpha")


class ClassificationTests(unittest.TestCase):
    def test_roles_are_classified_deterministically(self):
        cases = {
            "tests/test_auth.py": ProjectEntityRefKind.TEST,
            "src/test_auth.py": ProjectEntityRefKind.TEST,
            "src/auth_test.py": ProjectEntityRefKind.TEST,
            "src/auth.py": ProjectEntityRefKind.MODULE,
            "pyproject.toml": ProjectEntityRefKind.CONFIG,
            "config/settings.yaml": ProjectEntityRefKind.CONFIG,
            "README.md": ProjectEntityRefKind.DOC,
            "docs/guide.rst": ProjectEntityRefKind.DOC,
            "assets/logo.svg": ProjectEntityRefKind.FILE,
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(classify_entity_kind(path), expected)

    def test_blank_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            classify_entity_kind("  ")


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_builds_hierarchy_with_packages_and_repository(self):
        snapshot = RepositorySnapshot(
            files={
                "src/midnight/__init__.py": "a" * 64,
                "src/midnight/ledger.py": "b" * 64,
                "tests/test_ledger.py": "c" * 64,
            }
        )
        refs = bootstrap_entity_refs(PROJECT, "alpha", snapshot, now=NOW)
        kinds = {path: ref.ref_kind for path, ref in ((r.path, r) for r in refs.values())}
        self.assertIn(ProjectEntityRefKind.REPOSITORY, [r.ref_kind for r in refs.values()])
        self.assertIn(ProjectEntityRefKind.PACKAGE, [r.ref_kind for r in refs.values()])
        self.assertEqual(kinds["tests/test_ledger.py"], ProjectEntityRefKind.TEST)
        self.assertEqual(kinds["src/midnight/ledger.py"], ProjectEntityRefKind.MODULE)
        package_ref = [r for r in refs.values() if r.ref_kind is ProjectEntityRefKind.PACKAGE][0]
        self.assertEqual(package_ref.path, "src/midnight")

    def test_package_dirs_from_snapshot(self):
        snapshot = RepositorySnapshot(
            files={"pkg/__init__.py": "a" * 64, "pkg/deep/__init__.py": "b" * 64, "plain.py": "c" * 64}
        )
        self.assertEqual(package_dirs_from_snapshot(snapshot), frozenset({"pkg", "pkg/deep"}))


class IncrementalUpsertTests(unittest.TestCase):
    def test_incremental_upsert_preserves_first_seen_and_updates_freshness(self):
        initial = upsert_entity_refs(
            {},
            PROJECT,
            "alpha",
            touched=[("src/auth.py", "a" * 64)],
            now=NOW,
        )[0]
        self.assertEqual(len(initial), 2)  # repository + file
        first_seen = initial[
            entity_ref(PROJECT, "alpha", "src/auth.py", now=NOW).identity.canonical
        ].first_seen_at

        updated, written = upsert_entity_refs(
            initial,
            PROJECT,
            "alpha",
            touched=[("src/auth.py", "d" * 64)],
            now=LATER,
        )
        ref = updated[
            entity_ref(PROJECT, "alpha", "src/auth.py", now=NOW).identity.canonical
        ]
        self.assertEqual(ref.first_seen_at, first_seen)
        self.assertEqual(ref.last_seen_at, LATER)
        self.assertEqual(ref.content_digest, "d" * 64)
        self.assertEqual(len(written), 2)

    def test_touched_paths_add_package_containers_when_known(self):
        updated, _ = upsert_entity_refs(
            {},
            PROJECT,
            "alpha",
            touched=[("src/midnight/ledger.py", None)],
            package_dirs=frozenset({"src/midnight"}),
            now=NOW,
        )
        self.assertTrue(any(r.ref_kind is ProjectEntityRefKind.PACKAGE and r.path == "src/midnight" for r in updated.values()))

    def test_windows_path_separators_are_normalized(self):
        updated, _ = upsert_entity_refs(
            {}, PROJECT, "alpha", touched=[("src\\auth.py", None)], now=NOW
        )
        self.assertTrue(any(r.path == "src/auth.py" for r in updated.values()))

    def test_naive_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            upsert_entity_refs({}, PROJECT, "alpha", touched=[("a.py", None)], now=datetime(2026, 9, 1))


class SymbolMappingTests(unittest.TestCase):
    def test_symbols_and_regions_map_to_entity_refs_with_canonical_resolvers(self):
        content = (
            b"class TokenRefresh:\n"
            b"    def refresh(self):\n"
            b"        return 'token'\n"
        )
        resolved = resolve_file_change(
            repository_key="alpha",
            change_set_id="cs-1",
            path="src/auth.py",
            previous_path=None,
            status=FileChangeStatus.CREATED,
            before=None,
            after=content,
        )
        refs = symbol_refs_from_resolved(PROJECT, "alpha", resolved, now=NOW)
        self.assertTrue(refs)
        symbols = [r for r in refs if r.ref_kind is ProjectEntityRefKind.SYMBOL]
        self.assertTrue(symbols)
        self.assertEqual(
            {r.resolver_tool for r in symbols}, {"stdlib-ast"}
        )
        for ref in refs:
            self.assertEqual(ref.repository_key, "alpha")
            self.assertEqual(ref.path, "src/auth.py")

    def test_identity_is_content_independent(self):
        one = entity_ref(PROJECT, "alpha", "src/auth.py", now=NOW)
        two = entity_ref(PROJECT, "alpha", "src/auth.py", now=LATER)
        self.assertEqual(one.identity, two.identity)
        self.assertEqual(one.resolver_tool, ENTITY_RESOLVER_TOOL)


class IndexTests(unittest.TestCase):
    def test_index_refs_by_path_skips_repository_and_prefers_freshest(self):
        old = entity_ref(PROJECT, "alpha", "src/auth.py", now=NOW)
        new = entity_ref(PROJECT, "alpha", "src/auth.py", now=LATER)
        repo = entity_ref(
            PROJECT, "alpha", None, now=NOW, ref_kind=ProjectEntityRefKind.REPOSITORY
        )
        index = index_refs_by_path([old, new, repo])
        self.assertEqual(index["src/auth.py"], new)
        self.assertEqual(len(index), 1)


if __name__ == "__main__":
    unittest.main()
