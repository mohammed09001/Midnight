"""Distribution-free cohort comparisons: effect size and uncertainty, not only p-values."""
from __future__ import annotations
from dataclasses import dataclass
from math import erfc, sqrt
from .bootstrap import percentile_interval, resample_two_sample
from .contracts import ClaimKind

_METHOD = "statistical-comparison"
_VERSION = "1"
_BOOTSTRAP_RESAMPLES = 200
_BOOTSTRAP_SEED = 0

@dataclass(frozen=True, slots=True)
class ComparisonResult:
    test: str; n_a: int; n_b: int; statistic: float | None; p_value: float | None; effect_size: float | None; effect_name: str; ci95: tuple[float, float] | None; sufficient: bool; alpha: float; method: str; method_version: str; claim_kind: str; uncertainty: str

def tie_corrected_ranks(values: tuple[float, ...]) -> list[float]:
    """Average ranks with tie correction; shared by rank-based comparisons and correlations."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        tie_end = index
        while tie_end + 1 < len(order) and values[order[tie_end + 1]] == values[order[index]]:
            tie_end += 1
        average_rank = (index + tie_end) / 2 + 1
        for position in range(index, tie_end + 1):
            ranks[order[position]] = average_rank
        index = tie_end + 1
    return ranks

def compare_samples(a: tuple[float, ...], b: tuple[float, ...], *, feature: str = "feature", alpha: float = .05, min_size: int = 5) -> ComparisonResult:
    """Tie-corrected Mann-Whitney U with rank-biserial effect and seeded bootstrap interval."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    n_a, n_b = len(a), len(b)
    if n_a < min_size or n_b < min_size:
        return ComparisonResult("mann_whitney_u", n_a, n_b, None, None, None, "rank_biserial", None, False, alpha, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, f"samples below {min_size} are not compared; sample size controls the conclusion")
    pooled = tuple(a) + tuple(b)
    ranks = tie_corrected_ranks(pooled)
    u_a = sum(ranks[:n_a]) - n_a * (n_a + 1) / 2
    u_b = n_a * n_b - u_a
    u = min(u_a, u_b)
    mean_u = n_a * n_b / 2
    tie_counts = {value: pooled.count(value) for value in set(pooled)}
    tie_term = sum(t ** 3 - t for t in tie_counts.values())
    n = n_a + n_b
    std_u = sqrt(n_a * n_b / 12 * ((n + 1) - tie_term / (n * (n - 1))))
    z = (u - mean_u) / std_u if std_u else 0.0
    p_value = min(1.0, erfc(abs(z) / sqrt(2)))
    effect = 1 - 2 * u_a / (n_a * n_b)
    ci = _bootstrap_ci(tuple(a), tuple(b))
    return ComparisonResult(
        "mann_whitney_u", n_a, n_b, round(u, 3), round(p_value, 6), round(effect, 3), "rank_biserial", ci, True, alpha,
        _METHOD, _VERSION, ClaimKind.STATISTICAL.value,
        "normal approximation handles ties; no distributional assumption about the feature; p-values accompany, never replace, effect size",
    )

def _rank_biserial(sample_a: list[float], sample_b: list[float]) -> float:
    """Rank-biserial effect of one resampled pair of cohorts."""
    ranks = tie_corrected_ranks(tuple(sample_a) + tuple(sample_b))
    u_a = sum(ranks[:len(sample_a)]) - len(sample_a) * (len(sample_a) + 1) / 2
    return 1 - 2 * u_a / (len(sample_a) * len(sample_b))

def _bootstrap_ci(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float]:
    """Deterministic bootstrap of the rank-biserial effect via the canonical seeded resampling engine."""
    return percentile_interval(resample_two_sample(tuple(a), tuple(b), _rank_biserial, resamples=_BOOTSTRAP_RESAMPLES, seed=_BOOTSTRAP_SEED))

def compare_proportions(accepted_a: int, n_a: int, accepted_b: int, n_b: int, *, alpha: float = .05, min_size: int = 5) -> ComparisonResult:
    """Two-proportion z comparison with risk-difference effect and Wald interval."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    if accepted_a > n_a or accepted_b > n_b or min(accepted_a, accepted_b) < 0:
        raise ValueError("accepted counts must not exceed cohort sizes")
    if n_a < min_size or n_b < min_size:
        return ComparisonResult("two_proportion_z", n_a, n_b, None, None, None, "risk_difference", None, False, alpha, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, f"cohorts below {min_size} are not compared")
    p_a, p_b = accepted_a / n_a, accepted_b / n_b
    pooled = (accepted_a + accepted_b) / (n_a + n_b)
    std = sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    z = (p_a - p_b) / std if std else 0.0
    p_value = min(1.0, erfc(abs(z) / sqrt(2)))
    difference = p_a - p_b
    std_diff = sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    ci = (round(difference - 1.96 * std_diff, 3), round(difference + 1.96 * std_diff, 3))
    return ComparisonResult(
        "two_proportion_z", n_a, n_b, round(z, 3), round(p_value, 6), round(difference, 3), "risk_difference", ci, True, alpha,
        _METHOD, _VERSION, ClaimKind.STATISTICAL.value,
        "risk difference with Wald interval; small-sample cohorts are gated by min_size",
    )
