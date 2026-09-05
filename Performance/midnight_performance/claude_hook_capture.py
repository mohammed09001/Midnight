"""Real ``UserPromptSubmit`` hook entrypoint for Claude Code (Execution 04,
Section B).

Every other adapter in this package only NORMALIZES an already-supplied
payload; this module is the one place Performance is actually invoked BY a
coding harness, so it is held to a stricter, machine-verified contract than
"normalize what you're given." Confirmed live against the current hooks
reference (code.claude.com/docs/en/hooks, researched 2026-09):

* ANY stdout this hook writes on exit code 0 is injected as context Claude
  can see and act on, unconditionally — so this hook writes ZERO stdout
  bytes, on every path, success or failure.
* Exit code 2 blocks and ERASES the user's prompt entirely — it never
  reaches Claude. This hook therefore NEVER exits 2, and in fact never
  exits anything but 0: a Midnight capture failure must not intentionally
  stop Claude from receiving the user's prompt, and the only way to
  guarantee that under every internal failure mode is to never emit a
  blocking exit code at all.
* The default timeout for this specific hook is 30s; this module bounds its
  own work well under that (see ``_CAPTURE_TIMEOUT_SECONDS``) so Midnight's
  own capture can never be the reason Claude's hook timeout is hit.
* Claude Code runs multiple hook processes for the same event in parallel
  as normal, expected behavior (not a rare edge case) — this is exactly
  the scenario ``EvidenceLedger``'s cross-process file lock
  (``ledger.py``) exists to make safe.

Identity is derived ONLY from ``session_id``/``prompt_id`` — never from
prompt text (Section E's explicit ban on mutable-text-derived identity).
Internal failures remain diagnosable via stderr and a best-effort local log
file, never via stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from pathlib import Path

from .claude_adapter import normalize_claude_hook
from .prompt_capture import record_prompt_run

_CAPTURE_TIMEOUT_SECONDS = 8.0
_DEFAULT_PROJECT_KEY = "midnight"
_PROVIDER = "claude-code"
_DIAGNOSTIC_LOG_NAME = "hook_diagnostics.log"


def _read_stdin_payload() -> dict:
    """Best-effort, bounded stdin JSON parse. `{}` on any failure — a
    malformed payload must degrade to a gap, never crash toward stdout."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _prompt_run_identity(raw: dict) -> str | None:
    """Deterministic identity from `session_id:prompt_id` ONLY — never from
    prompt text, which is mutable and not evidence of stable identity."""
    session_id = raw.get("session_id")
    prompt_id = raw.get("prompt_id")
    if isinstance(session_id, str) and session_id.strip() and isinstance(prompt_id, str) and prompt_id.strip():
        return f"{session_id}:{prompt_id}"
    return None


def capture_user_prompt_submit(raw: dict, *, ledger_path: Path, project_key: str) -> tuple[bool, tuple[str, ...]]:
    """Normalize + durably record one occurrence. Returns (appended, gaps).

    Raises on internal failure — the caller (`main`) is solely responsible
    for turning any exception into a silent, non-blocking, stdout-empty
    exit 0; this function itself stays honest and lets failures surface.
    """
    observed = normalize_claude_hook(raw)
    gaps = list(observed.gaps)
    identity = _prompt_run_identity(raw)
    if identity is None:
        gaps.append("unavailable:prompt_run_identity")
        return False, tuple(gaps)
    appended, _canonical = record_prompt_run(
        ledger_path, project_key, _PROVIDER, identity, observed_at=datetime.now(timezone.utc),
    )
    return appended, tuple(gaps)


def _diagnose(data_dir: Path | None, message: str) -> None:
    """Write a diagnosable failure record. stderr first (never stdout);
    the local log write is itself failure-isolated so a broken disk/path
    can never escalate this into a blocking exit."""
    try:
        sys.stderr.write(f"[midnight-claude-hook] {message}\n")
    except Exception:
        pass
    if data_dir is None:
        return
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with (data_dir / _DIAGNOSTIC_LOG_NAME).open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    # Everything below — including argument parsing — is wrapped in one
    # blanket handler. argparse itself calls `sys.exit(2)` on a missing
    # required argument or malformed input by default, which is exactly the
    # blocking exit code this hook must never emit; `exit_on_error=False`
    # asks it to raise instead where it can, and the `except SystemExit`
    # below is the hard backstop for whatever it still exits on (including
    # `--help`). Catching bare `BaseException` (not just `Exception`) is
    # deliberate and narrowly scoped to this one entrypoint: the documented
    # contract is that this hook NEVER exits anything but 0, under ANY
    # internal-failure mode, full stop.
    data_dir: Path | None = None
    try:
        parser = argparse.ArgumentParser(
            description="Claude Code UserPromptSubmit observer: captures a Prompt Run occurrence, never blocks or contaminates Claude's context.",
            exit_on_error=False,
        )
        parser.add_argument("--data-dir", type=Path, required=True, help="project ledger directory containing evidence.jsonl")
        parser.add_argument("--project", default=_DEFAULT_PROJECT_KEY, help="local project key (deterministic identity input)")
        args = parser.parse_args(argv)
        data_dir = args.data_dir

        raw = _read_stdin_payload()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                capture_user_prompt_submit, raw, ledger_path=args.data_dir / "evidence.jsonl", project_key=args.project,
            )
            try:
                appended, gaps = future.result(timeout=_CAPTURE_TIMEOUT_SECONDS)
                if gaps:
                    _diagnose(data_dir, f"capture completed with gaps={list(gaps)} appended={appended}")
            except FutureTimeoutError:
                _diagnose(data_dir, f"capture exceeded {_CAPTURE_TIMEOUT_SECONDS}s internal timeout; abandoning without blocking Claude")
    except SystemExit as exc:
        _diagnose(data_dir, f"argument parsing requested exit code {exc.code!r}; suppressed, never propagated")
    except BaseException:  # noqa: BLE001 - see contract note above: this hook must NEVER exit anything but 0
        _diagnose(data_dir, f"internal capture failure: {traceback.format_exc()}")

    # Contract, unconditional: zero stdout bytes, exit 0, always — a Midnight
    # capture failure must never stop Claude from receiving the user's prompt.
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
