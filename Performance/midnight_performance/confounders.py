"""Confounder-aware comparative analysis: stratified, seeded, and never causal."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import Callable, Mapping, Sequence
from .bootstrap import DEFAULT_RESAMPLES, DEFAULT_SEED, BootstrapEstimate, bootstrap_difference, mean_difference, percentile_interval, resample_two_sample
from .contracts import ClaimKind
from .dataset import DatasetRow

_METHOD = "stratified-comparison"
_VERSION = "1"
DEFAULT_MIN_STRATUM = 3

@dataclass(frozen=True, slots=True)
class StratumComparison:
    key: str; group_a: str; group_b: str; n_a: int; n_b: int; effect: float | None; ci95: tuple[float, float] | None; sufficient: bool; uncertainty: str
    def __post_init__(self):
        if not self.key.strip(): raise ValueError("stratum key is required")
        if self.sufficient and self.effect is None: raise ValueError("sufficient strata carry effects")
        if not self.sufficient and self.effect is not None: raise ValueError("suppressed strata carry no effect")
        if (self.effect is None) is not (self.ci95 is None): raise ValueError("stratum effect and interval are reported together or not at all")

@dataclass(frozen=True, slots=True)
class StratifiedComparison:
    outcome: str; groups: tuple[str, str]; population: int; excluded: tuple[str, ...]; strata: tuple[StratumComparison, ...]; suppressed: tuple[str, ...]; naive: BootstrapEstimate; adjusted_effect: float | None; adjusted_ci95: tuple[float, float] | None; naive_agrees: bool | None; min_stratum: int; resamples: int; seed: int; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if not self.outcome.strip(): raise ValueError("outcome feature name is required")
        if len(self.groups) != 2 or any(not group.strip() for group in self.groups) or self.groups[0] == self.groups[1]: raise ValueError("comparisons require two distinct named groups")
        if self.population < 1: raise ValueError("stratified comparison requires at least one analyzable row")
        if self.min_stratum < 1: raise ValueError("minimum stratum size must be positive")
        if self.resamples < 1: raise ValueError("resamples must be positive")
        if (self.adjusted_effect is None) is not (self.adjusted_ci95 is None): raise ValueError("adjusted effect and interval are reported together or not at all")

def _sign(value: float) -> int:
    return (value > 0) - (value < 0)

def compare_stratified(rows, treatment: Callable[[DatasetRow], str | None], outcome: str, confounders: Mapping[str, Callable[[DatasetRow], str | None]], *, statistic: Callable[[Sequence[float], Sequence[float]], float] = mean_difference, name: str = "mean_difference", resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED, min_stratum: int = DEFAULT_MIN_STRATUM) -> StratifiedComparison:
    """Compare two treatment groups on an outcome within confounder strata; the naive contrast is reported only to be challenged.

    Confounders are caller-named (task difficulty, component, agent/model, repository size,
    change size, release context, user/project) and extract stratum values from each row.
    """
    if not outcome.strip(): raise ValueError("outcome feature name is required")
    if not confounders: raise ValueError("at least one confounder is required; an unstratified comparison is the naive contrast this module exists to challenge")
    if resamples < 1: raise ValueError("resamples must be positive")
    if min_stratum < 1: raise ValueError("minimum stratum size must be positive")
    confounder_names = sorted(confounders)
    analysis: list[tuple[str, float, str]] = []
    excluded: list[str] = []
    group_names: set[str] = set()
    for row in rows:
        group = treatment(row)
        if group is None:
            excluded.append(f"{row.prompt_run_id}:no_treatment_group")
            continue
        value = row.features.get(outcome)
        if value is None:
            excluded.append(f"{row.prompt_run_id}:missing_{outcome}")
            continue
        parts: list[str] | None = []
        for confounder_name in confounder_names:
            stratum_value = confounders[confounder_name](row)
            if stratum_value is None:
                parts = None
                break
            parts.append(f"{confounder_name}={stratum_value}")
        if parts is None:
            excluded.append(f"{row.prompt_run_id}:missing_confounder")
            continue
        group_names.add(group)
        analysis.append((group, float(value), "|".join(parts)))
    if len(group_names) != 2:
        raise ValueError("treatment must produce exactly two groups over analyzable rows")
    group_a, group_b = sorted(group_names)
    values_a = tuple(value for group, value, _ in analysis if group == group_a)
    values_b = tuple(value for group, value, _ in analysis if group == group_b)
    if not values_a or not values_b:
        raise ValueError("both treatment groups need at least one analyzable row")
    naive = bootstrap_difference(values_a, values_b, statistic, name=name, resamples=resamples, seed=seed, min_size=2)
    by_stratum: dict[str, list[tuple[str, float]]] = {}
    for group, value, stratum in analysis:
        by_stratum.setdefault(stratum, []).append((group, value))
    strata: list[StratumComparison] = []
    suppressed: list[str] = []
    sufficient: list[tuple[str, tuple[float, ...], tuple[float, ...], int]] = []
    for key in sorted(by_stratum):
        population = by_stratum[key]
        stratum_a = tuple(value for group, value in population if group == group_a)
        stratum_b = tuple(value for group, value in population if group == group_b)
        if len(stratum_a) < min_stratum or len(stratum_b) < min_stratum:
            suppressed.append(f"{key}:{len(stratum_a)}+{len(stratum_b)}")
            strata.append(StratumComparison(key, group_a, group_b, len(stratum_a), len(stratum_b), None, None, False, f"below {min_stratum} rows per group; excluded from the adjusted estimate"))
            continue
        effect = round(statistic(stratum_a, stratum_b), 3)
        interval = percentile_interval(resample_two_sample(stratum_a, stratum_b, statistic, resamples=resamples, seed=seed))
        strata.append(StratumComparison(key, group_a, group_b, len(stratum_a), len(stratum_b), effect, interval, True, "within-stratum contrast; confounders fixed inside the stratum"))
        sufficient.append((key, stratum_a, stratum_b, len(stratum_a) + len(stratum_b)))
    parts = ["controls only for the supplied confounders; residual confounding remains possible; comparison is associative, never causal"]
    if excluded:
        parts.append(f"{len(excluded)} rows excluded for missing treatment, outcome, or confounder values")
    if suppressed:
        parts.append(f"suppressed strata below {min_stratum} per group: {suppressed}")
    adjusted_effect: float | None = None
    adjusted_ci95: tuple[float, float] | None = None
    naive_agrees: bool | None = None
    if sufficient:
        adjusted_effect = round(sum(weight * statistic(stratum_a, stratum_b) for _, stratum_a, stratum_b, weight in sufficient) / sum(weight for _, _, _, weight in sufficient), 3)
        if not isfinite(adjusted_effect): raise ValueError("statistic must return finite values")
        rng = Random(seed)
        joint: list[float] = []
        for _ in range(resamples):
            weighted_total = 0.0
            weight_total = 0
            for _, stratum_a, stratum_b, weight in sufficient:
                sample_a = [stratum_a[rng.randrange(len(stratum_a))] for _ in stratum_a]
                sample_b = [stratum_b[rng.randrange(len(stratum_b))] for _ in stratum_b]
                weighted_total += weight * statistic(sample_a, sample_b)
                weight_total += weight
            joint.append(weighted_total / weight_total)
        adjusted_ci95 = percentile_interval(joint)
        if naive.value is None:
            naive_agrees = None
        else:
            naive_agrees = _sign(naive.value) == _sign(adjusted_effect) or naive.value == 0 or adjusted_effect == 0
            if naive_agrees is False:
                parts.append("naive direction reverses after adjustment; report the adjusted result, never the naive contrast")
    else:
        parts.append("no stratum met the minimum per group; no adjusted estimate is reported")
    return StratifiedComparison(outcome, (group_a, group_b), len(analysis), tuple(excluded), tuple(strata), tuple(suppressed), naive, adjusted_effect, adjusted_ci95, naive_agrees, min_stratum, resamples, seed, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "; ".join(parts))
