"""Versioned, replaceable embedding provider; vector distance is retrieval evidence, never truth, and never crosses privacy policy unexamined."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Callable, Sequence
from .privacy import ContentCategory, PrivacyPolicy, PrivacyViolation

_METHOD = "semantic-similarity"
_VERSION = "1"


@dataclass(frozen=True, slots=True)
class EmbeddingProvider:
    """A pluggable embedding backend; name and version travel with every vector it produces."""
    name: str; version: str; embed: Callable[[str], Sequence[float]]

    def __post_init__(self):
        if not self.name.strip() or not self.version.strip(): raise ValueError("embedding provider requires a name and version")


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    provider: str; provider_version: str; values: tuple[float, ...]

    def __post_init__(self):
        if not self.provider.strip() or not self.provider_version.strip(): raise ValueError("embedding requires a provider name and version")
        if not self.values: raise ValueError("embedding requires at least one dimension")
        if any(not isfinite(value) for value in self.values): raise ValueError("embedding values must be finite")


def embed_text(provider: EmbeddingProvider, policy: PrivacyPolicy, category: ContentCategory, text: str) -> EmbeddingVector:
    """Embed text only after the privacy policy allows its content category; the provider itself may be swapped freely."""
    if not policy.allows(category):
        raise PrivacyViolation(f"privacy policy does not allow embedding content category {category.value}")
    if not text.strip():
        raise ValueError("embedding requires non-empty text")
    values = tuple(float(value) for value in provider.embed(text))
    return EmbeddingVector(provider.name, provider.version, values)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float | None:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a, norm_b = sqrt(sum(x * x for x in a)), sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return None
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def embedding_similarity(a: EmbeddingVector | None, b: EmbeddingVector | None) -> tuple[float | None, tuple[str, ...]]:
    """Cosine similarity rescaled to [0, 1]; embeddings from different providers/versions are incommensurable and never compared."""
    if a is None or b is None:
        return None, ()
    if a.provider != b.provider or a.provider_version != b.provider_version:
        return None, (f"incommensurable providers: {a.provider}/{a.provider_version} vs {b.provider}/{b.provider_version}",)
    if len(a.values) != len(b.values):
        return None, (f"dimension mismatch: {len(a.values)} vs {len(b.values)}",)
    cosine = _cosine(a.values, b.values)
    if cosine is None:
        return None, ("zero-magnitude embedding",)
    return round((cosine + 1) / 2, 3), (f"{a.provider}/{a.provider_version} cosine={round(cosine, 3)}",)
