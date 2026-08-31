"""Reproducible experiment manifests and metric/cohort regression comparisons."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
@dataclass(frozen=True, slots=True)
class ReproducibilityManifest:
    dataset_version: str; prompt_version: str; agent_model_version: str; parameters: tuple[tuple[str,str], ...]; repository_fixture: str; evaluator_versions: tuple[str,...]; code_fixture: str; watch_fixture: str; environment: str; seed: int | None
    def __post_init__(self):
        if not all((self.dataset_version.strip(), self.prompt_version.strip(), self.agent_model_version.strip(), self.repository_fixture.strip(), self.code_fixture.strip(), self.watch_fixture.strip(), self.environment.strip())): raise ValueError("reproducibility manifest is incomplete")
@dataclass(frozen=True, slots=True)
class RegressionMetric:
    name: str; baseline: float; current: float; cohort: str = "all"
    @property
    def delta(self): return round(self.current-self.baseline,3)
@dataclass(frozen=True, slots=True)
class RegressionReport:
    manifest: ReproducibilityManifest; metrics: tuple[RegressionMetric,...]; regressions: tuple[RegressionMetric,...]; claim_kind: ClaimKind=ClaimKind.DERIVED
def evaluate_regression(manifest: ReproducibilityManifest, metrics: tuple[RegressionMetric,...], *, lower_is_better: tuple[str,...]=()) -> RegressionReport:
    bad=tuple(x for x in metrics if (x.delta > 0 if x.name in lower_is_better else x.delta < 0))
    return RegressionReport(manifest, metrics, bad)
