"""Data-quality findings over dataset rows, before analytics or ML consumes them."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from collections import Counter
from .dataset import DatasetRow
from .dataset_versioning import DatasetDefinition

_METHOD = "data-quality"
_VERSION = "1"
_MISSINGNESS_LIMIT = .5
_IMBALANCE_LIMIT = .8

class QualitySeverity(str, Enum):
    WARNING = "warning"; CRITICAL = "critical"

@dataclass(frozen=True, slots=True)
class QualityFinding:
    check: str; severity: QualitySeverity; count: int; detail: str
    def __post_init__(self):
        if self.count < 1: raise ValueError("findings describe at least one offending item")

@dataclass(frozen=True, slots=True)
class QualityReport:
    rows_checked: int; findings: tuple[QualityFinding, ...]; method: str; method_version: str
    @property
    def passes(self) -> bool:
        return not any(finding.severity is QualitySeverity.CRITICAL for finding in self.findings)

def validate_quality(rows: tuple[DatasetRow, ...], definition: DatasetDefinition | None = None) -> QualityReport:
    """Measure quality hazards before analytics; findings are exposed, never silently repaired."""
    findings: list[QualityFinding] = []
    rows = tuple(rows)

    def add(check: str, severity: QualitySeverity, count: int, detail: str) -> None:
        if count:
            findings.append(QualityFinding(check, severity, count, detail))

    counts = Counter(row.prompt_run_id for row in rows)
    add("duplicate_rows", QualitySeverity.CRITICAL, sum(n - 1 for n in counts.values() if n > 1), f"repeated prompt run ids: {sorted(pid for pid, n in counts.items() if n > 1)}")
    add("invalid_identities", QualitySeverity.CRITICAL, sum(1 for row in rows if not row.prompt_run_id.strip()), "blank prompt run ids")
    anomalies = [(row.prompt_run_id, name) for row in rows for name, value in row.features.items() if value is not None and not 0 <= value <= 1]
    add("feature_anomalies", QualitySeverity.CRITICAL, len(anomalies), f"features outside zero-one bounds: {anomalies[:5]}")
    if definition is not None:
        incomplete_schema = [row.prompt_run_id for row in rows if set(definition.feature_schema) - set(row.features)]
        add("schema_coverage", QualitySeverity.CRITICAL, len(incomplete_schema), f"rows missing schema features: {incomplete_schema}")
        out_of_bounds = [row.prompt_run_id for row in rows if (definition.starts_at and row.observed_at < definition.starts_at) or (definition.ends_at and row.observed_at > definition.ends_at)]
        add("impossible_timestamps", QualitySeverity.CRITICAL, len(out_of_bounds), f"rows outside definition time bounds: {out_of_bounds}")
    if rows:
        feature_names = sorted({name for row in rows for name in row.features})
        sparse = [name for name in feature_names if sum(1 for row in rows if row.features.get(name) is None) / len(rows) > _MISSINGNESS_LIMIT]
        add("missingness", QualitySeverity.WARNING, len(sparse), f"features missing in more than {_MISSINGNESS_LIMIT} of rows: {sparse}")
    unlabeled = sum(1 for row in rows if row.label is None)
    add("label_sparsity", QualitySeverity.WARNING, 1 if rows and unlabeled / len(rows) > _MISSINGNESS_LIMIT else 0, f"{unlabeled}/{len(rows)} rows carry no label")
    labels = Counter(row.label for row in rows if row.label is not None)
    if labels:
        majority = max(labels.values())
        if majority / sum(labels.values()) > _IMBALANCE_LIMIT:
            add("class_imbalance", QualitySeverity.WARNING, 1, f"majority label holds {round(majority / sum(labels.values()), 3)} of labeled rows: {dict(labels)}")
    unlinked = [row.prompt_run_id for row in rows if not row.lineage or all(not ref.startswith(("c", "v")) for ref in row.lineage)]
    add("incomplete_linkage", QualitySeverity.WARNING, len(unlinked), f"rows without change/verification lineage: {unlinked}")
    ref_owners: dict[str, int] = {}
    for row in rows:
        for ref in row.lineage:
            ref_owners[ref] = ref_owners.get(ref, 0) + 1
    shared = sorted(ref for ref, n in ref_owners.items() if n > 1)
    add("leakage_risk", QualitySeverity.WARNING, len(shared), f"lineage references shared across rows: {shared[:5]}")
    return QualityReport(len(rows), tuple(findings), _METHOD, _VERSION)
