"""Controlled comparison of variants over a frozen dataset snapshot; design is declared, never inferred."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping
from .bootstrap import DEFAULT_RESAMPLES, DEFAULT_SEED
from .confounders import DEFAULT_MIN_STRATUM, StratifiedComparison, compare_stratified
from .contracts import ClaimKind
from .dataset import DatasetRow
from .dataset_versioning import DatasetSnapshot
from .stats_tests import ComparisonResult, compare_samples

_METHOD = "experiment-analysis"
_VERSION = "1"


class ExperimentDesign(str, Enum):
    RANDOMIZED = "randomized"
    OBSERVATIONAL = "observational"


@dataclass(frozen=True, slots=True)
class ExperimentArm:
    name: str; description: str
    def __post_init__(self):
        if not self.name.strip(): raise ValueError("arm name is required")
        if not self.description.strip(): raise ValueError("arm description is required")


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    """A pinned comparison of exactly two arms (prompt variant, agent/model, verification instruction, or workflow change) over one frozen dataset snapshot."""
    name: str; version: str; design: ExperimentDesign; dataset_fingerprint: str; outcome_feature: str; assignment_method: str; arms: tuple[ExperimentArm, ExperimentArm]; randomization_unit: str | None = None

    def __post_init__(self):
        if not self.name.strip() or not self.version.strip(): raise ValueError("experiment requires name and version")
        if not self.dataset_fingerprint.strip(): raise ValueError("experiment must pin the fingerprint of a frozen dataset snapshot")
        if not self.outcome_feature.strip(): raise ValueError("experiment requires an outcome feature")
        if not self.assignment_method.strip(): raise ValueError("experiment requires a documented arm-assignment method")
        if len(self.arms) != 2 or self.arms[0].name == self.arms[1].name:
            raise ValueError("experiment requires exactly two distinctly named arms")
        if self.design is ExperimentDesign.RANDOMIZED and not (self.randomization_unit and self.randomization_unit.strip()):
            raise ValueError("randomized experiments must document the randomization unit")
        if self.design is ExperimentDesign.OBSERVATIONAL and self.randomization_unit is not None:
            raise ValueError("observational comparisons must not claim a randomization unit")


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    name: str; version: str; design: ExperimentDesign; dataset_fingerprint: str; outcome_feature: str
    arm_a: str; arm_b: str; excluded: tuple[str, ...]
    comparison: ComparisonResult; stratified: StratifiedComparison | None; confounders_checked: tuple[str, ...]
    causal_interpretable: bool; method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str

    def __post_init__(self):
        if (self.stratified is None) != (not self.confounders_checked):
            raise ValueError("a stratified adjustment and its confounder list are reported together or not at all")
        if self.causal_interpretable and self.design is ExperimentDesign.OBSERVATIONAL:
            raise ValueError("observational comparisons are never causally interpretable")


def run_experiment(
    definition: ExperimentDefinition,
    snapshot: DatasetSnapshot,
    assignment: Callable[[DatasetRow], str | None],
    *,
    confounders: Mapping[str, Callable[[DatasetRow], str | None]] | None = None,
    alpha: float = .05,
    min_size: int = 5,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    min_stratum: int = DEFAULT_MIN_STRATUM,
) -> ExperimentResult:
    """Compare the two declared arms on the declared outcome; the dataset snapshot must be the exact one the experiment was pinned against.

    Randomized and observational comparisons run the same arithmetic; only a documented, verified
    randomization mechanism ever earns `causal_interpretable`, and even then only when the comparison
    has enough data to be reported at all. Observational comparisons stay associative, with or without
    a stratified confounder adjustment.
    """
    if snapshot.fingerprint != definition.dataset_fingerprint:
        raise ValueError("experiment must run against the exact frozen dataset snapshot it was defined against")
    confounders = confounders or {}
    arm_a, arm_b = definition.arms[0].name, definition.arms[1].name
    values_a: list[float] = []
    values_b: list[float] = []
    excluded: list[str] = []
    for row in snapshot.rows:
        arm = assignment(row)
        if arm is None:
            excluded.append(f"{row.prompt_run_id}:no_arm_assignment")
            continue
        if arm not in (arm_a, arm_b):
            excluded.append(f"{row.prompt_run_id}:unrecognized_arm:{arm}")
            continue
        value = row.features.get(definition.outcome_feature)
        if value is None:
            excluded.append(f"{row.prompt_run_id}:missing_{definition.outcome_feature}")
            continue
        (values_a if arm == arm_a else values_b).append(value)
    comparison = compare_samples(tuple(values_a), tuple(values_b), feature=definition.outcome_feature, alpha=alpha, min_size=min_size)
    stratified: StratifiedComparison | None = None
    confounders_checked: tuple[str, ...] = ()
    if confounders:
        def treatment(row: DatasetRow) -> str | None:
            candidate = assignment(row)
            return candidate if candidate in (arm_a, arm_b) else None
        stratified = compare_stratified(snapshot.rows, treatment, definition.outcome_feature, confounders, resamples=resamples, seed=seed, min_stratum=min_stratum)
        confounders_checked = tuple(sorted(confounders))
    causal_interpretable = definition.design is ExperimentDesign.RANDOMIZED and comparison.sufficient
    parts: list[str] = []
    if definition.design is ExperimentDesign.RANDOMIZED:
        parts.append(f"randomized on {definition.randomization_unit}; interpretable as causal only to the extent the stated randomization mechanism held and excluded rows do not differ systematically between arms")
    else:
        parts.append("observational comparison; arm differences are associative only, never causal, even where a stratified adjustment is reported")
    if excluded:
        parts.append(f"{len(excluded)} rows excluded for missing arm assignment, an unrecognized arm, or a missing outcome value")
    if not comparison.sufficient:
        parts.append(f"samples below {min_size} are not compared; sample size controls the conclusion")
    if stratified is not None and stratified.naive_agrees is False:
        parts.append("naive comparison direction reverses after stratified adjustment; prefer the adjusted result")
    return ExperimentResult(
        definition.name, definition.version, definition.design, definition.dataset_fingerprint, definition.outcome_feature,
        arm_a, arm_b, tuple(excluded), comparison, stratified, confounders_checked, causal_interpretable,
        _METHOD, _VERSION, ClaimKind.STATISTICAL, "; ".join(parts),
    )
