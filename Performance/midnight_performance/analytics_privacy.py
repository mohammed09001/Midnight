"""Privacy-preserving transformations for rebuildable analytical datasets."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib

from .dataset import DatasetRow
from .dataset_versioning import DatasetSnapshot, snapshot
from .privacy import ContentCategory


@dataclass(frozen=True, slots=True)
class AnalyticsPrivacyPolicy:
    version: str
    feature_only: bool = False
    pseudonymization_salt: str | None = None
    retain_raw_prompt: bool = False
    retain_source: bool = False

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("analytics privacy policy requires a version")
        if self.pseudonymization_salt is not None and not self.pseudonymization_salt:
            raise ValueError("pseudonymization salt must be non-empty when supplied")

    def allows_raw_content(self, category: ContentCategory) -> bool:
        """Make prompt/source retention an explicit analytical-policy decision."""
        return (category is ContentCategory.PROMPT_TEXT and self.retain_raw_prompt) or (category is ContentCategory.SOURCE_CODE and self.retain_source)

    def audit_record(self) -> dict[str, object]:
        """Stable, non-secret policy metadata suitable for an audit trail."""
        return {
            "version": self.version,
            "feature_only": self.feature_only,
            "retain_raw_prompt": self.retain_raw_prompt,
            "retain_source": self.retain_source,
            "pseudonymization_enabled": self.pseudonymization_salt is not None,
        }


@dataclass(frozen=True, slots=True)
class DeletionPropagation:
    deleted_prompt_run_ids: tuple[str, ...]
    before_fingerprint: str
    after_fingerprint: str
    policy_version: str


def minimize_rows(rows: tuple[DatasetRow, ...], policy: AnalyticsPrivacyPolicy) -> tuple[DatasetRow, ...]:
    """Remove non-feature analytical content and pseudonymize stable row identifiers."""
    result = []
    for row in rows:
        prompt_run_id = _pseudonymize(row.prompt_run_id, policy.pseudonymization_salt) if policy.pseudonymization_salt else row.prompt_run_id
        lineage = () if policy.feature_only else row.lineage
        metadata = {} if policy.feature_only else dict(row.agent_metadata)
        result.append(replace(row, prompt_run_id=prompt_run_id, lineage=lineage, agent_metadata=metadata))
    return tuple(result)


def propagate_deletion(dataset: DatasetSnapshot, prompt_run_ids: tuple[str, ...], policy: AnalyticsPrivacyPolicy) -> tuple[DatasetSnapshot, DeletionPropagation]:
    """Produce a new snapshot without deleted subjects; never mutates prior evidence."""
    targets = frozenset(prompt_run_ids)
    if not targets or any(not item.strip() for item in targets):
        raise ValueError("at least one non-empty prompt run id is required")
    survivors = tuple(row for row in dataset.rows if row.prompt_run_id not in targets)
    rebuilt = snapshot(dataset.definition, survivors)
    event = DeletionPropagation(tuple(sorted(targets & {row.prompt_run_id for row in dataset.rows})), dataset.fingerprint, rebuilt.fingerprint, policy.version)
    return rebuilt, event


def _pseudonymize(value: str, salt: str) -> str:
    return "p_" + hashlib.sha256((salt + "\0" + value).encode()).hexdigest()[:24]
