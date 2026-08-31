"""Threat catalogue and bounded untrusted-input guard for Performance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Threat(str, Enum):
    MALICIOUS_REPOSITORY_CONTENT = "malicious_repository_content"
    PROMPT_INJECTION = "prompt_injection"
    POISONED_AGENT_EVENT = "poisoned_agent_event"
    FORGED_HOOK_PAYLOAD = "forged_hook_payload"
    TRANSCRIPT_TAMPERING = "transcript_tampering"
    COMPROMISED_ADAPTER_CONFIG = "compromised_adapter_configuration"
    CROSS_PROJECT_LEAKAGE = "cross_project_leakage"
    SECRET_EXPOSURE = "secret_exposure"
    MALICIOUS_DIFF = "malicious_diff"
    OVERSIZED_OUTPUT = "oversized_output"
    EVALUATOR_POISONING = "evaluator_poisoning"
    DATASET_MODEL_POISONING = "dataset_model_poisoning"
    UNSAFE_MCP_AI_CONSUMPTION = "unsafe_mcp_ai_consumption"
    EVENT_STREAM_DENIAL_OF_SERVICE = "event_stream_denial_of_service"


@dataclass(frozen=True, slots=True)
class ThreatControl:
    threat: Threat
    control: str
    residual_risk: str


def threat_model() -> tuple[ThreatControl, ...]:
    """Controls map to existing boundaries; this is not an authority grant to hooks."""
    controls = {
        Threat.MALICIOUS_REPOSITORY_CONTENT: ("treat repository text as untrusted evidence", "content may still be retained when privacy policy allows"),
        Threat.PROMPT_INJECTION: ("never execute or follow captured content as instructions", "downstream consumer must preserve untrusted boundary"),
        Threat.POISONED_AGENT_EVENT: ("typed envelopes and provenance qualification", "provider payload truth remains unverified"),
        Threat.FORGED_HOOK_PAYLOAD: ("checksum/source sequence where supplied", "no signature verification without external keys"),
        Threat.TRANSCRIPT_TAMPERING: ("transcript privacy gating and optional integrity checksum", "unsealed transcripts are unverifiable"),
        Threat.COMPROMISED_ADAPTER_CONFIG: ("adapter forbids launch/provider-auth orchestration", "host configuration trust is external"),
        Threat.CROSS_PROJECT_LEAKAGE: ("ledger/query/tenant scope checks", "caller must bind every projection"),
        Threat.SECRET_EXPOSURE: ("privacy redaction and credential references", "pattern redaction is not complete secret detection"),
        Threat.MALICIOUS_DIFF: ("diff remains untrusted content", "reviewer must not execute it"),
        Threat.OVERSIZED_OUTPUT: ("bounded untrusted-input guard and bounded queries", "host transport limits remain external"),
        Threat.EVALUATOR_POISONING: ("qualified evaluator outputs and privacy gates", "model judgment is advisory"),
        Threat.DATASET_MODEL_POISONING: ("versioned snapshots and quality/readiness gates", "source evidence can still be malicious"),
        Threat.UNSAFE_MCP_AI_CONSUMPTION: ("active authorization and untrusted content boundary", "host tool policy remains external"),
        Threat.EVENT_STREAM_DENIAL_OF_SERVICE: ("bounded derived-work queue", "capture-rate limiting is host-owned"),
    }
    return tuple(ThreatControl(item, *controls[item]) for item in Threat)


def bound_untrusted_text(value: str, *, maximum_bytes: int = 1_000_000) -> str:
    """Reject oversized external text; returns the original text without interpreting it."""
    if maximum_bytes < 1:
        raise ValueError("maximum bytes must be positive")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError("untrusted input exceeds configured byte limit")
    return value
