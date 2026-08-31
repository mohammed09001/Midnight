"""Versioned, reproducible analysis and reprocessing contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Iterable, Mapping

from .observation_model import ObservationEnvelope


@dataclass(frozen=True, slots=True)
class AnalysisDescriptor:
    name: str
    version: str
    kind: str
    configuration: Mapping[str, object]

    def __post_init__(self) -> None:
        if not all((self.name.strip(), self.version.strip(), self.kind.strip())):
            raise ValueError("analysis name, version, and kind are required")

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps({"name": self.name, "version": self.version, "kind": self.kind, "configuration": self.configuration}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    descriptor: AnalysisDescriptor
    input_fingerprint: str
    output: Mapping[str, object]


class Reprocessor:
    """Runs pure analysis against replayed evidence without mutating the ledger."""

    def run(self, descriptor: AnalysisDescriptor, evidence: Iterable[ObservationEnvelope], analyzer: Callable[[tuple[ObservationEnvelope, ...]], Mapping[str, object]]) -> AnalysisResult:
        inputs = tuple(evidence)
        fingerprint = self._inputs_fingerprint(inputs)
        return AnalysisResult(descriptor, fingerprint, dict(analyzer(inputs)))

    @staticmethod
    def _inputs_fingerprint(inputs: tuple[ObservationEnvelope, ...]) -> str:
        canonical = "\n".join(json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":"), default=str) for item in inputs)
        return hashlib.sha256(canonical.encode()).hexdigest()
