#!/usr/bin/env python3
"""Execution 05, Section A/J: before/after benchmark for the rebuildable
read projection.

Reuses the exact seeding methodology used to capture this execution's
ground-truth "before" numbers: a corpus is seeded by writing pre-validated
JSONL lines DIRECTLY to the ledger file, bypassing `EvidenceLedger.append`'s
own O(n) duplicate check (which makes bulk seeding via the public API
prohibitively slow at these sizes — that O(n) append cost is itself
measured separately below and reported, not fixed, per this execution's
documented scope decision).

Not a pytest test — a manual/CI dev tool, since a full 1k/10k/100k sweep
takes real wall-clock minutes. Run: `python scripts/benchmark_evidence_reads.py`
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import sys
import sqlite3
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from midnight_performance.contracts import ClaimKind, EntityKind, Observation, deterministic_identity
from midnight_performance.desktop_bridge import prompt_run_activity
from midnight_performance.ledger import EvidenceLedger
from midnight_performance.observation_model import EvidenceSourceKind, ObservationEnvelope, ObservationLayer, ObservationType
from midnight_performance.privacy import PrivacyGuard, PrivacyPolicy
from midnight_performance.prompt_capture import record_prompt_run
from midnight_performance import projection_store as ps

PROJECT_KEY = "bench-project"
PROJECT = deterministic_identity(EntityKind.PROJECT, PROJECT_KEY)
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
SIZES = (1_000, 10_000, 100_000)


def seed_direct(ledger_path: Path, n: int) -> None:
    guard = PrivacyGuard(PrivacyPolicy())
    lines = []
    for i in range(n):
        stable_key = f"provider:evt-{i}"
        observation = Observation(
            identity=deterministic_identity(EntityKind.PROMPT_RUN, stable_key),
            claim_kind=ClaimKind.OBSERVED,
            subject=deterministic_identity(EntityKind.PROMPT_VERSION, stable_key),
            payload={}, observed_at=BASE + timedelta(seconds=i), source="provider",
        )
        envelope = ObservationEnvelope(
            observation=observation, project=PROJECT, observation_type=ObservationType.PROMPT,
            layer=ObservationLayer.NORMALIZED, provider="provider", provider_event_id=f"evt-{i}",
            source_kind=EvidenceSourceKind.PROVIDER_HOOK, attributes={"occurrence_only": True},
        )
        protected = replace(envelope, observation=guard.protect(envelope.observation))
        lines.append(json.dumps(protected.to_dict(), sort_keys=True, default=str))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def time_it(fn, repeats=5) -> list[float]:
    return [_time_once(fn) for _ in range(repeats)]


def _time_once(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def med(samples: list[float]) -> float:
    return statistics.median(samples) * 1000


def p95(samples: list[float]) -> float:
    s = sorted(samples)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return s[idx] * 1000


def main() -> None:
    print(f"SQLite version: {sqlite3.sqlite_version}\n")
    print(f"{'N':>8} | {'file(MB)':>9} | {'append(ms)':>11} | {'replay(ms)':>11} | {'query BEFORE(ms)':>17} | {'query AFTER median(ms)':>23} | {'query AFTER p95(ms)':>20}")

    for n in SIZES:
        tmp = Path(tempfile.mkdtemp())
        ledger_path = tmp / "evidence.jsonl"
        seed_direct(ledger_path, n)
        file_mb = ledger_path.stat().st_size / (1024 * 1024)

        append_samples = []
        for r in range(3):
            append_samples.append(_time_once(
                lambda r=r: record_prompt_run(ledger_path, PROJECT_KEY, "provider", f"newevt-{r}", observed_at=BASE + timedelta(hours=1))
            ))

        ledger = EvidenceLedger(ledger_path, PROJECT, PrivacyGuard(PrivacyPolicy()))
        replay_samples = time_it(lambda: list(ledger.replay()), repeats=3)

        # BEFORE: what a raw replay+sort query cost (the pre-Execution-05 path).
        def before_query():
            list(sorted((e for e in ledger.replay() if e.observation.identity.kind is EntityKind.PROMPT_RUN),
                        key=lambda e: (e.observation.observed_at, e.observation.identity.canonical)))[:100]
        before_samples = time_it(before_query, repeats=3)

        # AFTER: the real, current prompt_run_activity() — projection-backed.
        ps.build(ledger, ps.projection_path(tmp))  # warm build, mirrors steady state
        after_samples = time_it(lambda: prompt_run_activity(ledger_path, PROJECT_KEY, limit=100), repeats=5)

        print(
            f"{n:>8} | {file_mb:>9.2f} | {med(append_samples):>11.2f} | {med(replay_samples):>11.2f} | "
            f"{med(before_samples):>17.2f} | {med(after_samples):>23.2f} | {p95(after_samples):>20.2f}"
        )
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
