"""Append-only JSONL ledger for policy-protected canonical observations."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import threading
from typing import Iterator

from .contracts import EntityKind, Identity
from .observation_model import ObservationEnvelope, ObservationLayer
from .privacy import PrivacyGuard


class EvidenceLedger:
    """Project-isolated, durable raw/normalized evidence with restart-safe replay."""

    def __init__(self, path: Path, project: Identity, guard: PrivacyGuard) -> None:
        if project.kind is not EntityKind.PROJECT:
            raise ValueError("ledger project must have project identity")
        self.path = path
        self.project = project
        self.guard = guard
        self._lock = threading.Lock()

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
        with self._lock:
            existing = {item.observation.identity.canonical for item in self.replay()}
            if protected.observation.identity.canonical in existing:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(protected.to_dict(), sort_keys=True, default=str) + "\n"
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return True

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
