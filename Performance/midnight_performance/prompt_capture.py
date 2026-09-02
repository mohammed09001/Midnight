"""Performance-owned capture of Prompt Run evidence from coding-agent work.

This is the BYOT write half that keeps the Desktop bridge read-only: a host
(a hook, a script, an operator) supplies one provider event identity per real
prompt occurrence, and this module appends a normalized PROMPT_RUN
observation through the standard policy-gated ledger path.

Privacy through minimum data: the durable payload is empty.  No prompt text,
output, diff, command, or transcript ever passes through here, so the
Activity Map can never leak development content.  Identity is derived
deterministically from ``provider:provider_event_id``, so replaying or
retrying the same event never creates duplicate evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ClaimKind, EntityKind, Observation, deterministic_identity
from .ledger import EvidenceLedger
from .observation_model import EvidenceSourceKind, ObservationEnvelope, ObservationLayer, ObservationType
from .privacy import PrivacyGuard, PrivacyPolicy


def record_prompt_run(
    ledger_path: Path,
    project_key: str,
    provider: str,
    provider_event_id: str,
    *,
    observed_at: datetime | None = None,
) -> tuple[bool, str]:
    """Append one PROMPT_RUN observation; return (appended, canonical id).

    ``observed_at`` defaults to the capture moment and must be timezone-aware
    when supplied — naive timestamps are rejected before anything is written.
    Returns ``False`` when the identical evidence already exists (idempotent
    replay); the ledger, not this module, decides acceptance.
    """
    moment = observed_at if observed_at is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    stable_key = f"{provider}:{provider_event_id}"
    project = deterministic_identity(EntityKind.PROJECT, project_key)
    observation = Observation(
        identity=deterministic_identity(EntityKind.PROMPT_RUN, stable_key),
        claim_kind=ClaimKind.OBSERVED,
        subject=deterministic_identity(EntityKind.PROMPT_VERSION, stable_key),
        payload={},
        observed_at=moment,
        source=provider,
    )
    envelope = ObservationEnvelope(
        observation=observation,
        project=project,
        observation_type=ObservationType.PROMPT,
        layer=ObservationLayer.NORMALIZED,
        provider=provider,
        provider_event_id=provider_event_id,
        source_kind=EvidenceSourceKind.PROVIDER_HOOK,
    )
    ledger = EvidenceLedger(ledger_path, project, PrivacyGuard(PrivacyPolicy()))
    return ledger.append(envelope), observation.identity.canonical


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record one real Prompt Run occurrence into the project evidence ledger.",
    )
    parser.add_argument("--data-dir", type=Path, required=True, help="project ledger directory containing evidence.jsonl")
    parser.add_argument("--project", default="midnight", help="local project key (deterministic identity input)")
    parser.add_argument("--provider", required=True, help="coding-harness provider name (e.g. claude-code, opencode)")
    parser.add_argument("--event-id", required=True, help="provider-unique event id; retries map to the same evidence")
    parser.add_argument("--observed-at", default=None, help="timezone-aware ISO 8601 instant; defaults to now")
    args = parser.parse_args(argv)
    moment = datetime.fromisoformat(args.observed_at) if args.observed_at else None
    appended, canonical = record_prompt_run(
        args.data_dir / "evidence.jsonl",
        args.project,
        args.provider,
        args.event_id,
        observed_at=moment,
    )
    json.dump({"recorded": appended, "promptRunId": canonical}, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
