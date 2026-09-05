import unittest

from midnight_performance.contracts import EntityKind
from midnight_performance.relationship_graph import ResolvedRepositoryEntity
from midnight_performance.repository_capture import ChangeEvidence
from midnight_performance.repository_entity_resolution import (
    FileChangeStatus,
    classify_language,
    resolve_file_change,
    resolve_repository_entities,
)

REPO = "repo-key"
CS = "cs-1"

PYTHON_SOURCE = b"""
def greet(name):
    return f"hello {name}"


class Greeter:
    def hello(self):
        return "hi"
"""

PYTHON_SYNTAX_ERROR_SOURCE = b"def broken(:\n    pass\n"


class LanguageClassificationTests(unittest.TestCase):
    def test_classifies_by_extension(self):
        self.assertEqual(classify_language("a.py", b"x"), "python")
        self.assertEqual(classify_language("a.ts", b"x"), "typescript")
        self.assertEqual(classify_language("a.tsx", b"x"), "typescript")
        self.assertEqual(classify_language("a.js", b"x"), "javascript")
        self.assertEqual(classify_language("a.jsx", b"x"), "javascript")
        self.assertEqual(classify_language("a.json", b"{}"), "config")
        self.assertEqual(classify_language("pyproject.toml", b"[project]"), "config")
        self.assertEqual(classify_language("README", b"hello"), "unknown-text")

    def test_nul_byte_evidence_classifies_as_binary_regardless_of_extension(self):
        self.assertEqual(classify_language("image.py", b"\x00\x01\x02binary"), "binary")

    def test_content_unavailable_never_guesses_binary(self):
        self.assertEqual(classify_language("mystery", None), "unknown-text")


class PythonSymbolResolutionTests(unittest.TestCase):
    def test_python_function_and_class_produce_qualified_symbols(self):
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="src/greet.py", previous_path=None,
            status=FileChangeStatus.CREATED, before=None, after=PYTHON_SOURCE,
        )
        self.assertTrue(resolved.file_change.resolver.supported)
        names = {symbol.qualified_name for symbol in resolved.symbols}
        self.assertIn("greet", names)
        self.assertIn("Greeter", names)
        self.assertIn("Greeter.hello", names)
        self.assertEqual(resolved.gaps, ())

    def test_python_syntax_error_is_an_honest_gap_no_symbols(self):
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="src/broken.py", previous_path=None,
            status=FileChangeStatus.CREATED, before=None, after=PYTHON_SYNTAX_ERROR_SOURCE,
        )
        self.assertEqual(resolved.symbols, ())
        self.assertEqual(len(resolved.gaps), 1)
        self.assertIn("unavailable:python_syntax_error", resolved.gaps[0])

    def test_modified_file_symbol_rename_carries_rename_note_not_new_identity(self):
        before = b"def old_name():\n    return 1\n"
        after = b"def new_name():\n    return 1\n"
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="src/m.py", previous_path=None,
            status=FileChangeStatus.MODIFIED, before=before, after=after,
        )
        self.assertEqual(len(resolved.symbols), 1)
        symbol = resolved.symbols[0]
        self.assertEqual(symbol.qualified_name, "new_name")
        self.assertIsNotNone(symbol.rename_note)


class TypeScriptJavaScriptFileLevelTests(unittest.TestCase):
    def test_typescript_and_javascript_stay_file_level_with_explicit_gap(self):
        # No file content available at all — nothing to bound a region from.
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="src/app.ts", previous_path=None,
            status=FileChangeStatus.DELETED, before=None, after=None,
        )
        self.assertEqual(resolved.symbols, ())
        self.assertEqual(resolved.regions, ())
        self.assertFalse(resolved.file_change.resolver.supported)

    def test_typescript_produces_a_real_code_region_not_a_symbol(self):
        before = b"export function a() {\n  return 1;\n}\n"
        after = b"export function a() {\n  return 2;\n}\nexport function b() {}\n"
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="src/app.ts", previous_path=None,
            status=FileChangeStatus.MODIFIED, before=before, after=after,
        )
        self.assertEqual(resolved.symbols, ())  # never Symbol truth for TS
        self.assertGreater(len(resolved.regions), 0)
        self.assertTrue(resolved.file_change.resolver.supported)
        self.assertIn("line-based diff evidence", resolved.file_change.resolver.uncertainty)
        self.assertNotIn("structural", resolved.file_change.resolver.uncertainty.split("never")[0])


class FileOnlyCategoryTests(unittest.TestCase):
    def test_unknown_text_language_is_file_only_with_gap(self):
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="NOTES", previous_path=None,
            status=FileChangeStatus.CREATED, before=None, after=b"just some notes",
        )
        self.assertEqual(resolved.symbols, ())
        self.assertEqual(resolved.regions, ())
        self.assertFalse(resolved.file_change.resolver.supported)
        self.assertIsNotNone(resolved.file_change.resolver.gap)

    def test_config_file_is_file_only_no_symbol_resolution_attempted(self):
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="package.json", previous_path=None,
            status=FileChangeStatus.MODIFIED, before=b"{}", after=b'{"name": "x"}',
        )
        self.assertEqual(resolved.symbols, ())
        self.assertEqual(resolved.regions, ())
        self.assertFalse(resolved.file_change.resolver.supported)

    def test_binary_file_never_has_content_inspected(self):
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="assets/logo.py", previous_path=None,
            status=FileChangeStatus.CREATED, before=None, after=b"\x00\x01\x02\x03PNGDATA",
        )
        self.assertEqual(resolved.file_change.resolver.language, "binary")
        self.assertEqual(resolved.symbols, ())
        self.assertEqual(resolved.regions, ())

    def test_deleted_file_produces_file_change_only_no_children(self):
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="src/gone.py", previous_path=None,
            status=FileChangeStatus.DELETED, before=PYTHON_SOURCE, after=None,
        )
        self.assertEqual(resolved.symbols, ())
        self.assertEqual(resolved.regions, ())
        self.assertFalse(resolved.file_change.resolver.supported)
        self.assertIn("deleted", resolved.file_change.resolver.gap)


class RenameMoveResolutionTests(unittest.TestCase):
    def test_renamed_file_resolves_to_one_file_change_not_create_plus_delete(self):
        evidence = ChangeEvidence(created=(), modified=(), deleted=(), renamed=(("old.py", "new.py"),))
        entities, gaps, labels = resolve_repository_entities(
            repository_key=REPO, change_set_id=CS, evidence=evidence,
            content_before={"old.py": PYTHON_SOURCE}, content_after={"new.py": PYTHON_SOURCE},
        )
        file_change_entities = [e for e in entities if e.parent is None]
        self.assertEqual(len(file_change_entities), 1)

    def test_renamed_path_is_never_also_processed_via_created_or_deleted(self):
        # A realistic ChangeEvidence where the renamed pair's paths ALSO
        # still appear in created/deleted (real `compare()` output — see
        # design decision 1) must still resolve to exactly one FileChange.
        evidence = ChangeEvidence(created=("new.py",), modified=(), deleted=("old.py",), renamed=(("old.py", "new.py"),))
        entities, gaps, labels = resolve_repository_entities(
            repository_key=REPO, change_set_id=CS, evidence=evidence,
            content_before={"old.py": PYTHON_SOURCE}, content_after={"new.py": PYTHON_SOURCE},
        )
        file_change_entities = [e for e in entities if e.parent is None]
        self.assertEqual(len(file_change_entities), 1)


class ResourceLimitTests(unittest.TestCase):
    def test_oversized_source_is_a_resource_bound_gap_reusing_parser_adapter_constant(self):
        from midnight_performance.parser_adapter import MAX_SOURCE_BYTES
        oversized = b"x = 1\n" * (MAX_SOURCE_BYTES // 6 + 1)
        resolved = resolve_file_change(
            repository_key=REPO, change_set_id=CS, path="src/huge.py", previous_path=None,
            status=FileChangeStatus.CREATED, before=None, after=oversized,
        )
        self.assertEqual(resolved.symbols, ())
        self.assertFalse(resolved.file_change.resolver.supported)
        self.assertEqual(resolved.file_change.resolver.gap, "source exceeds parser resource bound")


class DeterministicIdentityTests(unittest.TestCase):
    def test_resolve_repository_entities_is_replay_stable(self):
        evidence = ChangeEvidence(created=("src/a.py",), modified=(), deleted=())
        kwargs = dict(
            repository_key=REPO, change_set_id=CS, evidence=evidence,
            content_before={}, content_after={"src/a.py": PYTHON_SOURCE},
        )
        first, first_gaps, first_labels = resolve_repository_entities(**kwargs)
        second, second_gaps, second_labels = resolve_repository_entities(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first_gaps, second_gaps)

    def test_identity_changes_when_change_set_id_changes(self):
        evidence = ChangeEvidence(created=("src/a.py",), modified=(), deleted=())
        entities_a, _, _ = resolve_repository_entities(
            repository_key=REPO, change_set_id="cs-a", evidence=evidence,
            content_before={}, content_after={"src/a.py": PYTHON_SOURCE},
        )
        entities_b, _, _ = resolve_repository_entities(
            repository_key=REPO, change_set_id="cs-b", evidence=evidence,
            content_before={}, content_after={"src/a.py": PYTHON_SOURCE},
        )
        file_ids_a = {e.entity.canonical for e in entities_a if e.parent is None}
        file_ids_b = {e.entity.canonical for e in entities_b if e.parent is None}
        self.assertTrue(file_ids_a.isdisjoint(file_ids_b))


class HierarchyShapeTests(unittest.TestCase):
    def test_symbols_are_children_of_their_file_change_not_the_change_set(self):
        evidence = ChangeEvidence(created=("src/a.py",), modified=(), deleted=())
        entities, gaps, labels = resolve_repository_entities(
            repository_key=REPO, change_set_id=CS, evidence=evidence,
            content_before={}, content_after={"src/a.py": PYTHON_SOURCE},
        )
        file_entities = [e for e in entities if e.parent is None and e.entity.kind is EntityKind.FILE_CHANGE]
        symbol_entities = [e for e in entities if e.entity.kind is EntityKind.SYMBOL]
        self.assertEqual(len(file_entities), 1)
        self.assertGreater(len(symbol_entities), 0)
        for symbol_entity in symbol_entities:
            self.assertEqual(symbol_entity.parent, file_entities[0].entity)

    def test_all_entities_are_valid_resolved_repository_entity_instances(self):
        evidence = ChangeEvidence(created=("src/a.py", "src/app.ts", "README", "config.json"), modified=(), deleted=())
        entities, _, _ = resolve_repository_entities(
            repository_key=REPO, change_set_id=CS, evidence=evidence,
            content_before={},
            content_after={
                "src/a.py": PYTHON_SOURCE, "src/app.ts": b"export const x = 1;\n",
                "README": b"notes", "config.json": b"{}",
            },
        )
        self.assertTrue(all(isinstance(e, ResolvedRepositoryEntity) for e in entities))
        # Every FileChange (parent=None) is present; region/symbol children
        # never dangle without their file present in the same tuple.
        declared = {e.entity for e in entities}
        for entity in entities:
            if entity.parent is not None:
                self.assertIn(entity.parent, declared)


if __name__ == "__main__":
    unittest.main()
