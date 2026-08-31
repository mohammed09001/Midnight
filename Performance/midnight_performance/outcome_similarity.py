"""Cross-domain outcome pattern overlap across the optional sibling domains; categorical, never causal, and never a substitute for each association's own identity."""
from __future__ import annotations
from .associations import OutcomeAssociation

_METHOD = "cross-domain-outcome-similarity"
_VERSION = "1"


def _jaccard(a: frozenset, b: frozenset) -> float | None:
    union = a | b
    return round(len(a & b) / len(union), 3) if union else None


def _signature(association: OutcomeAssociation) -> str:
    return f"{association.outcome.provider.value}:{association.kind.value}:{association.outcome.kind}"


def cross_domain_outcome_similarity(a: tuple[OutcomeAssociation, ...], b: tuple[OutcomeAssociation, ...]) -> tuple[float | None, tuple[str, ...]]:
    """Overlap of (sibling domain, association kind, outcome kind) dimensions; each association's own external_id/provenance stays on the Experience untouched.

    Matching on the categorical dimension, not on `OutcomeReference.external_id`, is deliberate: two different
    prompt runs practically never share the identical Watch Runtime/Data/Security event id, so exact-id matching
    would always score zero and defeat the purpose of cross-domain pattern retrieval.
    """
    signatures_a = frozenset(_signature(item) for item in a)
    signatures_b = frozenset(_signature(item) for item in b)
    if not signatures_a or not signatures_b:
        return None, ()
    return _jaccard(signatures_a, signatures_b), tuple(sorted(signatures_a & signatures_b))
