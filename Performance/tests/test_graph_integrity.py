import unittest

from midnight_performance import (
    EntityKind,
    IntegrityMode,
    IntegritySeverity,
    PromptRun,
    VisualNodeMetadata,
    build_graph,
    build_performance_visual_map,
    deterministic_identity,
    validate_graph_integrity,
)

PROJECT_KEY = "integrity-project"


class GraphIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)

    def test_isolated_root_qualifies(self):
        run = PromptRun("run-1", None, gaps=("unavailable:prompt_version",))
        graph = build_graph(run)
        root = deterministic_identity(EntityKind.PROMPT_RUN, "run-1")
        visual_map = build_performance_visual_map(graph, project_context=self.project.canonical)
        report = validate_graph_integrity(graph, visual_map, project=self.project, root=root, truncated=False)
        self.assertTrue(report.qualifies)
        self.assertFalse(any(f.kind == "missing_root" for f in report.findings))

    def test_missing_root_is_an_error(self):
        run = PromptRun("run-1", None, gaps=("unavailable:prompt_version",))
        graph = build_graph(run)
        wrong_root = deterministic_identity(EntityKind.PROMPT_RUN, "some-other-run")
        visual_map = build_performance_visual_map(graph, project_context=self.project.canonical)
        report = validate_graph_integrity(graph, visual_map, project=self.project, root=wrong_root, truncated=False)
        self.assertFalse(report.qualifies)
        self.assertTrue(any(f.kind == "missing_root" and f.severity is IntegritySeverity.ERROR for f in report.findings))

    def test_cross_project_node_is_an_error(self):
        run = PromptRun("run-1", "pv-1")
        graph = build_graph(run)
        root = deterministic_identity(EntityKind.PROMPT_RUN, "run-1")
        other_project = deterministic_identity(EntityKind.PROJECT, "a-different-project")
        version_node = deterministic_identity(EntityKind.PROMPT_VERSION, "pv-1")
        visual_map = build_performance_visual_map(
            graph, project_context=self.project.canonical,
            node_metadata={version_node: VisualNodeMetadata(project_context=other_project.canonical)},
        )
        report = validate_graph_integrity(graph, visual_map, project=self.project, root=root, truncated=False)
        self.assertFalse(report.qualifies)
        self.assertTrue(any(f.kind == "cross_project_node" and f.severity is IntegritySeverity.ERROR for f in report.findings))

    def test_missing_project_context_is_a_warning_not_an_error(self):
        run = PromptRun("run-1", "pv-1")
        graph = build_graph(run)
        root = deterministic_identity(EntityKind.PROMPT_RUN, "run-1")
        # No project_context supplied anywhere — every node defaults to None.
        visual_map = build_performance_visual_map(graph)
        report = validate_graph_integrity(graph, visual_map, project=self.project, root=root, truncated=False)
        self.assertTrue(report.qualifies)  # warnings alone don't disqualify
        self.assertTrue(any(f.kind == "missing_project_context" and f.severity is IntegritySeverity.WARNING for f in report.findings))

    def test_truncation_is_reported_explicitly(self):
        run = PromptRun("run-1", "pv-1")
        graph = build_graph(run)
        root = deterministic_identity(EntityKind.PROMPT_RUN, "run-1")
        visual_map = build_performance_visual_map(graph, project_context=self.project.canonical)
        report = validate_graph_integrity(graph, visual_map, project=self.project, root=root, truncated=True)
        self.assertTrue(any(f.kind == "truncated" for f in report.findings))

    def test_strict_mode_field_is_recorded(self):
        run = PromptRun("run-1", "pv-1")
        graph = build_graph(run)
        root = deterministic_identity(EntityKind.PROMPT_RUN, "run-1")
        visual_map = build_performance_visual_map(graph, project_context=self.project.canonical)
        report = validate_graph_integrity(graph, visual_map, project=self.project, root=root, truncated=False, mode=IntegrityMode.STRICT)
        self.assertEqual(report.mode, IntegrityMode.STRICT)


if __name__ == "__main__":
    unittest.main()
