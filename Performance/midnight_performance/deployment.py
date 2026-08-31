"""Tenant isolation plus local-first self-hosted and BYOC deployment contracts.

The implementation deliberately manages only local Performance files.  Cloud
transport and credentials remain customer-owned references, never SDK clients
or stored secrets in this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import shutil
from typing import Mapping

from .contracts import Identity
from .ledger import EvidenceLedger
from .privacy import PrivacyPolicy
from .work_queue import DerivedWorkQueue


DEPLOYMENT_SCHEMA_VERSION = 1


class ScopedWorkload(str, Enum):
    OBSERVATIONS = "observations"
    CODE_REFERENCE = "code_reference"
    WATCH_REFERENCE = "watch_reference"
    DATASET = "dataset"
    EXPERIMENT = "experiment"
    MODEL = "model"
    MEMORY = "memory"
    EMBEDDING = "embedding"
    API = "api"
    RECOMMENDATION = "recommendation"


@dataclass(frozen=True, slots=True)
class TenantScope:
    tenant_id: str
    project: Identity
    workspace_id: str
    repository_id: str

    def __post_init__(self) -> None:
        if not all((self.tenant_id.strip(), self.workspace_id.strip(), self.repository_id.strip())):
            raise ValueError("tenant, workspace, and repository identifiers are required")


@dataclass(frozen=True, slots=True)
class ScopedResource:
    scope: TenantScope
    workload: ScopedWorkload
    resource_id: str

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValueError("scoped resource id is required")


class TenantIsolation:
    """Registry that makes every resource's tenant/project/workspace/repository binding explicit."""

    def __init__(self) -> None:
        self._resources: dict[tuple[ScopedWorkload, str], ScopedResource] = {}

    def register(self, resource: ScopedResource) -> None:
        key = (resource.workload, resource.resource_id)
        existing = self._resources.get(key)
        if existing is not None and existing != resource:
            raise PermissionError("resource identity is already bound to another tenant scope")
        self._resources[key] = resource

    def authorize(self, scope: TenantScope, workload: ScopedWorkload, resource_id: str) -> ScopedResource:
        try:
            resource = self._resources[(workload, resource_id)]
        except KeyError as exc:
            raise KeyError("unknown scoped resource") from exc
        if resource.scope != scope:
            raise PermissionError("cross-tenant/project/workspace/repository access rejected")
        return resource


@dataclass(frozen=True, slots=True)
class ResourceSizing:
    cpu_cores: int
    memory_mb: int
    worker_capacity: int

    def __post_init__(self) -> None:
        if self.cpu_cores < 1 or self.memory_mb < 128 or self.worker_capacity < 1:
            raise ValueError("resource sizing must reserve CPU, 128MB memory, and worker capacity")


@dataclass(frozen=True, slots=True)
class SecretReference:
    name: str
    required: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or any(token in self.name.lower() for token in ("=", "secret:", "password:")):
            raise ValueError("secret references contain names only, never secret values")


@dataclass(frozen=True, slots=True)
class SelfHostedConfig:
    root: Path
    scope: TenantScope
    privacy: PrivacyPolicy
    sizing: ResourceSizing
    secrets: tuple[SecretReference, ...] = ()
    local_ai_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.privacy.self_hosted or self.privacy.byoc:
            raise ValueError("self-hosted deployment requires self_hosted privacy mode")


@dataclass(frozen=True, slots=True)
class DeploymentHealth:
    healthy: bool
    migration_version: int | None
    pending_work: int
    degraded_components: tuple[str, ...]
    issues: tuple[str, ...]


class SelfHostedDeployment:
    """Local lifecycle operations for one ledger; no server, agent, or cloud process is launched."""

    _MIGRATION_FILE = "schema-version"

    def __init__(self, config: SelfHostedConfig, ledger: EvidenceLedger, workers: DerivedWorkQueue | None = None) -> None:
        if ledger.project != config.scope.project:
            raise PermissionError("self-hosted ledger must match deployment project scope")
        self.config, self.ledger, self.workers = config, ledger, workers

    @property
    def migration_path(self) -> Path:
        return self.config.root / self._MIGRATION_FILE

    def migrate(self) -> int:
        self.config.root.mkdir(parents=True, exist_ok=True)
        current = self._migration_version()
        if current is not None and current > DEPLOYMENT_SCHEMA_VERSION:
            raise ValueError("deployment data uses a newer schema")
        self.migration_path.write_text(str(DEPLOYMENT_SCHEMA_VERSION), encoding="utf-8")
        return DEPLOYMENT_SCHEMA_VERSION

    def health(self) -> DeploymentHealth:
        issues: list[str] = []
        version = self._migration_version()
        if version != DEPLOYMENT_SCHEMA_VERSION:
            issues.append("migration is not current")
        try:
            tuple(self.ledger.replay())
        except ValueError:
            issues.append("ledger replay failed")
        pending = self.workers.pending if self.workers else 0
        degraded = tuple(sorted(item.value for item in self.workers.degraded_components)) if self.workers else ()
        if degraded:
            issues.append("derived workers degraded")
        return DeploymentHealth(not issues, version, pending, degraded, tuple(issues))

    def backup(self, destination: Path) -> Path:
        if destination.exists():
            raise FileExistsError("backup destination must not already exist")
        destination.mkdir(parents=True)
        if self.ledger.path.exists():
            shutil.copy2(self.ledger.path, destination / self.ledger.path.name)
        if self.migration_path.exists():
            shutil.copy2(self.migration_path, destination / self._MIGRATION_FILE)
        return destination

    def restore(self, source: Path, *, overwrite: bool = False) -> None:
        source_ledger = source / self.ledger.path.name
        source_migration = source / self._MIGRATION_FILE
        if not source_ledger.exists() or not source_migration.exists():
            raise FileNotFoundError("backup is incomplete")
        try:
            source_version = int(source_migration.read_text(encoding="utf-8").strip())
        except ValueError as exc:
            raise ValueError("backup migration marker is invalid") from exc
        if source_version != DEPLOYMENT_SCHEMA_VERSION:
            raise ValueError("backup schema version is unsupported")
        if (self.ledger.path.exists() or self.migration_path.exists()) and not overwrite:
            raise FileExistsError("restore would overwrite local deployment; pass overwrite=True")
        self.config.root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_ledger, self.ledger.path)
        shutil.copy2(source_migration, self.migration_path)
        tuple(self.ledger.replay())

    def _migration_version(self) -> int | None:
        if not self.migration_path.exists():
            return None
        try:
            return int(self.migration_path.read_text(encoding="utf-8").strip())
        except ValueError as exc:
            raise ValueError("invalid deployment migration marker") from exc


@dataclass(frozen=True, slots=True)
class BringYourOwnCloudConfig:
    scope: TenantScope
    privacy: PrivacyPolicy
    customer_data_plane: str
    workload_locations: Mapping[ScopedWorkload, str]

    def __post_init__(self) -> None:
        if not self.privacy.byoc or self.privacy.self_hosted:
            raise ValueError("BYOC deployment requires byoc privacy mode")
        if not self.customer_data_plane.strip() or any(not location.strip() for location in self.workload_locations.values()):
            raise ValueError("BYOC requires customer-controlled workload location references")
        if set(self.workload_locations) != set(ScopedWorkload):
            raise ValueError("BYOC must locate every scoped workload in the customer data plane")
