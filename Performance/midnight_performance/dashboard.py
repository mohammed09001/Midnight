"""Metric/cohort dashboard projections with reference-only sibling navigation."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ExternalReference
@dataclass(frozen=True, slots=True)
class DashboardMetric:
    name:str; value:float|None; cohort:str="all"
@dataclass(frozen=True, slots=True)
class Dashboard:
    title:str; metrics:tuple[DashboardMetric,...]; navigation:tuple[ExternalReference,...]
    def __post_init__(self):
        if not self.title.strip(): raise ValueError("dashboard title required")
        if any(x.value is not None and not 0<=x.value<=1 for x in self.metrics): raise ValueError("metric values must be zero-one")
