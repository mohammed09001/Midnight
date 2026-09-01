"""Local neighborhoods around a current Prompt Run or draft prompt, bucketed by outcome; evidence for later analytics, never a recommendation itself."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from .contracts import ClaimKind
from .feedback import FeedbackReason, FeedbackRecord, Judgment
from .similarity import Experience, SimilarityMatch, match

_METHOD = "experience-neighborhood"
_VERSION = "1"
BUCKETS: tuple[str, ...] = ("successful", "partial", "failed", "regressed", "uncertain")
_JUDGMENT_BUCKET: dict[Judgment, str] = {
    Judgment.ACHIEVED: "successful", Judgment.PARTIAL: "partial",
    Judgment.NOT_ACHIEVED: "failed", Judgment.UNCERTAIN: "uncertain",
}


@dataclass(frozen=True, slots=True)
class NeighborhoodMember:
    match: SimilarityMatch
    bucket: str

    def __post_init__(self):
        if self.bucket not in BUCKETS: raise ValueError(f"bucket must be one of {BUCKETS}")


@dataclass(frozen=True, slots=True)
class Neighborhood:
    query_prompt_run_id: str; members: tuple[NeighborhoodMember, ...]
    method: str; method_version: str; claim_kind: ClaimKind; uncertainty: str
    gaps: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.query_prompt_run_id.strip(): raise ValueError("neighborhood requires the query prompt run id")

    def bucket(self, name: str) -> tuple[NeighborhoodMember, ...]:
        if name not in BUCKETS: raise ValueError(f"bucket must be one of {BUCKETS}")
        return tuple(item for item in self.members if item.bucket == name)


def _bucket_for(feedback: tuple[FeedbackRecord, ...]) -> str:
    """Regression is reported as its own bucket regardless of the accompanying judgment; missing feedback is uncertain, never success."""
    if any(FeedbackReason.REGRESSION in record.reasons for record in feedback):
        return "regressed"
    if not feedback:
        return "uncertain"
    latest = max(feedback, key=lambda record: record.submitted_at)
    return _JUDGMENT_BUCKET[latest.judgment]


def build_neighborhood(query: Experience, candidates: tuple[Experience, ...], *, top_k_per_bucket: int = 5, min_score: float = 0.0, weights: Mapping[str, float] | None = None) -> Neighborhood:
    """Rank candidates with the same multi-view retrieval used elsewhere, then bucket by outcome; each bucket is capped independently so a common outcome cannot crowd out a rare one."""
    if top_k_per_bucket < 1:
        raise ValueError("top_k_per_bucket must be positive")
    if not 0 <= min_score <= 1:
        raise ValueError("min_score must be between zero and one")
    by_id = {item.prompt_run_id: item for item in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("candidate experiences must have unique prompt run ids")
    omitted_self = tuple(item.prompt_run_id for item in candidates if item.prompt_run_id == query.prompt_run_id)
    scored = sorted(
        (item for item in (match(query, candidate, weights=weights) for candidate in candidates if candidate.prompt_run_id != query.prompt_run_id) if item.score is not None and item.score >= min_score),
        key=lambda item: (-item.score, item.prompt_run_id),
    )
    counts = {bucket: 0 for bucket in BUCKETS}
    members: list[NeighborhoodMember] = []
    for item in scored:
        bucket = _bucket_for(by_id[item.prompt_run_id].feedback)
        if counts[bucket] >= top_k_per_bucket:
            continue
        counts[bucket] += 1
        members.append(NeighborhoodMember(item, bucket))
    parts = ["ranking reuses the same multi-view retrieval as experience matching; bucketing by outcome is a rebuildable projection, not a causal recommendation"]
    empty = tuple(bucket for bucket in BUCKETS if counts[bucket] == 0)
    if empty:
        parts.append(f"no qualifying neighbors in: {list(empty)}")
    gaps = tuple(f"excluded:self_candidate:{item}" for item in omitted_self)
    return Neighborhood(query.prompt_run_id, tuple(members), _METHOD, _VERSION, ClaimKind.DERIVED, "; ".join(parts), gaps)
