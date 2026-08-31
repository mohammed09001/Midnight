"""Evidence authenticity helpers over versioned observation envelopes."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from .observation_model import ObservationEnvelope


def seal(envelope: ObservationEnvelope, *, signer: str | None = None) -> ObservationEnvelope:
    """Attach a checksum over the envelope excluding its checksum field.

    A checksum detects tampering after capture; it is not a substitute for an
    externally verified cryptographic signature.
    """
    if signer is not None and not signer.strip():
        raise ValueError("signer must be non-empty when supplied")
    unsigned = replace(envelope, integrity_checksum=None, signer=signer)
    return replace(unsigned, integrity_checksum=_digest(unsigned))


def verify(envelope: ObservationEnvelope) -> bool | None:
    """Return None when an envelope was not sealed, otherwise verify its checksum."""
    if envelope.integrity_checksum is None:
        return None
    return envelope.integrity_checksum == _digest(replace(envelope, integrity_checksum=None))


def repository_claim_contradictions(claimed_paths: tuple[str, ...], final_paths: tuple[str, ...]) -> tuple[str, ...]:
    """Report agent-native edit claims absent from the final repository evidence."""
    final = frozenset(final_paths)
    return tuple(sorted(path for path in claimed_paths if path not in final))


def _digest(envelope: ObservationEnvelope) -> str:
    payload = envelope.to_dict()
    payload["integrity_checksum"] = None
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
