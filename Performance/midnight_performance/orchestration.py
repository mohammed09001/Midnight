"""Typed Performance capabilities for a separate Intelligence orchestration layer.

This facade coordinates neither coding agents nor sibling products.  It binds
authorized requests to Performance's query facade and ledger only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping

from .contracts import EntityKind
from .ledger import EvidenceLedger
from .observation_model import ObservationEnvelope, ObservationLayer
from .query_api import PerformanceQueryAPI, QueryAuthorization, QueryProjection


ORCHESTRATION_CAPABILITY_VERSION = 1


class PerformanceCapability(str, Enum):
    HISTORY_QUERY = "history.query"
    PROMPT_RETRIEVE = "prompt.retrieve"
    EXECUTION_RETRIEVE = "execution.retrieve"
    CHANGE_RETRIEVE = "change.retrieve"
    EPISODE_RETRIEVE = "episode.retrieve"
    SIMILARITY_SEARCH = "similarity.search"
    MEMORY_QUERY = "memory.query"
    PROMPT_GENERATE = "prompt.generate"
    VERIFICATION_HISTORY = "verification.history"
    OUTCOME_RECORD = "outcome.record"


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    name: PerformanceCapability
    version: int = ORCHESTRATION_CAPABILITY_VERSION
    user_invoked: bool = False
    mutates_evidence: bool = False

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("capability version must be positive")


@dataclass(frozen=True, slots=True)
class OrchestrationAuthorization:
    query: QueryAuthorization
    may_generate_prompts: bool = False
    may_record_outcomes: bool = False


class PerformanceCapabilityPlane:
    """A server-bound orchestration facade with explicit capability ownership."""

    def __init__(self, query_api: PerformanceQueryAPI, ledger: EvidenceLedger, authorization: OrchestrationAuthorization, *, prompt_generator: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None) -> None:
        if query_api.project != ledger.project or authorization.query.project != ledger.project:
            raise PermissionError("capability plane requires one authorized Performance project")
        self._api, self._ledger, self._authorization = query_api, ledger, authorization
        self._prompt_generator = prompt_generator

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(CapabilityDescriptor(item, user_invoked=item is PerformanceCapability.PROMPT_GENERATE, mutates_evidence=item is PerformanceCapability.OUTCOME_RECORD) for item in PerformanceCapability)

    def invoke(self, capability: PerformanceCapability, arguments: Mapping[str, object]) -> object:
        if capability is PerformanceCapability.HISTORY_QUERY:
            return self._api.query_evidence(self._authorization.query, limit=int(arguments.get("limit", 50)))
        if capability is PerformanceCapability.PROMPT_RETRIEVE:
            return self._api.query_evidence(self._authorization.query, kinds=frozenset({EntityKind.PROMPT, EntityKind.PROMPT_VERSION, EntityKind.PROMPT_RUN}), limit=int(arguments.get("limit", 50)))
        if capability is PerformanceCapability.EXECUTION_RETRIEVE:
            return self._api.query_evidence(self._authorization.query, kinds=frozenset({EntityKind.AGENT_RUN, EntityKind.AGENT_SESSION, EntityKind.AGENT_TURN}), limit=int(arguments.get("limit", 50)))
        if capability is PerformanceCapability.CHANGE_RETRIEVE:
            return self._api.query_evidence(self._authorization.query, kinds=frozenset({EntityKind.CHANGE_SET, EntityKind.FILE_CHANGE}), limit=int(arguments.get("limit", 50)))
        if capability is PerformanceCapability.EPISODE_RETRIEVE:
            return self._api.episodes(self._authorization.query, limit=int(arguments.get("limit", 50)))
        if capability is PerformanceCapability.VERIFICATION_HISTORY:
            return self._api.query_evidence(self._authorization.query, kinds=frozenset({EntityKind.VERIFICATION_RUN}), limit=int(arguments.get("limit", 50)))
        if capability is PerformanceCapability.SIMILARITY_SEARCH:
            return self._projection("similarity")
        if capability is PerformanceCapability.MEMORY_QUERY:
            return self._projection("memory")
        if capability is PerformanceCapability.PROMPT_GENERATE:
            if not self._authorization.may_generate_prompts or self._prompt_generator is None:
                raise PermissionError("prompt generation is unavailable without explicit authorization and a host generator")
            return self._prompt_generator(arguments)
        if capability is PerformanceCapability.OUTCOME_RECORD:
            if not self._authorization.may_record_outcomes:
                raise PermissionError("outcome recording requires explicit authorization")
            if EntityKind.OUTCOME_OBSERVATION not in self._authorization.query.allowed_kinds:
                raise PermissionError("outcome recording is not authorized for this capability scope")
            envelope = arguments.get("envelope")
            if not isinstance(envelope, ObservationEnvelope) or envelope.project != self._ledger.project:
                raise ValueError("outcome.record requires a same-project ObservationEnvelope")
            if envelope.observation.identity.kind is not EntityKind.OUTCOME_OBSERVATION or envelope.layer is ObservationLayer.DERIVED:
                raise ValueError("outcome.record accepts only raw or normalized outcome observations")
            return self._ledger.append(envelope)
        raise ValueError(f"unsupported Performance capability: {capability.value}")

    def _projection(self, name: str) -> QueryProjection:
        return self._api.projection(self._authorization.query, name)
