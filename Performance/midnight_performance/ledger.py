"""Append-only JSONL ledger for policy-protected canonical observations.

Cross-process safety (Execution 04, Section F): the check-then-append
critical section in :meth:`EvidenceLedger.append` is guarded by a
cross-platform advisory file lock (``msvcrt.locking`` on Windows,
``fcntl.flock`` on POSIX) on a sibling ``<name>.lock`` file, in addition to
the in-process ``threading.Lock``. Claude Code's own hooks documentation
confirms multiple hook processes for the same event running concurrently is
normal, expected behavior — a single in-process lock cannot protect against
that, since each hook invocation is a separate OS process. The file lock
closes that gap for the property that matters most: two processes can never
both observe "not a duplicate" and both append, so no silent duplicate
canonical identity can occur under concurrent writers (see
``tests/test_ledger_concurrency.py``).

This is an advisory lock, not a durability guarantee. A process hard-killed
mid-write can still leave a torn/incomplete line on disk. ``replay`` already
fails closed (raises ``ValueError``) on any malformed line rather than
silently accepting or silently truncating history, so the honest, provable
property is "no silent duplicate, no silently-accepted corruption" — never
"corruption can't happen." True atomic-write durability (e.g. a
temp-file-then-rename per record) is a bigger format change, deliberately
deferred to a future execution.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator

from .contracts import EntityKind, Identity
from .observation_model import ObservationEnvelope, ObservationLayer
from .privacy import PrivacyGuard

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


_LOCK_POLL_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 30.0

# Test-only seam (Execution 04, Section F): when set, `append` splits its
# write into two flushed-and-fsynced halves with a sleep between them, so a
# test can deterministically kill the process mid-write and observe a real
# torn line on disk, rather than relying on nondeterministic OS timing. A
# no-op whenever unset — zero behavior change in production.
_TEST_WRITE_DELAY_ENV = "MIDNIGHT_TEST_WRITE_DELAY_MS"


@contextmanager
def _cross_process_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"could not acquire ledger append lock within {_LOCK_TIMEOUT_SECONDS}s")
                time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class EvidenceLedger:
    """Project-isolated, durable raw/normalized evidence with restart-safe replay."""

    def __init__(self, path: Path, project: Identity, guard: PrivacyGuard) -> None:
        if project.kind is not EntityKind.PROJECT:
            raise ValueError("ledger project must have project identity")
        self.path = path
        self.project = project
        self.guard = guard
        self._lock = threading.Lock()

    @property
    def _lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    def append(self, envelope: ObservationEnvelope) -> bool:
        """Policy-filter then flush a record once per deterministic identity."""
        if envelope.project != self.project:
            raise PermissionError("cross-project evidence write rejected")
        if envelope.layer is ObservationLayer.DERIVED:
            raise ValueError("derived analysis belongs in a rebuildable projection, not the raw ledger")
        protected = replace(envelope, observation=self.guard.protect(envelope.observation))
        # The durable record is the privacy-filtered representation.  Preserve a
        # supplied provenance signer, but recompute its checksum over that exact
        # representation so replay can detect subsequent JSONL tampering.
        if protected.integrity_checksum is not None:
            from .provenance import seal

            protected = seal(protected, signer=protected.signer)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The in-process lock protects concurrent threads within this one
        # interpreter; the file lock (below) protects concurrent *processes*
        # (e.g. two hook invocations for the same event) — both are needed.
        with self._lock, _cross_process_lock(self._lock_path):
            existing = {item.observation.identity.canonical for item in self.replay()}
            if protected.observation.identity.canonical in existing:
                return False
            line = json.dumps(protected.to_dict(), sort_keys=True, default=str) + "\n"
            delay_ms = os.environ.get(_TEST_WRITE_DELAY_ENV)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                if delay_ms:
                    split = len(line) // 2
                    handle.write(line[:split])
                    handle.flush()
                    os.fsync(handle.fileno())
                    time.sleep(int(delay_ms) / 1000)
                    handle.write(line[split:])
                else:
                    handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return True

    def read_new_bytes(self, since_offset: int) -> tuple[bytes, int]:
        """Locked, raw read of ledger bytes from ``since_offset`` to the
        current end of file — for a rebuildable read projection's
        incremental catch-up (Execution 05). Does not parse or validate;
        the caller owns interpreting the returned bytes.

        Reuses the same cross-process lock ``append`` takes, because a
        plain read from a separate process does not otherwise respect
        another process's advisory lock: without this, a concurrent
        incremental read could observe a torn tail while a writer is
        mid-append. Binary mode is deliberate — byte offsets must be exact,
        and text-mode newline translation would shift them.
        """
        with _cross_process_lock(self._lock_path):
            if not self.path.exists():
                return b"", 0
            with self.path.open("rb") as handle:
                handle.seek(since_offset)
                new_bytes = handle.read()
                new_eof_offset = handle.tell()
        return new_bytes, new_eof_offset

    def replay(self) -> Iterator[ObservationEnvelope]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    envelope = ObservationEnvelope.from_dict(json.loads(line))
                    if envelope.project != self.project:
                        raise PermissionError("cross-project evidence found in ledger")
                    yield envelope
                except (KeyError, TypeError, ValueError, PermissionError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid evidence at line {line_number}") from exc
