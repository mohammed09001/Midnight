"""Python-side resolution and validation of the canonical Midnight project
descriptor (``midnight.project.json``).

The trusted Node Desktop Host (``desktop/host/projectBinding.ts``) is what
resolves the project binding on behalf of the renderer — this module never
runs in response to a renderer request. It exists so the Python/host
production side of the contract validates the descriptor too (the shared
schema must be validated on both sides), as defense in depth for anything
that invokes the bridge directly (tests, CLI operators) rather than
exclusively through the Node Host.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .contract_schema import ContractValidationError, validate_project_descriptor

DESCRIPTOR_FILENAME = "midnight.project.json"
_MAX_WALK_LEVELS = 32


class ProjectDescriptorError(ValueError):
    """Raised when the project descriptor is missing, malformed, or unsafe."""


@dataclass(frozen=True, slots=True)
class ProjectDescriptor:
    descriptor_version: int
    project_id: str
    performance_data_dir: Path  # absolute, resolved, guaranteed inside project root
    workspace_id: str | None


def find_descriptor_file(start_dir: Path) -> Path:
    """Walk upward from ``start_dir`` looking for the canonical descriptor."""
    current = start_dir.resolve()
    for _ in range(_MAX_WALK_LEVELS):
        candidate = current / DESCRIPTOR_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise ProjectDescriptorError(f"no {DESCRIPTOR_FILENAME} found above {start_dir}")


def resolve_project_descriptor(start_dir: Path) -> ProjectDescriptor:
    """Locate, validate, and resolve the canonical project binding.

    Never accepts a filesystem path from a caller other than ``start_dir``
    (the search origin) — the descriptor's own content is the only source of
    the Performance data location, and it is resolved relative to the
    descriptor file itself, never to caller-supplied input.
    """
    descriptor_path = find_descriptor_file(start_dir)
    try:
        raw = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectDescriptorError(f"unreadable project descriptor: {exc}") from exc

    try:
        validate_project_descriptor(raw)
    except ContractValidationError as exc:
        raise ProjectDescriptorError(str(exc)) from exc

    project_root = descriptor_path.parent.resolve()
    relative = raw["performanceDataDir"]
    resolved = (project_root / relative).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ProjectDescriptorError(
            f"performanceDataDir '{relative}' escapes the project root"
        ) from exc

    return ProjectDescriptor(
        descriptor_version=raw["descriptorVersion"],
        project_id=raw["projectId"],
        performance_data_dir=resolved,
        workspace_id=raw.get("workspaceId"),
    )
