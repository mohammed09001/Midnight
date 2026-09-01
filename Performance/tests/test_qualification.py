from midnight_performance import (
    AdapterHealth, Capability, CapabilityManifest, ChangeEvidence, EvaluationCorpus,
    FrozenEvent, FrozenPromptRun, PromptRun, QualificationState, RepositorySnapshot,
    TaskType, evaluate_frozen_run, qualify_harness,
)


def _run() -> FrozenPromptRun:
    return FrozenPromptRun(
        PromptRun("run-1", "prompt-v1"),
        "Add src/widget.py\nDo not change protected.py\nTest the widget",
        "codex",
        lifecycle_events=(
            FrozenEvent("start", {"type": "turn.started", "session_id": "s", "turn_id": "t"}),
            FrozenEvent("interrupted", {"type": "turn.interrupted", "session_id": "s", "turn_id": "t"}),
            FrozenEvent("resume", {"type": "turn.started", "state": "resumed", "session_id": "s", "turn_id": "t"}),
            FrozenEvent("complete", {"type": "turn.completed", "session_id": "s", "turn_id": "t"}),
        ),
        tool_events=(
            FrozenEvent("files", {"type": "item.file_change", "session_id": "s", "path": "src/widget.py"}),
            FrozenEvent("files-again", {"type": "item.file_change", "session_id": "s", "path": "src/widget.py"}),
        ),
        baseline=RepositorySnapshot({"protected.py": "old"}),
        final=RepositorySnapshot({"protected.py": "old", "src/widget.py": "new", "tests/test_widget.py": "new"}),
        requested_scope=("src/widget.py",), task_type=TaskType.FEATURE_ADDITION,
        expected_scores={"requirement_coverage": 1.0},
    )


def test_frozen_corpus_is_versioned_replayable_and_measures_known_changes():
    run = _run()
    corpus = EvaluationCorpus("1", (run,))
    assert corpus.replay() == (run,)
    assert corpus.fingerprint == EvaluationCorpus("1", (run,)).fingerprint
    result = evaluate_frozen_run(run)
    assert result.changes.created == ("src/widget.py", "tests/test_widget.py")
    assert not result.expected_mismatches


def test_qualification_degrades_and_reconciles_native_events_to_repository_truth():
    run = _run()
    # Replayed transport delivery uses the same id and is idempotently ignored;
    # a distinct, unreconciled native claim remains explicit.
    duplicate = FrozenPromptRun(**{name: getattr(run, name) for name in run.__dataclass_fields__} | {
        "tool_events": run.tool_events + (
            FrozenEvent("files", {"type": "item.file_change", "session_id": "s", "path": "src/widget.py"}),
            FrozenEvent("missing", {"type": "item.file_change", "session_id": "s", "path": "missing.py"}),
        ),
    })
    manifest = CapabilityManifest("codex", frozenset({"1"}), frozenset({Capability.COMMAND, Capability.FILE_CHANGE, Capability.TRANSCRIPT}))
    result = qualify_harness(duplicate, manifest, provider_version="1", agent_prose="Implemented missing.py and tests passed.")
    assert result.health.health is AdapterHealth.DEGRADED
    assert result.state is QualificationState.DEGRADED
    assert result.duplicate_event_ids == ("files",)
    assert result.unreconciled_native_claims == ("missing.py",)
    assert [window.state for window in result.windows] == ["started", "interrupted", "resumed", "completed"]
    assert result.repository_changes == ChangeEvidence(("src/widget.py", "tests/test_widget.py"), (), ())
    assert result.report is not None


def test_unknown_provider_drift_is_not_silently_parsed():
    run = _run()
    manifest = CapabilityManifest("codex", frozenset({"1"}), frozenset({Capability.COMMAND}))
    result = qualify_harness(run, manifest, provider_version="2")
    assert result.state is QualificationState.UNSUPPORTED
    assert "unavailable:unsupported_version:2" in result.gaps

    wrong_surface = qualify_harness(run, CapabilityManifest("opencode", frozenset({"1"}), frozenset()), provider_version="1")
    assert wrong_surface.state is QualificationState.UNSUPPORTED
    assert "unavailable:manifest-adapter:opencode" in wrong_surface.gaps


def test_each_declared_provider_surface_is_qualified_passively():
    base = _run()
    fixtures = (
        ("codex", {"type": "item.file_change", "session_id": "s", "path": "src/widget.py"}),
        ("claude-code", {"hook_event_name": "PostToolUse", "session_id": "s", "path": "src/widget.py"}),
        ("opencode", {"type": "file.changed", "session_id": "s", "adapter_version": "1", "path": "src/widget.py"}),
    )
    for provider, payload in fixtures:
        run = FrozenPromptRun(**{name: getattr(base, name) for name in base.__dataclass_fields__} | {
            "provider": provider, "lifecycle_events": (), "tool_events": (FrozenEvent("file", payload),),
        })
        result = qualify_harness(run, CapabilityManifest(provider, frozenset({"1"}), frozenset()), provider_version="1")
        assert result.state is QualificationState.QUALIFIED
        assert result.native_file_claims == ("src/widget.py",)

    assert qualify_harness(base, CapabilityManifest("codex", frozenset({"1"}), frozenset()), provider_version="1", hooks_available=False).state is QualificationState.DEGRADED
