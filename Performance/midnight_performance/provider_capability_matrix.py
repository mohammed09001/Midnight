"""Execution 04, Section A: a provider capability matrix built from actual
repository adapter code, diffed against the current, live official provider
interfaces researched for this execution (2026-09):

* Claude Code hooks — code.claude.com/docs/en/hooks
* Codex App Server — github.com/openai/codex `codex-rs/app-server/README.md`
* OpenCode plugins — opencode.ai/docs/plugins/

``CURRENT_PROVIDER_MANIFESTS`` is a snapshot of what each research pass
POSITIVELY confirmed, not a live fetch — it should be refreshed whenever a
future execution re-verifies these protocols, and its date should move with
it.

Two directions of drift matter and are reported separately:

* under-implementation — the live provider offers something our adapter
  doesn't implement (``drift.probe()``'s existing ``AdapterHealth``/gaps).
* over-claim — our adapter declares a capability this research pass could
  NOT positively confirm (``ProviderCapabilityEntry.unconfirmed_by_research``).
  This is deliberately NOT the same as "confirmed absent": Codex's dropped
  ``VERIFICATION``/``NATIVE_DIFF`` capabilities were removed from the
  adapter outright because research found a clear, positive absence (no
  first-class verification item type exists); OpenCode's weaker research
  pass ("not found in the pages fetched" is a much softer signal than "does
  not exist") is instead surfaced here as an honest open question, never
  silently stripped from the adapter on incomplete evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .claude_adapter import CLAUDE_ADAPTER
from .codex_adapter import CODEX_ADAPTER
from .drift import AdapterHealth, CapabilityManifest, HealthReport, probe
from .harness import Capability, ObservationAdapter
from .opencode_adapter import OPENCODE_ADAPTER


CURRENT_PROVIDER_MANIFESTS: Mapping[str, CapabilityManifest] = {
    "claude-code": CapabilityManifest(
        "claude-code", frozenset({"1"}),
        frozenset({
            Capability.SESSION_LIFECYCLE, Capability.PROMPT, Capability.TOOL_CALL,
            Capability.FILE_CHANGE, Capability.SUBAGENT, Capability.PERMISSION,
            Capability.COMPLETION, Capability.TRANSCRIPT,
        }),
    ),
    "codex": CapabilityManifest(
        "codex", frozenset({"1", "2"}),
        frozenset({
            Capability.SESSION_LIFECYCLE, Capability.TURN_LIFECYCLE, Capability.TOOL_CALL,
            Capability.COMMAND, Capability.FILE_CHANGE, Capability.COMPLETION,
            Capability.USAGE, Capability.PROMPT,
        }),
    ),
    "opencode": CapabilityManifest(
        "opencode", frozenset({"1"}),
        frozenset({
            Capability.SESSION_LIFECYCLE, Capability.PROMPT, Capability.TOOL_CALL,
            Capability.COMMAND, Capability.FILE_CHANGE,
        }),
    ),
}

_ADAPTERS: Mapping[str, ObservationAdapter] = {
    "claude-code": CLAUDE_ADAPTER,
    "codex": CODEX_ADAPTER,
    "opencode": OPENCODE_ADAPTER,
}


@dataclass(frozen=True, slots=True)
class ProviderCapabilityEntry:
    provider: str
    adapter_version: str
    health: HealthReport
    implemented: frozenset[Capability]
    currently_confirmed: frozenset[Capability]
    unconfirmed_by_research: frozenset[Capability]


def build_capability_matrix(*, provider_versions: Mapping[str, str | None]) -> tuple[ProviderCapabilityEntry, ...]:
    """One `drift.probe()` call per adapter against its current manifest.

    `provider_versions` maps provider name -> the actual installed/detected
    provider version (or None if unknown/unavailable). This module makes no
    attempt to detect it itself, consistent with adapters never launching or
    introspecting a provider — the caller supplies real, observed evidence.
    """
    entries: list[ProviderCapabilityEntry] = []
    for provider, adapter in _ADAPTERS.items():
        manifest = CURRENT_PROVIDER_MANIFESTS[provider]
        health = probe(adapter, manifest, provider_version=provider_versions.get(provider))
        entries.append(ProviderCapabilityEntry(
            provider=provider,
            adapter_version=adapter.version,
            health=health,
            implemented=adapter.capabilities,
            currently_confirmed=manifest.capabilities,
            unconfirmed_by_research=adapter.capabilities - manifest.capabilities,
        ))
    return tuple(entries)
