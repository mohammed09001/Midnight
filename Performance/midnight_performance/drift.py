"""Version and capability drift evaluation for passive adapters."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .harness import ObservationAdapter, Capability

class AdapterHealth(str, Enum): HEALTHY="healthy"; DEGRADED="degraded"; UNSUPPORTED_VERSION="unsupported_version"; HOOKS_MISSING="hooks_missing"; PERMISSION_REQUIRED="permission_required"; UNAVAILABLE="unavailable"
@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    adapter: str; supported_versions: frozenset[str]; capabilities: frozenset[Capability]
@dataclass(frozen=True, slots=True)
class HealthReport:
    health: AdapterHealth; gaps: tuple[str, ...]
def probe(adapter: ObservationAdapter, manifest: CapabilityManifest, *, provider_version: str | None, hooks_available: bool=True, permission_granted: bool=True) -> HealthReport:
    if provider_version is None: return HealthReport(AdapterHealth.UNAVAILABLE, ("unavailable:provider_version",))
    if provider_version not in manifest.supported_versions: return HealthReport(AdapterHealth.UNSUPPORTED_VERSION, (f"unavailable:unsupported_version:{provider_version}",))
    if not hooks_available: return HealthReport(AdapterHealth.HOOKS_MISSING, ("unavailable:hooks",))
    if not permission_granted: return HealthReport(AdapterHealth.PERMISSION_REQUIRED, ("unavailable:permission",))
    missing = manifest.capabilities - adapter.capabilities
    return HealthReport(AdapterHealth.DEGRADED if missing else AdapterHealth.HEALTHY, tuple(f"unavailable:{item.value}" for item in sorted(missing, key=lambda x:x.value)))
