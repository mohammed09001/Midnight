"""MCP-shaped and host-native read tools over :mod:`query_api`.

These are interaction tools only.  They do not install hooks, observe agents,
or modify prompts; native capture remains the responsibility of adapters.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Callable, Mapping

from .analysis import AnalysisDescriptor
from .contracts import ClaimKind, EntityKind, Identity
from .interaction_policy import ActiveSurface, InteractionPolicy
from .query_api import PerformanceQueryAPI, QueryAuthorization


class PerformanceReadTools:
    """Host object with MCP-compatible definitions and bounded dispatch."""

    def __init__(self, api: PerformanceQueryAPI, authorization: QueryAuthorization, *, analyzers: Mapping[str, Callable] = (), interaction_policy: InteractionPolicy = InteractionPolicy()) -> None:
        self.api = api
        self.authorization = authorization
        self._analyzers = dict(analyzers)
        self._interaction_policy = interaction_policy

    def definitions(self) -> tuple[Mapping[str, object], ...]:
        return (
            {"name": "performance.list_resources", "description": "List the stable Performance query resource vocabulary.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "performance.query_evidence", "description": "Read bounded, project-authorized Performance evidence.", "inputSchema": {"type": "object", "properties": {"kinds": {"type": "array", "items": {"type": "string"}}, "subject": {"type": "string"}, "claim_kinds": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}}},
            {"name": "performance.get_episodes", "description": "Read explicit, rebuildable episode correlations.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}}},
            {"name": "performance.read_projection", "description": "Read a qualified Performance projection such as memory, similarity, relationships, metrics, datasets, experiments, models, or recommendations.", "inputSchema": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}},
            {"name": "performance.request_analysis", "description": "Explicitly request a registered, pure analysis; it does not capture or alter an agent session.", "inputSchema": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}},
        )

    def invoke(self, name: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
        self._interaction_policy.authorize_active(ActiveSurface.MCP_HOST, explicitly_invoked=True)
        if name == "performance.list_resources":
            return {"api_version": 1, "resources": _plain(self.api.resources(self.authorization))}
        if name == "performance.query_evidence":
            kinds = arguments.get("kinds")
            claim_kinds = arguments.get("claim_kinds")
            subject = arguments.get("subject")
            page = self.api.query_evidence(
                self.authorization,
                kinds=frozenset(EntityKind(value) for value in kinds) if kinds is not None else None,
                subject=Identity.parse(subject) if isinstance(subject, str) else None,
                claim_kinds=frozenset(ClaimKind(value) for value in claim_kinds) if claim_kinds is not None else None,
                limit=int(arguments.get("limit", 50)),
            )
            return _plain(page)
        if name == "performance.get_episodes":
            return {"api_version": 1, "items": _plain(self.api.episodes(self.authorization, limit=int(arguments.get("limit", 50))))}
        if name == "performance.read_projection":
            projection = self.api.projection(self.authorization, _required_name(arguments))
            return _plain(projection)
        if name == "performance.request_analysis":
            analysis_name = _required_name(arguments)
            try:
                analyzer = self._analyzers[analysis_name]
            except KeyError as exc:
                raise KeyError(f"unknown registered analysis: {analysis_name}") from exc
            result = self.api.request_analysis(self.authorization, AnalysisDescriptor(analysis_name, "1", "host-request", {}), analyzer)
            return _plain(result)
        raise KeyError(f"unknown Performance read tool: {name}")


def _required_name(arguments: Mapping[str, object]) -> str:
    value = arguments.get("name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tool argument 'name' is required")
    return value


def _plain(value: object) -> object:
    if isinstance(value, Identity):
        return value.canonical
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset)):
        return [_plain(item) for item in value]
    if hasattr(value, "hex") and value.__class__.__name__ == "UUID":
        return str(value)
    return value
