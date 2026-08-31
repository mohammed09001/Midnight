"""Portable deployment parity and bring-your-own data/ML resource contracts.

These contracts do not open cloud connections or retain credential values.
They make deployment semantics and customer-controlled resource bindings
explicit so managed cloud is never architecturally privileged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .deployment import TenantScope
from .privacy import ContentCategory


PORTABLE_CONTRACT_VERSION = 1


class DeploymentMode(str, Enum):
    SELF_HOSTED = "self_hosted"
    BYOC = "byoc"
    MANAGED = "managed"


@dataclass(frozen=True, slots=True)
class PrivacyGuarantee:
    allowed_categories: frozenset[ContentCategory]
    export_enabled: bool
    retention: str

    def __post_init__(self) -> None:
        if not self.retention.strip():
            raise ValueError("privacy guarantee requires a retention policy")


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    mode: DeploymentMode
    scope: TenantScope
    privacy: PrivacyGuarantee
    export_paths: frozenset[str]
    analytical_semantics_version: int = PORTABLE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.analytical_semantics_version < 1 or not self.export_paths or any(not item.strip() for item in self.export_paths):
            raise ValueError("deployment profile requires versioned semantics and export paths")

    def assert_compatible_with(self, other: "DeploymentProfile") -> None:
        if self.scope != other.scope:
            raise PermissionError("deployment profiles cannot cross tenant/project scope")
        if self.privacy != other.privacy:
            raise ValueError("deployment profiles have incompatible privacy guarantees")
        if self.export_paths != other.export_paths or self.analytical_semantics_version != other.analytical_semantics_version:
            raise ValueError("deployment profiles have incompatible export paths or analytical semantics")


@dataclass(frozen=True, slots=True)
class ManagedCloudConfig:
    """An opt-in profile only; it has no higher authority than other modes."""

    profile: DeploymentProfile
    enabled: bool = False

    def __post_init__(self) -> None:
        if self.profile.mode is not DeploymentMode.MANAGED:
            raise ValueError("managed cloud config requires a managed deployment profile")
        if not self.enabled:
            raise PermissionError("managed cloud must be explicitly enabled")


class ResourceKind(str, Enum):
    OBJECT_STORAGE = "object_storage"
    ANALYTICAL_STORAGE = "analytical_storage"
    QUEUE = "queue"
    EMBEDDING = "embedding"
    MODEL_EXECUTION = "model_execution"
    ML_COMPUTE = "ml_compute"


@dataclass(frozen=True, slots=True)
class CredentialReference:
    """Opaque locator resolved by a dedicated credential layer outside Performance."""

    name: str
    secret_store: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.secret_store.strip() or any(token in self.name.lower() for token in ("=", "token:", "secret:", "password:")):
            raise ValueError("credential references must contain names and secure-store identifiers only")


class CredentialResolver(Protocol):
    def resolve(self, reference: CredentialReference) -> object: ...


@dataclass(frozen=True, slots=True)
class ResourceProvider:
    name: str
    version: str
    resources: frozenset[ResourceKind]
    local_or_customer_controlled: bool

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip() or not self.resources:
            raise ValueError("resource provider requires name, version, and supported resources")


@dataclass(frozen=True, slots=True)
class ResourceBinding:
    scope: TenantScope
    resource: ResourceKind
    provider: ResourceProvider
    credential: CredentialReference | None = None

    def __post_init__(self) -> None:
        if self.resource not in self.provider.resources:
            raise ValueError("provider does not support the bound resource")
        if not self.provider.local_or_customer_controlled:
            raise PermissionError("BYO resource bindings require a local or customer-controlled provider")


class BringYourOwnResourceRegistry:
    """Tenant-scoped provider bindings; credentials remain opaque references."""

    def __init__(self) -> None:
        self._bindings: dict[tuple[TenantScope, ResourceKind], ResourceBinding] = {}

    def bind(self, binding: ResourceBinding) -> None:
        key = (binding.scope, binding.resource)
        if key in self._bindings:
            raise ValueError("resource is already bound for this tenant scope")
        self._bindings[key] = binding

    def resolve(self, scope: TenantScope, resource: ResourceKind) -> ResourceBinding:
        try:
            return self._bindings[(scope, resource)]
        except KeyError as exc:
            raise PermissionError("resource is not bound for this tenant scope") from exc
