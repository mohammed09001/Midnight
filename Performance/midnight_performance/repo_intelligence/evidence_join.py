"""Join repository entity references to Performance evidence.

The join consumes ``ObservationEnvelope`` streams exactly as
``EvidenceLedger.replay()`` yields them — Performance remains the
canonical owner of the evidence; this layer only correlates.  Payload
shapes are read defensively: today's durably-wired capture is Prompt Run
occurrence (empty payload), and repository-change observations carry
``files`` path lists.  Anything that cannot be attributed to an entity is
reported as an honest gap, never reconstructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..contracts import EntityKind
from ..observation_model import ObservationEnvelope, ObservationType
from .authorization import CrossProjectAccessError


_EVENT_CHANGE = "change"
_EVENT_VERIFICATION = "verification"
_EVENT_INTENT = "intent"
_EVENT_FEEDBACK = "feedback"
_EVENT_OUTCOME = "outcome"

_PASSING_OUTCOMES = frozenset({"passed", "pass", "success", "ok", "green"})
_FAILING_OUTCOMES = frozenset({"failed", "fail", "error", "red"})


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    """One Performance evidence point attributed to a repository path."""

    path: str
    observed_at: datetime
    event_kind: str
    observation_canonical: str
    observation_type: str
    passed: bool | None
    episode: str | None
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("evidence events must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EpisodeIntent:
    """A Prompt Run occurrence correlated to entity paths via a shared episode."""

    episode: str
    prompt_run_canonical: str
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoChange:
    """One change observation touching more than one entity."""

    observation_canonical: str
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JoinedEvidence:
    """Deterministic per-path evidence timeline over a bounded window."""

    project: object
    window_start: datetime
    window_end: datetime
    timelines: dict[str, tuple[EvidenceEvent, ...]]
    co_changes: tuple[CoChange, ...]
    episode_intents: tuple[EpisodeIntent, ...]
    gaps: tuple[str, ...]


def _payload_entries(payload) -> dict[str, tuple[str, ...]]:
    """Map each touched path to the payload roles it appeared under."""
    entries: dict[str, set[str]] = {}
    for key in ("files", "paths", "created", "modified", "deleted"):
        value = payload.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                clean = str(item).replace("\\", "/").lstrip("/")
                if clean.strip():
                    entries.setdefault(clean, set()).add(key)
    renamed = payload.get("renamed")
    if isinstance(renamed, (list, tuple)):
        for item in renamed:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                for role, part in (("renamed_from", item[0]), ("renamed_to", item[1])):
                    clean = str(part).replace("\\", "/").lstrip("/")
                    if clean.strip():
                        entries.setdefault(clean, set()).add(role)
            elif isinstance(item, str):
                clean = item.replace("\\", "/").lstrip("/")
                if clean.strip():
                    entries.setdefault(clean, set()).add("renamed")
    single = payload.get("path")
    if isinstance(single, str):
        clean = single.replace("\\", "/").lstrip("/")
        if clean.strip():
            entries.setdefault(clean, set()).add("path")
    return {path: tuple(sorted(roles)) for path, roles in entries.items()}


def _payload_paths(payload) -> tuple[str, ...]:
    return tuple(sorted(_payload_entries(payload)))


def _payload_passed(payload) -> bool | None:
    if "passed" in payload and isinstance(payload["passed"], bool):
        return payload["passed"]
    for key in ("outcome", "status", "result"):
        value = payload.get(key)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _PASSING_OUTCOMES:
                return True
            if lowered in _FAILING_OUTCOMES:
                return False
    return None


def _change_paths(observation) -> tuple[str, ...]:
    return _payload_paths(observation.payload)


def join_evidence(
    envelopes,
    project,
    *,
    window_start: datetime,
    window_end: datetime,
) -> JoinedEvidence:
    """Correlate a Performance evidence stream to per-path entity timelines.

    Deterministic: events are sorted by ``(observed_at, observation)``.
    Cross-project envelopes fail closed.  Prompt Run occurrences carry no
    paths; they attribute to entities only through a shared episode with a
    change observation.  Verification events attribute through payload
    paths, shared episodes, or the verified subject when it is a change
    identity known to the stream.
    """
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("join windows must be timezone-aware")
    if window_start > window_end:
        raise ValueError("window_start must not be after window_end")

    events: dict[str, list[EvidenceEvent]] = {}
    co_changes: list[CoChange] = []
    gaps: list[str] = []
    in_window: list[ObservationEnvelope] = []
    paths_by_episode: dict[str, set[str]] = {}
    prompt_runs_by_episode: dict[str, list[tuple[str, datetime]]] = {}
    change_paths_by_id: dict[str, tuple[str, ...]] = {}

    for envelope in envelopes:
        if envelope.project != project:
            raise CrossProjectAccessError(
                "cross-project evidence reached the join layer; failing closed"
            )
        if not (window_start <= envelope.observation.observed_at <= window_end):
            continue
        in_window.append(envelope)
        if envelope.observation.episode is not None and envelope.observation_type in (
            ObservationType.REPOSITORY_CHANGE,
            ObservationType.FILE_EDIT,
        ):
            paths = _change_paths(envelope.observation)
            if paths:
                paths_by_episode.setdefault(envelope.observation.episode.canonical, set()).update(paths)

    for envelope in sorted(in_window, key=lambda e: (e.observation.observed_at, e.observation.identity.canonical)):
        observation = envelope.observation
        canonical = observation.identity.canonical
        observed_at = observation.observed_at
        episode = observation.episode.canonical if observation.episode is not None else None
        obs_type = envelope.observation_type

        if obs_type in (ObservationType.REPOSITORY_CHANGE, ObservationType.FILE_EDIT):
            paths = _change_paths(observation)
            if not paths:
                gaps.append(f"repository change evidence without attributable paths: {canonical}")
                continue
            if len(paths) > 1:
                co_changes.append(
                    CoChange(observation_canonical=canonical, paths=tuple(sorted(set(paths))))
                )
            path_roles = _payload_entries(observation.payload)
            change_paths_by_id[canonical] = tuple(sorted(path_roles))
            for path, roles in sorted(path_roles.items()):
                events.setdefault(path, []).append(
                    EvidenceEvent(
                        path=path,
                        observed_at=observed_at,
                        event_kind=_EVENT_CHANGE,
                        observation_canonical=canonical,
                        observation_type=obs_type.value,
                        passed=None,
                        episode=episode,
                        roles=roles,
                    )
                )
        elif obs_type is ObservationType.VERIFICATION:
            paths = _payload_paths(observation.payload)
            if not paths and observation.subject.kind is EntityKind.CHANGE_SET:
                paths = change_paths_by_id.get(canonical, ())
            if not paths and episode is not None:
                paths = tuple(sorted(paths_by_episode.get(episode, set())))
            passed = _payload_passed(observation.payload)
            if not paths:
                gaps.append(f"verification evidence without entity attribution: {canonical}")
                continue
            for path in sorted(set(paths)):
                events.setdefault(path, []).append(
                    EvidenceEvent(
                        path=path,
                        observed_at=observed_at,
                        event_kind=_EVENT_VERIFICATION,
                        observation_canonical=canonical,
                        observation_type=obs_type.value,
                        passed=passed,
                        episode=episode,
                    )
                )
        elif obs_type is ObservationType.FEEDBACK:
            paths = _payload_paths(observation.payload)
            if not paths and episode is not None:
                paths = tuple(sorted(paths_by_episode.get(episode, set())))
            if not paths:
                gaps.append(f"feedback evidence without entity attribution: {canonical}")
                continue
            for path in sorted(set(paths)):
                events.setdefault(path, []).append(
                    EvidenceEvent(
                        path=path,
                        observed_at=observed_at,
                        event_kind=_EVENT_FEEDBACK,
                        observation_canonical=canonical,
                        observation_type=obs_type.value,
                        passed=None,
                        episode=episode,
                    )
                )
        elif obs_type is ObservationType.EXTERNAL_OUTCOME:
            paths = _payload_paths(observation.payload)
            if not paths and episode is not None:
                paths = tuple(sorted(paths_by_episode.get(episode, set())))
            if not paths:
                gaps.append(f"outcome evidence without entity attribution: {canonical}")
                continue
            for path in sorted(set(paths)):
                events.setdefault(path, []).append(
                    EvidenceEvent(
                        path=path,
                        observed_at=observed_at,
                        event_kind=_EVENT_OUTCOME,
                        observation_canonical=canonical,
                        observation_type=obs_type.value,
                        passed=_payload_passed(observation.payload),
                        episode=episode,
                    )
                )
        elif obs_type is ObservationType.PROMPT:
            if episode is None:
                gaps.append(
                    f"prompt run occurrence without episode correlation cannot be "
                    f"attributed to entities: {canonical}"
                )
                continue
            prompt_runs_by_episode.setdefault(episode, []).append((canonical, observed_at))

    for episode, prompt_runs in prompt_runs_by_episode.items():
        paths = tuple(sorted(paths_by_episode.get(episode, set())))
        if not paths:
            gaps.append(
                f"episode {episode} has prompt runs but no change evidence to attribute them to"
            )
            continue
        for prompt_run_canonical, prompt_observed_at in sorted(prompt_runs):
            for path in paths:
                events.setdefault(path, []).append(
                    EvidenceEvent(
                        path=path,
                        observed_at=prompt_observed_at,
                        event_kind=_EVENT_INTENT,
                        observation_canonical=prompt_run_canonical,
                        observation_type=ObservationType.PROMPT.value,
                        passed=None,
                        episode=episode,
                    )
                )

    timelines = {
        path: tuple(sorted(event_list, key=lambda e: (e.observed_at, e.observation_canonical)))
        for path, event_list in sorted(events.items())
    }
    episode_intents = tuple(
        EpisodeIntent(
            episode=episode,
            prompt_run_canonical=sorted(prompt_runs)[0][0],
            paths=tuple(sorted(paths_by_episode.get(episode, set()))),
        )
        for episode, prompt_runs in sorted(prompt_runs_by_episode.items())
        if paths_by_episode.get(episode)
    )
    return JoinedEvidence(
        project=project,
        window_start=window_start,
        window_end=window_end,
        timelines=timelines,
        co_changes=tuple(sorted(co_changes, key=lambda c: (c.observation_canonical, c.paths))),
        episode_intents=episode_intents,
        gaps=tuple(sorted(set(gaps))),
    )


__all__ = [
    "CoChange",
    "EpisodeIntent",
    "EvidenceEvent",
    "JoinedEvidence",
    "join_evidence",
]
