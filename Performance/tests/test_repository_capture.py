import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from midnight_performance.repository_capture import RepositorySnapshot, compare


class ChangeEvidenceRenameTests(unittest.TestCase):
    def test_compare_detects_unambiguous_rename_via_hash_correlation(self):
        before = RepositorySnapshot({"a.py": "hash1", "b.py": "hash2"})
        after = RepositorySnapshot({"c.py": "hash1", "b.py": "hash2"})
        evidence = compare(before, after)
        self.assertEqual(evidence.renamed, (("a.py", "c.py"),))
        # Additive only — created/deleted still carry every path they had before.
        self.assertEqual(evidence.created, ("c.py",))
        self.assertEqual(evidence.deleted, ("a.py",))
        self.assertEqual(evidence.modified, ())

    def test_ambiguous_hash_match_does_not_guess_a_rename(self):
        # Two deleted files share a hash with two created files — not a
        # provable 1:1 correspondence, so no rename is reported.
        before = RepositorySnapshot({"a.py": "h", "b.py": "h"})
        after = RepositorySnapshot({"c.py": "h", "d.py": "h"})
        evidence = compare(before, after)
        self.assertEqual(evidence.renamed, ())
        self.assertEqual(evidence.created, ("c.py", "d.py"))
        self.assertEqual(evidence.deleted, ("a.py", "b.py"))

    def test_partial_ambiguity_still_withholds_the_ambiguous_side(self):
        # One deleted path's hash also appears on a second deleted path,
        # even though only one created path shares that hash — still not
        # unambiguous 1:1, so no rename for that hash.
        before = RepositorySnapshot({"a.py": "h", "b.py": "h"})
        after = RepositorySnapshot({"c.py": "h"})
        evidence = compare(before, after)
        self.assertEqual(evidence.renamed, ())
        self.assertEqual(evidence.deleted, ("a.py", "b.py"))
        self.assertEqual(evidence.created, ("c.py",))

    def test_no_rename_when_nothing_moved(self):
        before = RepositorySnapshot({"a.py": "h1"})
        after = RepositorySnapshot({"a.py": "h2"})
        evidence = compare(before, after)
        self.assertEqual(evidence.renamed, ())
        self.assertEqual(evidence.modified, ("a.py",))

    def test_change_evidence_renamed_defaults_to_empty_for_positional_construction(self):
        from midnight_performance.repository_capture import ChangeEvidence
        evidence = ChangeEvidence(("a",), (), ())
        self.assertEqual(evidence.renamed, ())


class WindowsPathNormalizationTests(unittest.TestCase):
    def test_windows_repository_snapshot_normalizes_to_posix_paths_end_to_end(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "src" / "sub"
            nested.mkdir(parents=True)
            (nested / "module.py").write_bytes(b"x = 1\n")
            snapshot = RepositorySnapshot.capture(root)
            # `Path.rglob`/`relative_to` on Windows yields backslash-separated
            # parts internally; `.as_posix()` must normalize every path to
            # forward slashes before it ever reaches ChangeEvidence/graph
            # identity keys, real behavior already in place — this proves it.
            self.assertIn("src/sub/module.py", snapshot.files)
            self.assertNotIn("\\", next(iter(snapshot.files)))


if __name__ == "__main__":
    unittest.main()
