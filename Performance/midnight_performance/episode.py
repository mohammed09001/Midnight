"""Rebuildable, non-authoritative episode projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import EntityKind, Identity, Observation


@dataclass(frozen=True, slots=True)
class Episode:
    identity: Identity
    observations: tuple[Observation, ...]

    @property
    def evidence_kinds(self) -> frozenset[EntityKind]:
        return frozenset(item.identity.kind for item in self.observations)


class EpisodeProjector:
    """Groups explicit episode links only; it never fabricates correlation."""

    def rebuild(self, observations: Iterable[Observation]) -> dict[Identity, Episode]:
        grouped: dict[Identity, list[Observation]] = {}
        for observation in observations:
            if observation.episode is not None:
                grouped.setdefault(observation.episode, []).append(observation)
        return {
            identity: Episode(identity, tuple(sorted(items, key=lambda item: item.observed_at)))
            for identity, items in grouped.items()
        }
