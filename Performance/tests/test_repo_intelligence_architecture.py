"""Repo Intelligent architecture invariants, proven from the package source.

These checks fail the build if the foundation ever grows direct sibling
database access, its own durable-memory authority, or unportable
network/model calls outside the port layer.
"""

import ast
import unittest
from pathlib import Path

PACKAGE_DIR = Path("midnight_performance") / "repo_intelligence"

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "sqlite3",
        "requests",
        "urllib",
        "http",
        "socket",
        "ssl",
        "subprocess",
        "ctypes",
        "asyncio",
        "multiprocessing",
    }
)

ALLOWED_PERFORMANCE_IMPORTS = frozenset(
    {
        "contracts",
        "query_api",
        "memory_bridge",
        "ai_provider",
        "observation_model",
        "repository_capture",
        "repository_entity_resolution",
        "privacy",
    }
)

FORBIDDEN_MEMORY_AUTHORITY_SYMBOLS = frozenset(
    {
        "KnowledgeRecord",
        "promote",
        "supersede",
    }
)

FORBIDDEN_SOURCE_MARKERS = (
    ".sqlite",
    "Memory/",
    "Security/",
    "Watch/",
    "midnight_memory",
)


def package_sources():
    return sorted(PACKAGE_DIR.rglob("*.py"))


def imported_roots(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0] if node.level == 0 else (
                _relative_target(node)
            )
            yield root, node.module or "", node.lineno


def _relative_target(node: ast.ImportFrom) -> str:
    return (node.module or "").split(".")[0]


class ArchitectureTests(unittest.TestCase):
    def test_package_files_exist(self):
        sources = package_sources()
        self.assertGreaterEqual(len(sources), 5)

    def test_no_direct_database_or_network_imports(self):
        for path in package_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for root, module, lineno in imported_roots(tree):
                with self.subTest(file=path.name, line=lineno):
                    self.assertNotIn(
                        root,
                        FORBIDDEN_IMPORT_ROOTS,
                        f"{path}:{lineno} imports '{module}'; network/DB access belongs to port adapters",
                    )

    def test_performance_imports_stay_on_the_allowlisted_canonical_surfaces(self):
        for path in package_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level >= 2:
                    target = node.module or ""
                    with self.subTest(file=path.name, line=node.lineno, target=target):
                        self.assertIn(
                            target,
                            ALLOWED_PERFORMANCE_IMPORTS,
                            f"{path}:{node.lineno} reaches Performance module '{target}' "
                            "outside the allowed canonical contract surfaces",
                        )

    def test_no_second_durable_memory_authority(self):
        for path in package_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    with self.subTest(file=path.name, line=node.lineno):
                        self.assertNotIn(
                            node.name,
                            FORBIDDEN_MEMORY_AUTHORITY_SYMBOLS,
                            f"{path}:{node.lineno} defines '{node.name}'; durable-memory "
                            "promotion belongs to Midnight Memory via memory_bridge only",
                        )

    def test_no_sibling_storage_paths_or_engines_in_source(self):
        for path in package_sources():
            text = path.read_text(encoding="utf-8")
            for marker in FORBIDDEN_SOURCE_MARKERS:
                with self.subTest(file=path.name, marker=marker):
                    self.assertNotIn(
                        marker,
                        text,
                        f"{path} references '{marker}'; sibling products are reached "
                        "through their versioned contracts, never their storage",
                    )

    def test_core_imports_cleanly_without_optional_providers(self):
        import subprocess
        import sys

        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import midnight_performance.repo_intelligence as ri;"
                "reports = ri.RepoIntelligenceProviders().availability();"
                "assert len(reports) == 10 and not any(r.available for r in reports);"
                "print('bare-core-ok')",
            ],
            capture_output=True,
            text=True,
            cwd=".",
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("bare-core-ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
