"""Minimal JSON Schema 2020-12 subset interpreter, executed (not just read) on
both sides of the Midnight Desktop Host contract.

``Performance`` and ``desktop`` are both deliberately dependency-free (no
``jsonschema``, no ``ajv``).  Rather than hand-writing two independent,
possibly-drifting validators, this module and its TypeScript twin
(``desktop/host/schemaValidator.ts``) each implement the same small vocabulary
— ``type``, ``required``, ``properties``, ``items``, ``enum``, ``const``,
``minimum``/``maximum``, ``minLength``, ``additionalProperties: false``, and a
single top-level ``oneOf`` — and both execute the exact same ``.schema.json``
files in ``schemas/``.  The schema documents are the contract; this
interpreter is what makes that literally true rather than aspirational.

The subset intentionally excludes ``$ref``, nested ``oneOf``/``allOf``, and
other JSON Schema features the four schemas in this package do not need.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMAS_DIR = Path(__file__).parent / "schemas"

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


class ContractValidationError(ValueError):
    """Raised when a document fails validation against a contract schema."""

    def __init__(self, schema_name: str, violations: list[str]) -> None:
        self.schema_name = schema_name
        self.violations = violations
        super().__init__(f"{schema_name}: " + "; ".join(violations))


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _matches_type(instance: Any, type_name: str) -> bool:
    expected = _TYPE_MAP[type_name]
    if type_name == "integer":
        # bool is a subclass of int in Python; a JSON boolean must never pass an
        # "integer" check even though isinstance(True, int) is true.
        return isinstance(instance, int) and not isinstance(instance, bool)
    if type_name == "boolean":
        return isinstance(instance, bool)
    if type_name == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    return isinstance(instance, expected)


def validate(schema: dict[str, Any], instance: Any, path: str = "$") -> list[str]:
    """Return a list of human-readable violation messages (empty = valid)."""
    if "oneOf" in schema:
        branches = schema["oneOf"]
        matches = [branch for branch in branches if not validate(branch, instance, path)]
        if len(matches) == 1:
            return []
        if not matches:
            return [f"{path}: matches none of the {len(branches)} allowed shapes"]
        return [f"{path}: matches {len(matches)} allowed shapes, expected exactly one"]

    violations: list[str] = []

    schema_type = schema.get("type")
    if schema_type is not None:
        type_names = schema_type if isinstance(schema_type, list) else [schema_type]
        if not any(_matches_type(instance, name) for name in type_names):
            violations.append(f"{path}: expected type {schema_type}, got {type(instance).__name__}")
            return violations  # further structural checks are meaningless on a type mismatch

    if "const" in schema and instance != schema["const"]:
        violations.append(f"{path}: expected constant value {schema['const']!r}, got {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        violations.append(f"{path}: {instance!r} is not one of {schema['enum']!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            violations.append(f"{path}: string shorter than minLength {schema['minLength']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            violations.append(f"{path}: {instance} is below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            violations.append(f"{path}: {instance} is above maximum {schema['maximum']}")

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                violations.append(f"{path}: missing required property '{key}'")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    violations.append(f"{path}: unexpected property '{key}'")
        for key, subschema in properties.items():
            if key in instance:
                violations.extend(validate(subschema, instance[key], f"{path}.{key}"))

    if isinstance(instance, list) and "items" in schema:
        item_schema = schema["items"]
        for index, item in enumerate(instance):
            violations.extend(validate(item_schema, item, f"{path}[{index}]"))

    return violations


def _validate_or_raise(schema_name: str, instance: Any) -> None:
    schema = load_schema(schema_name)
    violations = validate(schema, instance)
    if violations:
        raise ContractValidationError(schema_name, violations)


def validate_project_descriptor(document: Any) -> None:
    _validate_or_raise("project-descriptor.schema.json", document)


def validate_host_envelope(document: Any) -> None:
    _validate_or_raise("host-envelope.schema.json", document)


def validate_activity_response(document: Any) -> None:
    _validate_or_raise("activity-response.schema.json", document)


def validate_error_response(document: Any) -> None:
    _validate_or_raise("error-response.schema.json", document)


def validate_graph_prompt_run_response(document: Any) -> None:
    _validate_or_raise("graph-prompt-run-response.schema.json", document)


def validate_memory_citation_refresh_response(document: Any) -> None:
    _validate_or_raise("memory-citation-refresh-response.schema.json", document)


def validate_project_insight_response(document: Any) -> None:
    _validate_or_raise("project-insight-response.schema.json", document)


def validate_project_insight_feedback_response(document: Any) -> None:
    _validate_or_raise("project-insight-feedback-response.schema.json", document)
