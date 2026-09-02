"""Versioned, reproducible analysis and reprocessing contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Iterable, Mapping

from .contracts import ExternalReference
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
    # Task 15 (Execution 05): by-reference citations of specific Memory
    # record revisions this analysis consulted, never a copy of Memory
    # content and never Memory canonical ownership. Deliberately NOT part
    # of input_fingerprint's hash — reproducibility of the analysis itself
    # stays governed solely by Performance's own ledger evidence; citations
    # are provenance metadata about what else was consulted, not an input.
    memory_references: tuple[ExternalReference, ...] = ()


class Reprocessor:
    """Runs pure analysis against replayed evidence without mutating the ledger."""

    def run(
        self,
        descriptor: AnalysisDescriptor,
        evidence: Iterable[ObservationEnvelope],
        analyzer: Callable[[tuple[ObservationEnvelope, ...]], Mapping[str, object]],
        *,
        memory_references: tuple[ExternalReference, ...] = (),
    ) -> AnalysisResult:
        inputs = tuple(evidence)
        fingerprint = self._inputs_fingerprint(inputs)
        return AnalysisResult(descriptor, fingerprint, dict(analyzer(inputs)), memory_references)

    @staticmethod
    def _inputs_fingerprint(inputs: tuple[ObservationEnvelope, ...]) -> str:
        canonical = "\n".join(json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":"), default=str) for item in inputs)
        return hashlib.sha256(canonical.encode()).hexdigest()
