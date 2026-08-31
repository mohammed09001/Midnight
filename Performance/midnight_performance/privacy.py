"""Fail-closed content controls applied before evidence is durable or exported."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import re
from typing import Mapping

from .contracts import Observation


class ContentCategory(str, Enum):
    METADATA = "metadata"
    PROMPT_TEXT = "prompt_text"
    MODEL_CONTENT = "model_content"
    SOURCE_CODE = "source_code"
    DIFF = "diff"
    COMMAND_DETAILS = "command_details"
    TOOL_DETAILS = "tool_details"
    TRANSCRIPT = "transcript"
    REPOSITORY_METADATA = "repository_metadata"
    SIBLING_REFERENCE = "sibling_reference"
    PII = "pii"
    SECRET = "secret"
    CREDENTIAL = "credential"


class RetentionClass(str, Enum):
    EPHEMERAL = "ephemeral"
    STANDARD = "standard"
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    """Independent controls; all non-metadata content is denied by default."""

    allowed_categories: frozenset[ContentCategory] = frozenset({ContentCategory.METADATA})
    retention: RetentionClass = RetentionClass.STANDARD
    allow_export: bool = False
    self_hosted: bool = True
    byoc: bool = False

    def __post_init__(self) -> None:
        if self.self_hosted == self.byoc:
            raise ValueError("choose exactly one storage mode: self_hosted or byoc")

    def allows(self, category: ContentCategory) -> bool:
        return category in self.allowed_categories


class PrivacyViolation(ValueError):
    pass


_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|password|secret|token|credential)\s*[:=]\s*['\"]?[^\s'\"]+"
    r"|(?:AKIA[0-9A-Z]{16})|(?:-----BEGIN [A-Z ]+PRIVATE KEY-----)"
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PrivacyGuard:
    policy: PrivacyPolicy
    field_categories: Mapping[str, ContentCategory] = field(default_factory=dict)

    def protect(self, observation: Observation) -> Observation:
        """Filter non-permitted fields, reject unclassified fields, and redact secrets."""
        protected: dict[str, object] = {}
        for name, value in observation.payload.items():
            category = self.field_categories.get(name)
            if category is None:
                raise PrivacyViolation(f"payload field '{name}' has no content category")
            if not self.policy.allows(category):
                continue
            protected[name] = self._redact(value)
        return replace(observation, payload=protected)

    def exportable(self, observation: Observation) -> Observation:
        if not self.policy.allow_export:
            raise PrivacyViolation("export is disabled by policy")
        return self.protect(observation)

    @staticmethod
    def _redact(value: object) -> object:
        if isinstance(value, str):
            value = _SENSITIVE.sub("[REDACTED]", value)
            return _EMAIL.sub("[REDACTED_EMAIL]", value)
        if isinstance(value, Mapping):
            return {
                key: "[REDACTED]" if re.search(r"(?i)(api[_-]?key|password|secret|token|credential)", str(key)) else PrivacyGuard._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [PrivacyGuard._redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(PrivacyGuard._redact(item) for item in value)
        return value
