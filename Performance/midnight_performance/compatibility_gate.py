"""Task 23 (Midnight Memory Execution 08): the Midnight Memory + Performance
compatibility gate.

A thin composition layer, not a new qualification authority: every clause
below shells out to or calls a real, already-existing, already-tested
capability — Memory's own `gate run` (Task 46, `src/engine/gate.ts`, 8
Memory-internal product-truth clauses), the real bridge round trip
(`memory_bridge.py`), the orphaned-but-real `qualify_memory_integration()`
(`evaluation_memory_qualification.py`), and the bridge's own real pytest
suites. This module invents no new store, transport, or authority; it only
aggregates existing fresh evidence into one pass/fail report with named
failing clauses, because today proving Memory+Performance compatibility
requires separately running `npm test`/`gate run` in Memory and `pytest` in
Performance and eyeballing both.

Report shape deliberately mirrors `ProductTruthGateReport`/`GateClause`
(`src/engine/gate.ts`) so the two reports read the same way.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from .contracts import ClaimKind, EntityKind, deterministic_identity, new_identity
from .evaluation_memory_qualification import qualify_memory_integration
from .memory_bridge import (
    MemoryContractError,
    MemoryUnavailableError,
    build_propose_envelope,
    call_memory_cli,
    lesson_from_sealed_envelope,
    propose_lesson_or_degrade,
    read_performance_context,
)
from .observation_model import Observation, ObservationEnvelope, ObservationLayer, ObservationType
from .provenance import seal

_DEFAULT_PROJECT_KEY = "compatibility-gate"


@dataclass(frozen=True, slots=True)
class CompatibilityCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CompatibilityClause:
    clause: str
    checks: tuple[CompatibilityCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


@dataclass(frozen=True, slots=True)
class CompatibilityGateReport:
    clauses: tuple[CompatibilityClause, ...]
    passed: bool


def _check(name: str, passed: bool, detail: str) -> CompatibilityCheck:
    return CompatibilityCheck(name, passed, detail)


def _run_cli(
    args: list[str],
    *,
    memory_repo_path: str | os.PathLike,
    node_executable: str = "node",
    timeout_seconds: float = 60.0,
) -> subprocess.CompletedProcess:
    """Run a Memory CLI subcommand that is not part of the versioned
    `contract call` envelope (e.g. `scope create`, `gate run`) — the same
    subprocess pattern `call_memory_cli` uses for `contract call` itself,
    reused here for the CLI-only surfaces those tests already rely on."""
    cli_path = os.path.join(str(memory_repo_path), "src", "cli", "cli.ts")
    argv = [node_executable, "--experimental-strip-types", cli_path, *args]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        raise MemoryUnavailableError(f"node executable '{node_executable}' not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise MemoryUnavailableError(f"Memory CLI call timed out after {timeout_seconds}s") from exc


def _memory_product_truth_clause(
    *, memory_repo_path: str | os.PathLike, node_executable: str, timeout_seconds: float,
) -> CompatibilityClause:
    """Reuses Memory's own 8-clause `gate run` verbatim — zero duplicated
    logic — and flattens its clauses into checks here."""
    try:
        proc = _run_cli(
            ["gate", "run"], memory_repo_path=memory_repo_path,
            node_executable=node_executable, timeout_seconds=timeout_seconds,
        )
    except MemoryUnavailableError as exc:
        return CompatibilityClause("memory_product_truth", (_check("memory:gate-run", False, str(exc)),))
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return CompatibilityClause(
            "memory_product_truth",
            (_check(
                "memory:gate-run", False,
                f"gate run produced non-JSON stdout (exit {proc.returncode}): stdout={proc.stdout!r} stderr={proc.stderr!r}",
            ),),
        )
    if "clauses" not in report:
        return CompatibilityClause(
            "memory_product_truth",
            (_check("memory:gate-run", False, f"gate run returned no clauses (exit {proc.returncode}): {report}"),),
        )
    checks = tuple(
        _check(f"memory:{clause['clause']}:{c['name']}", bool(c["pass"]), c["detail"])
        for clause in report["clauses"]
        for c in clause["checks"]
    )
    return CompatibilityClause("memory_product_truth", checks)


def _sealed_lesson(subject: str, content: str) -> dict:
    project = deterministic_identity(EntityKind.PROJECT, "compatibility-gate")
    observation = Observation(
        identity=new_identity(EntityKind.TOOL_OBSERVATION),
        claim_kind=ClaimKind.OBSERVED,
        subject=new_identity(EntityKind.AGENT_RUN),
        payload={},
    )
    envelope = seal(ObservationEnvelope(
        observation=observation, project=project,
        observation_type=ObservationType.TOOL, layer=ObservationLayer.RAW,
        provider="compatibility-gate", provider_event_id="compat-1",
    ))
    return lesson_from_sealed_envelope(envelope, subject=subject, content=content)


def _performance_to_memory_propose_clause(
    *, store_path: str, memory_repo_path: str | os.PathLike, node_executable: str,
    timeout_seconds: float, project_key: str,
) -> CompatibilityClause:
    lesson = _sealed_lesson("Compatibility gate proposal", "gate proof")
    envelope = build_propose_envelope(project_key, [lesson])
    try:
        response = call_memory_cli(
            envelope, memory_repo_path=memory_repo_path, store_path=store_path,
            node_executable=node_executable, timeout_seconds=timeout_seconds,
        )
    except (MemoryUnavailableError, MemoryContractError) as exc:
        return CompatibilityClause("performance_to_memory_propose", (_check("propose-real-round-trip", False, str(exc)),))
    accepted = response.get("result", {}).get("accepted", [])
    rejected = response.get("result", {}).get("rejected", [])
    ok = response.get("ok") is True and len(accepted) == 1
    detail = f"accepted={len(accepted)} rejected={len(rejected)}"
    return CompatibilityClause("performance_to_memory_propose", (_check("propose-real-round-trip", ok, detail),))


def _memory_to_performance_read_clause(
    *, store_path: str, memory_repo_path: str | os.PathLike, node_executable: str,
    timeout_seconds: float, project_key: str,
) -> CompatibilityClause:
    try:
        added = _run_cli(
            [
                "record", "add", "--scope", project_key, "--subject", "Compatibility gate record",
                "--content", "gate proof", "--evidence", "external:compat-gate-1",
                "--source-kind", "user_note", "--store", store_path,
            ],
            memory_repo_path=memory_repo_path, node_executable=node_executable, timeout_seconds=timeout_seconds,
        )
    except MemoryUnavailableError as exc:
        return CompatibilityClause("memory_to_performance_read", (_check("read-real-round-trip", False, str(exc)),))
    if added.returncode != 0:
        detail = f"record add failed (exit {added.returncode}): {added.stderr}"
        return CompatibilityClause("memory_to_performance_read", (_check("read-real-round-trip", False, detail),))

    result = read_performance_context(
        project_key, memory_repo_path=memory_repo_path, store_path=store_path,
        node_executable=node_executable, timeout_seconds=timeout_seconds,
    )
    if not result.available:
        detail = f"read unavailable: {result.error_code} {result.error_message}"
        return CompatibilityClause("memory_to_performance_read", (_check("read-real-round-trip", False, detail),))
    task13_fields_present = len(result.records) >= 1 and all(
        field in result.records[0] for field in ("contradiction", "evidenceGaps", "trace")
    )
    ok = result.available and task13_fields_present
    detail = f"{len(result.records)} record(s) read back; Task 13 fields present={task13_fields_present}"
    return CompatibilityClause("memory_to_performance_read", (_check("read-real-round-trip", ok, detail),))


def _standalone_degraded_operation_clause(*, memory_repo_path: str | os.PathLike) -> CompatibilityClause:
    envelope = build_propose_envelope("compat-gate-standalone", [])
    result = propose_lesson_or_degrade(
        envelope, memory_repo_path=memory_repo_path, node_executable="definitely-not-a-real-binary-xyz",
    )
    ok = result.delivered is False and result.degraded_reason is not None
    detail = f"delivered={result.delivered} degraded_reason={result.degraded_reason!r}"
    return CompatibilityClause("standalone_degraded_operation", (_check("truthful-degrade-when-unreachable", ok, detail),))


def _no_local_duplicate_authority_clause() -> CompatibilityClause:
    result = qualify_memory_integration()
    detail = "; ".join(result.failures) if result.failures else "no KnowledgeRecord/promote/supersede present in midnight_performance.memory"
    return CompatibilityClause(
        "no_local_duplicate_authority",
        (_check("structural-no-duplicate-authority", result.no_local_duplicate_authority, detail),),
    )


_BRIDGE_TEST_FILES = (
    "test_memory_bridge.py",
    "test_memory_bridge_recovery.py",
    "test_evaluation_memory_qualification.py",
)


def _cross_language_test_suites_clause(*, test_suite_timeout_seconds: float) -> CompatibilityClause:
    tests_dir = Path(__file__).resolve().parent.parent / "tests"
    targets = [str(tests_dir / name) for name in _BRIDGE_TEST_FILES]
    args = [sys.executable, "-m", "pytest", *targets, "-q"]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=test_suite_timeout_seconds, cwd=str(tests_dir.parent),
        )
    except subprocess.TimeoutExpired:
        detail = f"pytest timed out after {test_suite_timeout_seconds}s"
        return CompatibilityClause("cross_language_test_suites", (_check("bridge-test-suites", False, detail),))
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    summary = lines[-1] if lines else (proc.stderr.strip() or f"pytest exited {proc.returncode} with no output")
    return CompatibilityClause("cross_language_test_suites", (_check("bridge-test-suites", proc.returncode == 0, summary),))


def run_compatibility_gate(
    *,
    memory_repo_path: str | os.PathLike,
    node_executable: str = "node",
    timeout_seconds: float = 60.0,
    test_suite_timeout_seconds: float = 180.0,
) -> CompatibilityGateReport:
    """Run every clause against a disposable scratch store; the caller's
    store is never touched (mirrors `gate.ts`'s own principle)."""
    store_dir = mkdtemp()
    store_path = str(Path(store_dir) / "compatibility-gate.db")
    project_key = _DEFAULT_PROJECT_KEY

    clauses: list[CompatibilityClause] = [
        _memory_product_truth_clause(
            memory_repo_path=memory_repo_path, node_executable=node_executable, timeout_seconds=timeout_seconds,
        ),
    ]

    scope_error: str | None = None
    try:
        created = _run_cli(
            ["scope", "create", "--key", project_key, "--name", "Compatibility Gate", "--store", store_path],
            memory_repo_path=memory_repo_path, node_executable=node_executable, timeout_seconds=timeout_seconds,
        )
        if created.returncode != 0:
            scope_error = f"scope create failed (exit {created.returncode}): {created.stderr}"
    except MemoryUnavailableError as exc:
        scope_error = str(exc)

    if scope_error is not None:
        clauses.append(CompatibilityClause("performance_to_memory_propose", (_check("propose-real-round-trip", False, scope_error),)))
        clauses.append(CompatibilityClause("memory_to_performance_read", (_check("read-real-round-trip", False, scope_error),)))
    else:
        clauses.append(_performance_to_memory_propose_clause(
            store_path=store_path, memory_repo_path=memory_repo_path, node_executable=node_executable,
            timeout_seconds=timeout_seconds, project_key=project_key,
        ))
        clauses.append(_memory_to_performance_read_clause(
            store_path=store_path, memory_repo_path=memory_repo_path, node_executable=node_executable,
            timeout_seconds=timeout_seconds, project_key=project_key,
        ))

    clauses.append(_standalone_degraded_operation_clause(memory_repo_path=memory_repo_path))
    clauses.append(_no_local_duplicate_authority_clause())
    clauses.append(_cross_language_test_suites_clause(test_suite_timeout_seconds=test_suite_timeout_seconds))

    return CompatibilityGateReport(tuple(clauses), all(clause.passed for clause in clauses))


def _report_to_json(report: CompatibilityGateReport) -> str:
    payload = {
        "passed": report.passed,
        "clauses": [
            {
                "clause": clause.clause,
                "passed": clause.passed,
                "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in clause.checks],
            }
            for clause in report.clauses
        ],
    }
    return json.dumps(payload, indent=2)


def main() -> int:
    import argparse

    default_memory_repo = Path(__file__).resolve().parents[2] / "Memory"
    parser = argparse.ArgumentParser(description="Midnight Memory + Performance compatibility gate")
    parser.add_argument("--path", help="write the report as JSON to this path")
    parser.add_argument("--memory-repo-path", default=str(default_memory_repo))
    args = parser.parse_args()

    report = run_compatibility_gate(memory_repo_path=args.memory_repo_path)
    text = _report_to_json(report)
    print(text)
    if args.path:
        Path(args.path).write_text(text, encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
