import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from midnight_performance.project_descriptor import (
    ProjectDescriptorError,
    resolve_project_descriptor,
)


class ProjectDescriptorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "Performance" / "data").mkdir(parents=True)

    def write_descriptor(self, document: object) -> None:
        (self.root / "midnight.project.json").write_text(json.dumps(document), encoding="utf-8")

    def test_valid_descriptor_resolves(self):
        self.write_descriptor(
            {"descriptorVersion": 1, "projectId": "midnight", "performanceDataDir": "Performance/data", "workspaceId": None}
        )
        descriptor = resolve_project_descriptor(self.root / "desktop" / "host")
        self.assertEqual(descriptor.project_id, "midnight")
        self.assertEqual(descriptor.performance_data_dir, (self.root / "Performance" / "data").resolve())

    def test_missing_descriptor_is_rejected(self):
        with self.assertRaises(ProjectDescriptorError):
            resolve_project_descriptor(self.root)

    def test_malformed_json_is_rejected(self):
        (self.root / "midnight.project.json").write_text("{not-json", encoding="utf-8")
        with self.assertRaises(ProjectDescriptorError):
            resolve_project_descriptor(self.root)

    def test_schema_violation_is_rejected(self):
        self.write_descriptor({"descriptorVersion": 1, "projectId": "midnight"})  # missing performanceDataDir
        with self.assertRaises(ProjectDescriptorError):
            resolve_project_descriptor(self.root)

    def test_path_traversal_outside_project_root_is_rejected(self):
        self.write_descriptor(
            {"descriptorVersion": 1, "projectId": "midnight", "performanceDataDir": "../outside", "workspaceId": None}
        )
        with self.assertRaises(ProjectDescriptorError):
            resolve_project_descriptor(self.root)

    def test_extra_unknown_field_is_rejected(self):
        self.write_descriptor(
            {
                "descriptorVersion": 1,
                "projectId": "midnight",
                "performanceDataDir": "Performance/data",
                "unexpectedField": "nope",
            }
        )
        with self.assertRaises(ProjectDescriptorError):
            resolve_project_descriptor(self.root)


if __name__ == "__main__":
    unittest.main()
