"""Seeded bootstrap intervals for unstable or non-normal metrics, cohort differences, and historical rates."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import Callable, Sequence
from .contracts import ClaimKind

_METHOD = "bootstrap"
_VERSION = "1"
DEFAULT_RESAMPLES = 2000
DEFAULT_SEED = 0
DEFAULT_MIN_SIZE = 5

@dataclass(frozen=True, slots=True)
class BootstrapEstimate:
    estimate: str; n: int; n_b: int | None; value: float | None; ci95: tuple[float, float] | None; resamples: int; seed: int; sufficient: bool; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if not self.estimate.strip(): raise ValueError("estimate name is required")
        if self.resamples < 1: raise ValueError("resamples must be positive")
        if (self.value is None) is not (self.ci95 is None): raise ValueError("point estimate and interval are reported together or not at all")
        if self.sufficient and self.value is None: raise ValueError("sufficient estimates carry a value")
        if not self.sufficient and self.value is not None: raise ValueError("insufficient estimates carry no value")

def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)

def mean_difference(a: Sequence[float], b: Sequence[float]) -> float:
    """Default contrast statistic shared by cohort differences and stratified comparisons."""
    return _mean(a) - _mean(b)

def _validate(values: Sequence[float], resamples: int) -> None:
    if resamples < 1: raise ValueError("resamples must be positive")
    for value in values:
        if not isfinite(value): raise ValueError("values must be finite numbers")

def resample_one_sample(values: Sequence[float], statistic: Callable[[Sequence[float]], float], *, resamples: int, seed: int) -> list[float]:
    """Resample the observed sample with replacement under a fixed seed; the draw order is part of the contract."""
    rng = Random(seed)
    population = tuple(values)
    estimates = []
    for _ in range(resamples):
        estimates.append(statistic([population[rng.randrange(len(population))] for _ in population]))
    estimates.sort()
    return estimates

def resample_two_sample(a: Sequence[float], b: Sequence[float], statistic: Callable[[Sequence[float], Sequence[float]], float], *, resamples: int, seed: int) -> list[float]:
    """Resample both cohorts independently per iteration, first a then b, under one seeded stream."""
    rng = Random(seed)
    first, second = tuple(a), tuple(b)
    estimates = []
    for _ in range(resamples):
        sample_a = [first[rng.randrange(len(first))] for _ in first]
        sample_b = [second[rng.randrange(len(second))] for _ in second]
        estimates.append(statistic(sample_a, sample_b))
    estimates.sort()
    return estimates

def percentile_interval(estimates: Sequence[float], alpha: float = .05) -> tuple[float, float]:
    """Percentile interval of sorted resample statistics; non-finite resamples are rejected."""
    ordered = sorted(estimates)
    if not ordered: raise ValueError("percentile intervals require at least one resample")
    for value in ordered:
        if not isfinite(value): raise ValueError("resample statistics must be finite")
    low = ordered[int(len(ordered) * alpha / 2)]
    high = ordered[min(len(ordered) - 1, int(len(ordered) * (1 - alpha / 2)))]
    return (round(low, 3), round(high, 3))

def bootstrap_metric(values: Sequence[float], statistic: Callable[[Sequence[float]], float] = _mean, *, name: str = "mean", resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED, min_size: int = DEFAULT_MIN_SIZE) -> BootstrapEstimate:
    """Distribution-free interval for any unstable or non-normal performance metric over observed runs."""
    sample = tuple(float(value) for value in values)
    _validate(sample, resamples)
    if len(sample) < min_size:
        return BootstrapEstimate(name, len(sample), None, None, None, resamples, seed, False, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, f"samples below {min_size} get no interval; resampling a handful of runs invents precision")
    estimates = resample_one_sample(sample, statistic, resamples=resamples, seed=seed)
    value = round(statistic(sample), 3)
    if not isfinite(value): raise ValueError("statistic must return finite values")
    return BootstrapEstimate(name, len(sample), None, value, percentile_interval(estimates), resamples, seed, True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "percentile interval over seeded resamples of the observed sample; method, version, seed, and resample count are persisted for reproducibility")

def bootstrap_difference(a: Sequence[float], b: Sequence[float], statistic: Callable[[Sequence[float], Sequence[float]], float] = mean_difference, *, name: str = "mean_difference", resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED, min_size: int = DEFAULT_MIN_SIZE) -> BootstrapEstimate:
    """Interval for the cohort difference of any statistic; cohort sizes gate the conclusion."""
    first, second = tuple(float(value) for value in a), tuple(float(value) for value in b)
    _validate(first, resamples)
    _validate(second, resamples)
    if len(first) < min_size or len(second) < min_size:
        return BootstrapEstimate(name, len(first), len(second), None, None, resamples, seed, False, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, f"cohorts below {min_size} runs are not compared; sample size controls the conclusion")
    estimates = resample_two_sample(first, second, statistic, resamples=resamples, seed=seed)
    value = round(statistic(first, second), 3)
    if not isfinite(value): raise ValueError("statistic must return finite values")
    return BootstrapEstimate(name, len(first), len(second), value, percentile_interval(estimates), resamples, seed, True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "percentile interval over seeded per-cohort resamples; the interval is associative, never causal")

def bootstrap_rate(successes: int, total: int, *, name: str = "rate", resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED, min_size: int = DEFAULT_MIN_SIZE) -> BootstrapEstimate:
    """Interval for a historical rate over observed trials; tiny denominators stay unreported."""
    if not isinstance(successes, int) or not isinstance(total, int): raise ValueError("rate trials must be integers")
    if total < 1 or successes < 0 or successes > total: raise ValueError("successes must be between zero and the cohort total")
    outcomes = tuple(1.0 if index < successes else 0.0 for index in range(total))
    return bootstrap_metric(outcomes, _mean, name=name, resamples=resamples, seed=seed, min_size=min_size)
