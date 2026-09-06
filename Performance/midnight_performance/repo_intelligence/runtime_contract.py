"""Machine-readable ownership and execution contract for Repo Intelligent runtime.

Execution 02/01 consolidates production orchestration without pretending every
existing library module is already a production owner. The inventory below is
deliberately explicit about canonical, library-only and deferred paths.
Runtime stage outcomes are content-free diagnostics: they carry reason codes
and counts, never prompt/source text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

RUNTIME_CONTRACT_VERSION = 1


class RuntimeStage(str, Enum):
    OBSERVE = "observe"
    DETECT_SIGNAL = "detect_signal"
    COMPUTE_LEARNING_PRESSURE = "compute_learning_pressure"
    CHECK_INTERNAL_SUFFICIENCY = "check_internal_sufficiency"
    PLAN_RETRIEVAL = "plan_retrieval"
    ROUTE_CHEAPEST_QUALIFIED_RESOLVER = "route_cheapest_qualified_resolver"
    OPTIONAL_EXTERNAL_DISCOVERY = "optional_external_discovery"
    VERIFY_EVIDENCE = "verify_evidence"
    SYNTHESIZE = "synthesize"
    GRAPH_FUSION = "graph_fusion"
    ATTENTION_RANK = "attention_rank"
    EXPOSE = "expose"
    RECORD_OUTCOME = "record_outcome"
    LEARN = "learn"


class StageOwnershipStatus(str, Enum):
    CANONICAL = "CANONICAL"
    LIBRARY_ONLY = "LIBRARY_ONLY"
    DUPLICATE = "DUPLICATE"
    DEFERRED = "DEFERRED"
    BROKEN = "BROKEN"


class StageExecutionStatus(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    SKIPPED = "skipped"
    FAILED = "failed"


class StageReasonCode(str, Enum):
    POLICY_DENIAL = "policy_denial"
    PRIVACY_DENIED = "privacy_denied"
    AUTHORIZATION_DENIED = "authorization_denied"
    INTERNAL_SUFFICIENT = "internal_sufficient"
    ABSENCE = "absence"
    INSUFFICIENCY = "insufficiency"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    BUDGET_STOP = "budget_stop"
    STALE_STATE = "stale_state"
    INTERNAL_ERROR = "internal_error"
    NOT_APPLICABLE = "not_applicable"
    DEFERRED = "deferred"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    HARD_LIMIT = "hard_limit"


@dataclass(frozen=True, slots=True)
class StageInventoryEntry:
    stage: RuntimeStage
    owner: str
    production_caller: str
    persistence: str
    telemetry: str
    tests: str
    alternate_path: str | None
    status: StageOwnershipStatus
    note: str = ""
    contract_version: int = RUNTIME_CONTRACT_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "stage": self.stage.value,
            "owner": self.owner,
            "production_caller": self.production_caller,
            "persistence": self.persistence,
            "telemetry": self.telemetry,
            "tests": self.tests,
            "alternate_path": self.alternate_path,
            "status": self.status.value,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class StageOutcome:
    stage: RuntimeStage
    status: StageExecutionStatus
    owner: str
    reason_code: StageReasonCode | None = None
    detail: str = ""
    contract_version: int = RUNTIME_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.status is StageExecutionStatus.COMPLETED and self.reason_code is not None:
            raise ValueError("completed runtime stages must not carry a failure/degradation/skip reason")
        if self.status is not StageExecutionStatus.COMPLETED and self.reason_code is None:
            raise ValueError("degraded/skipped/failed runtime stages require an explicit reason code")
        if not self.owner.strip():
            raise ValueError("runtime stage outcomes require an owner")

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "stage": self.stage.value,
            "status": self.status.value,
            "owner": self.owner,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class PerformanceEvidenceCoverage:
    """What portion of matching Performance evidence the runtime actually read."""

    total_matching: int
    retrieved: int
    start_offset: int
    hard_limit: int
    complete: bool
    reason: str
    contract_version: int = RUNTIME_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if min(self.total_matching, self.retrieved, self.start_offset, self.hard_limit) < 0:
            raise ValueError("Performance evidence coverage counts cannot be negative")
        if self.retrieved > self.hard_limit:
            raise ValueError("retrieved evidence cannot exceed the declared hard limit")
        if not self.reason.strip():
            raise ValueError("Performance evidence coverage requires a reason")

    @property
    def truncated(self) -> bool:
        return not self.complete and self.total_matching > self.retrieved

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "total_matching": self.total_matching,
            "retrieved": self.retrieved,
            "start_offset": self.start_offset,
            "hard_limit": self.hard_limit,
            "complete": self.complete,
            "truncated": self.truncated,
            "reason": self.reason,
        }


# One production owner per user-visible concern. Alternate engines remain
# reusable libraries until a later Execution deliberately migrates ownership.
CANONICAL_STAGE_INVENTORY: tuple[StageInventoryEntry, ...] = (
    StageInventoryEntry(RuntimeStage.OBSERVE, "repo_intelligence_pipeline._read_performance_evidence", "repo_intelligence_pipeline.run_pipeline", "Performance ledger remains canonical; coverage only in run result", "StageOutcome + PerformanceEvidenceCoverage", "runtime consolidation + query API tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.DETECT_SIGNAL, "repo_intelligence.signals.scan_signals", "repo_intelligence_pipeline.run_pipeline", "RepoIntelligenceStore derived signal cache", "StageOutcome + CostRecord", "signal + pipeline tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.COMPUTE_LEARNING_PRESSURE, "repo_intelligence.signals.score_path_pressure", "repo_intelligence.signals.scan_signals", "inside derived InternalSignal/LineageReceipt", "inspectable pressure factors", "signal tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.CHECK_INTERNAL_SUFFICIENCY, "repo_intelligence_pipeline._memory_answer_status", "repo_intelligence_pipeline.run_pipeline", "latest coarse status in pipeline_runs", "StageOutcome", "pipeline tests", "Repo Intelligent 02 Execution 02 replaces coarse project-level sufficiency with per-question qualification", StageOwnershipStatus.CANONICAL, "Ownership is canonical; semantic sufficiency remains intentionally limited and is not claimed complete."),
    StageInventoryEntry(RuntimeStage.PLAN_RETRIEVAL, "repo_intelligence.federated_retrieval.plan_retrieval", "repo_intelligence_pipeline.run_pipeline", "not durable; deterministic plan", "StageOutcome", "federated retrieval + runtime tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.ROUTE_CHEAPEST_QUALIFIED_RESOLVER, "repo_intelligence_pipeline deterministic/local routing gate", "repo_intelligence_pipeline.run_pipeline", "job/cost records", "StageOutcome", "runtime tests", "Repo Intelligent 02 Execution 05 made repo_intelligence.cost_quality.route a feature-complete, fully-tested adaptive router (LIGHTWEIGHT_ML tier, quality floors, counterfactual tracking, promotion gate) still awaiting a production PricedExecutor/model provider before any pipeline stage delegates to it", StageOwnershipStatus.CANONICAL, "Current production routing is deterministic/local-first. The adaptive router is real and verified but not yet the pipeline's decision owner: no concrete model provider exists to route to, and this stage's only graded decision (fetch relevance) was already Execution 04's demonstration target."),
    StageInventoryEntry(RuntimeStage.OPTIONAL_EXTERNAL_DISCOVERY, "repo_intelligence.discovery.discover", "repo_intelligence_pipeline.run_pipeline", "CostRecord; source pointers stay evidence references", "StageOutcome + DiscoveryRun", "discovery + pipeline tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.VERIFY_EVIDENCE, "repo_intelligence_pipeline._augment_with_external_evidence", "repo_intelligence_pipeline.run_pipeline", "EvidenceBundle/ExternalSourceRef-derived state", "StageOutcome", "pipeline adversarial tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.SYNTHESIZE, "repo_intelligence.synthesis.synthesize", "repo_intelligence_pipeline.run_pipeline", "RepoIntelligenceStore ProjectInsight cache", "StageOutcome", "synthesis + pipeline tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.GRAPH_FUSION, "repo_intelligence.project_graph.build_project_graph", "repo_intelligence_pipeline.run_pipeline", "rebuildable graph projection", "StageOutcome", "project graph + runtime tests", "repo_intelligence_fusion is a read/query helper, not a competing graph decision owner", StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.ATTENTION_RANK, "repo_intelligence.terminal_learning.decide_terminal_card", "repo_intelligence_pipeline.run_pipeline", "Canonical attention score plus rolling exposure budget", "StageOutcome", "terminal + runtime tests", "repo_intelligence.attention is the canonical formula (module remains reusable; no competing library-only owner)", StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.EXPOSE, "repo_intelligence_pipeline + RepoIntelligenceStore.append_exposure", "repo_intelligence_pipeline.run_pipeline", "durable Repo Intelligent exposure history", "StageOutcome", "bridge + runtime tests", None, StageOwnershipStatus.CANONICAL),
    StageInventoryEntry(RuntimeStage.RECORD_OUTCOME, "repo_intelligence_pipeline.record_feedback / associate_learning_outcome", "explicit feedback/outcome entry points", "durable exposure feedback + learning outcomes", "explicit event records", "bridge + pipeline tests", None, StageOwnershipStatus.CANONICAL, "Not executed speculatively during a pipeline pass; only real later events are recorded."),
    StageInventoryEntry(RuntimeStage.LEARN, "repo_intelligence.learning_loop.ContinuousLearningLoop", "no production background caller", "returned checkpoints are not durably scheduled by production", "library audit trail only", "learning-loop unit tests", None, StageOwnershipStatus.DEFERRED, "Continuous background execution is formally deferred. Production remains explicit bounded user-pull/bridge execution."),
)


def stage_inventory() -> tuple[dict[str, object], ...]:
    return tuple(entry.to_dict() for entry in CANONICAL_STAGE_INVENTORY)


__all__ = [
    "CANONICAL_STAGE_INVENTORY",
    "PerformanceEvidenceCoverage",
    "RUNTIME_CONTRACT_VERSION",
    "RuntimeStage",
    "StageExecutionStatus",
    "StageInventoryEntry",
    "StageOutcome",
    "StageOwnershipStatus",
    "StageReasonCode",
    "stage_inventory",
]
