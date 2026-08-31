"""Bounded, isolated best-effort work for rebuildable Performance projections.

Raw evidence is intentionally absent from this API.  A failed ML, AI,
similarity, dashboard, or recommendation job can only degrade its own derived
component and cannot corrupt the ledger.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .telemetry import PerformanceMetric, PerformanceTelemetry


class DerivedComponent(str, Enum):
    ML = "ml"
    AI_EVALUATION = "ai_evaluation"
    SIMILARITY = "similarity"
    DASHBOARD = "dashboard"
    RECOMMENDATION = "recommendation"


@dataclass(frozen=True, slots=True)
class RetryBudget:
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("retry budget requires at least one attempt")


@dataclass(frozen=True, slots=True)
class WorkFailure:
    component: DerivedComponent
    task_id: str
    attempts: int
    error_type: str


@dataclass(slots=True)
class _WorkItem:
    component: DerivedComponent
    task_id: str
    operation: Callable[[], object]
    attempts: int = 0


class DerivedWorkQueue:
    """Synchronous worker boundary with bounded admission and per-component degradation."""

    def __init__(self, capacity: int, retry_budget: RetryBudget = RetryBudget(), telemetry: PerformanceTelemetry | None = None) -> None:
        if capacity < 1:
            raise ValueError("queue capacity must be positive")
        self.capacity, self.retry_budget = capacity, retry_budget
        self._items: deque[_WorkItem] = deque()
        self.telemetry = telemetry
        self._failures: list[WorkFailure] = []
        self._degraded: set[DerivedComponent] = set()

    @property
    def pending(self) -> int:
        return len(self._items)

    @property
    def failures(self) -> tuple[WorkFailure, ...]:
        return tuple(self._failures)

    @property
    def degraded_components(self) -> frozenset[DerivedComponent]:
        return frozenset(self._degraded)

    def submit(self, component: DerivedComponent, task_id: str, operation: Callable[[], object]) -> bool:
        if not task_id.strip():
            raise ValueError("work task id is required")
        if self.pending >= self.capacity:
            if self.telemetry is not None:
                self.telemetry.record(PerformanceMetric.FAILURE, 1, subject="derived_queue", succeeded=False)
            return False
        self._items.append(_WorkItem(component, task_id, operation))
        if self.telemetry is not None:
            self.telemetry.record(PerformanceMetric.QUEUE_DEPTH, self.pending, subject="derived_queue")
        return True

    def run_one(self) -> object | None:
        if not self._items:
            return None
        item = self._items.popleft()
        item.attempts += 1
        try:
            return item.operation()
        except Exception as exc:
            if item.attempts < self.retry_budget.max_attempts:
                self._items.append(item)
            else:
                self._degraded.add(item.component)
                self._failures.append(WorkFailure(item.component, item.task_id, item.attempts, type(exc).__name__))
                if self.telemetry is not None:
                    self.telemetry.record(PerformanceMetric.FAILURE, 1, subject=item.component.value, succeeded=False)
            return None
