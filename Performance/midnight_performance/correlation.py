"""Correlation analysis over prompt-experience variables; correlations stay associative, never causal."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from math import erfc, exp, isfinite, lgamma, log, sqrt
from .contracts import ClaimKind
from .stats_tests import tie_corrected_ranks

_METHOD = "correlation"
_VERSION = "1"
DEFAULT_MIN_OBSERVATIONS = 5

class CorrelationKind(str, Enum): PEARSON="pearson"; SPEARMAN="spearman"; CRAMERS_V="cramers_v"; CORRELATION_RATIO="correlation_ratio"

@dataclass(frozen=True, slots=True)
class CorrelationResult:
    x: str; y: str; kind: CorrelationKind; n: int; statistic: float | None; p_value: float | None; sufficient: bool; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if not self.x.strip() or not self.y.strip(): raise ValueError("correlation variables must be named")
        if self.n < 0: raise ValueError("observation count must not be negative")
        if self.sufficient and self.statistic is None: raise ValueError("sufficient correlations carry a statistic")
        if not self.sufficient and self.statistic is not None: raise ValueError("insufficient correlations carry no statistic")

@dataclass(frozen=True, slots=True)
class CorrelationReport:
    rows: int; numeric: tuple[str, ...]; categorical: tuple[str, ...]; with_label: bool; pairs: tuple[CorrelationResult, ...]; method: str; method_version: str; claim_kind: str; uncertainty: str
    def __post_init__(self):
        if self.rows < 0: raise ValueError("row count must not be negative")

def _numeric_pairs(xs, ys) -> tuple[tuple[float, float], ...]:
    if len(xs) != len(ys): raise ValueError("correlated variables must have equal length")
    pairs = []
    for x, y in zip(xs, ys):
        if x is None or y is None: raise ValueError("pass pairwise-complete values; None entries are filtered by the caller")
        left, right = float(x), float(y)
        if not isfinite(left) or not isfinite(right): raise ValueError("correlation values must be finite numbers")
        pairs.append((left, right))
    return tuple(pairs)

def _categorical_pairs(xs, ys) -> tuple[tuple[str, str], ...]:
    if len(xs) != len(ys): raise ValueError("correlated variables must have equal length")
    pairs = []
    for x, y in zip(xs, ys):
        if x is None or y is None: raise ValueError("pass pairwise-complete values; None entries are filtered by the caller")
        pairs.append((str(x), str(y)))
    return tuple(pairs)

def _complete(xs, ys) -> tuple[list, list]:
    left, right = [], []
    for x, y in zip(xs, ys):
        if x is None or y is None: continue
        left.append(x)
        right.append(y)
    return left, right

def _insufficient(x_name: str, y_name: str, kind: CorrelationKind, n: int, note: str) -> CorrelationResult:
    return CorrelationResult(x_name, y_name, kind, n, None, None, False, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, note)

def _coefficient(xs: list[float], ys: list[float]) -> float | None:
    count = len(xs)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0: return None
    return max(-1.0, min(1.0, covariance / sqrt(var_x * var_y)))

def _normal_approximation_p(r: float, n: int) -> float:
    if abs(r) == 1.0: return 0.0
    return min(1.0, erfc(abs(r) * sqrt((n - 2) / (1 - r * r)) / sqrt(2)))

def _gate(name_x: str, name_y: str, kind: CorrelationKind, n: int, min_observations: int) -> CorrelationResult | None:
    if min_observations < 2: raise ValueError("minimum observations must be at least two")
    if n < min_observations:
        return _insufficient(name_x, name_y, kind, n, f"{n} complete observations is below {min_observations}; correlation over a handful of runs invents precision")
    return None

def pearson(x_name: str, xs, y_name: str, ys, *, min_observations: int = DEFAULT_MIN_OBSERVATIONS) -> CorrelationResult:
    """Linear association with a normal-approximation p-value over pairwise-complete observations."""
    pairs = _numeric_pairs(xs, ys)
    gated = _gate(x_name, y_name, CorrelationKind.PEARSON, len(pairs), min_observations)
    if gated: return gated
    r = _coefficient([x for x, _ in pairs], [y for _, y in pairs])
    if r is None:
        return _insufficient(x_name, y_name, CorrelationKind.PEARSON, len(pairs), "zero variance in at least one variable; no correlation is defined")
    return CorrelationResult(x_name, y_name, CorrelationKind.PEARSON, len(pairs), round(r, 3), round(_normal_approximation_p(r, len(pairs)), 6), True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "pearson measures linear association; the p-value is a normal approximation; correlation is not causation")

def spearman(x_name: str, xs, y_name: str, ys, *, min_observations: int = DEFAULT_MIN_OBSERVATIONS) -> CorrelationResult:
    """Monotonic association over tie-corrected ranks; robust to non-normal metric distributions."""
    pairs = _numeric_pairs(xs, ys)
    gated = _gate(x_name, y_name, CorrelationKind.SPEARMAN, len(pairs), min_observations)
    if gated: return gated
    rank_x = tie_corrected_ranks(tuple(x for x, _ in pairs))
    rank_y = tie_corrected_ranks(tuple(y for _, y in pairs))
    r = _coefficient(rank_x, rank_y)
    if r is None:
        return _insufficient(x_name, y_name, CorrelationKind.SPEARMAN, len(pairs), "zero variance in at least one variable; no correlation is defined")
    return CorrelationResult(x_name, y_name, CorrelationKind.SPEARMAN, len(pairs), round(r, 3), round(_normal_approximation_p(r, len(pairs)), 6), True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "spearman measures monotonic association over ranks; the p-value is a normal approximation; correlation is not causation")

def _chi2_sf(statistic: float, degrees: int) -> float:
    """Upper tail of the chi-square distribution via the regularized upper incomplete gamma."""
    if degrees < 1: raise ValueError("chi-square degrees of freedom must be positive")
    if statistic <= 0: return 1.0
    a, x = degrees / 2, statistic / 2
    if x < a + 1:
        term = 1.0 / a
        total = term
        ap = a
        for _ in range(500):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-14: break
        return max(0.0, min(1.0, 1.0 - total * exp(-x + a * log(x) - lgamma(a))))
    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < tiny: d = tiny
        c = b + an / c
        if abs(c) < tiny: c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14: break
    return max(0.0, min(1.0, exp(-x + a * log(x) - lgamma(a)) * h))

def cramers_v(x_name: str, xs, y_name: str, ys, *, min_observations: int = DEFAULT_MIN_OBSERVATIONS) -> CorrelationResult:
    """Categorical association strength over a contingency table with an analytic chi-square p-value."""
    pairs = _categorical_pairs(xs, ys)
    gated = _gate(x_name, y_name, CorrelationKind.CRAMERS_V, len(pairs), min_observations)
    if gated: return gated
    n = len(pairs)
    row_counts = Counter(x for x, _ in pairs)
    column_counts = Counter(y for _, y in pairs)
    rows, columns = len(row_counts), len(column_counts)
    if min(rows, columns) < 2:
        return _insufficient(x_name, y_name, CorrelationKind.CRAMERS_V, n, "a variable with a single level has no categorical association to measure")
    chi2 = 0.0
    cells = Counter(pairs)
    for x_value in row_counts:
        for y_value in column_counts:
            expected = row_counts[x_value] * column_counts[y_value] / n
            observed = cells.get((x_value, y_value), 0)
            chi2 += (observed - expected) ** 2 / expected
    v = sqrt(chi2 / (n * (min(rows, columns) - 1)))
    p = _chi2_sf(chi2, (rows - 1) * (columns - 1))
    return CorrelationResult(x_name, y_name, CorrelationKind.CRAMERS_V, n, round(v, 3), round(p, 6), True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "cramer's v measures categorical association strength; correlation is not causation")

def correlation_ratio(x_name: str, values, y_name: str, groups, *, min_observations: int = DEFAULT_MIN_OBSERVATIONS) -> CorrelationResult:
    """Association between a numeric variable and a categorical grouping via variance share (eta)."""
    if len(values) != len(groups): raise ValueError("correlated variables must have equal length")
    paired = []
    for value, group in zip(values, groups):
        if value is None or group is None: raise ValueError("pass pairwise-complete values; None entries are filtered by the caller")
        number = float(value)
        if not isfinite(number): raise ValueError("correlation values must be finite numbers")
        paired.append((number, str(group)))
    gated = _gate(x_name, y_name, CorrelationKind.CORRELATION_RATIO, len(paired), min_observations)
    if gated: return gated
    by_group: dict[str, list[float]] = {}
    for value, group in paired:
        by_group.setdefault(group, []).append(value)
    if len(by_group) < 2:
        return _insufficient(x_name, y_name, CorrelationKind.CORRELATION_RATIO, len(paired), "a single group gives no between-group separation to measure")
    grand = sum(value for value, _ in paired) / len(paired)
    ss_total = sum((value - grand) ** 2 for value, _ in paired)
    if ss_total == 0:
        return _insufficient(x_name, y_name, CorrelationKind.CORRELATION_RATIO, len(paired), "zero variance overall; no correlation ratio is defined")
    ss_between = sum(len(group_values) * (sum(group_values) / len(group_values) - grand) ** 2 for group_values in by_group.values())
    eta = sqrt(ss_between / ss_total)
    return CorrelationResult(x_name, y_name, CorrelationKind.CORRELATION_RATIO, len(paired), round(eta, 3), None, True, _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "eta shares variance across groups; direction is undefined and no p-value is reported; association is not causation")

def analyze_correlations(rows, *, numeric: tuple[str, ...] = (), categorical: tuple[str, ...] = (), include_label: bool = True, min_observations: int = DEFAULT_MIN_OBSERVATIONS) -> CorrelationReport:
    """Pairwise correlations across prompt features, categorical context, and the user-feedback label."""
    population = tuple(rows)
    numeric_names = tuple(numeric) if numeric else tuple(sorted({name for row in population for name in row.features}))
    categorical_names = tuple(sorted(dict.fromkeys(categorical)))
    pairs: list[CorrelationResult] = []
    for index, x_name in enumerate(numeric_names):
        for y_name in numeric_names[index + 1:]:
            complete_x, complete_y = _complete([row.features.get(x_name) for row in population], [row.features.get(y_name) for row in population])
            pairs.append(pearson(x_name, complete_x, y_name, complete_y, min_observations=min_observations))
            pairs.append(spearman(x_name, complete_x, y_name, complete_y, min_observations=min_observations))
    for x_name in numeric_names:
        for y_name in categorical_names:
            complete_values, complete_groups = _complete([row.features.get(x_name) for row in population], [row.agent_metadata.get(y_name) for row in population])
            pairs.append(correlation_ratio(x_name, complete_values, y_name, complete_groups, min_observations=min_observations))
    if include_label:
        labels = [row.label for row in population]
        for x_name in numeric_names:
            complete_values, complete_labels = _complete([row.features.get(x_name) for row in population], labels)
            pairs.append(correlation_ratio(x_name, complete_values, "label", complete_labels, min_observations=min_observations))
        for x_name in categorical_names:
            complete_groups, complete_labels = _complete([row.agent_metadata.get(x_name) for row in population], labels)
            pairs.append(cramers_v(x_name, complete_groups, "label", complete_labels, min_observations=min_observations))
    for index, x_name in enumerate(categorical_names):
        for y_name in categorical_names[index + 1:]:
            complete_x, complete_y = _complete([row.agent_metadata.get(x_name) for row in population], [row.agent_metadata.get(y_name) for row in population])
            pairs.append(cramers_v(x_name, complete_x, y_name, complete_y, min_observations=min_observations))
    return CorrelationReport(len(population), numeric_names, categorical_names, include_label, tuple(pairs), _METHOD, _VERSION, ClaimKind.STATISTICAL.value, "every entry is a correlation over observed rows; confounders are not controlled and no entry is causal")
