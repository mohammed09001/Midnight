"""Read/write Desktop bridge for Midnight Repo Intelligent's terminal card.

Mirrors ``desktop_bridge.py``'s/``graph_bridge.py``'s CLI conventions
exactly: a bounded, versioned JSON document on stdout, self-validated
against its schema before being printed, and a distinct exit code for an
honest "invalid request" failure (never a raw crash, never a partial or
fabricated document on stdout).

``decide_terminal_card`` is deliberately single-candidate (Repo
Intelligent's Attention Budget principle): this bridge always resolves to
at most ONE current insight for a project, never a list.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .contract_schema import validate_project_insight_feedback_response, validate_project_insight_response
from .desktop_bridge import open_project_ledger, project_identity
from .query_api import PerformanceQueryAPI
from .repo_intelligence.authorization import RepoIntelligenceAuthorization
from .repo_intelligence.contracts import Exposure, ExposureOutcome, ProjectInsight
from .repo_intelligence.terminal_learning import TerminalCandidate
from .repo_intelligence_adapters import production_providers
from .repo_intelligence_pipeline import record_feedback, run_pipeline
from .repo_intelligence_store import RepoIntelligenceStore

BRIDGE_VERSION = 1
DEFAULT_PROJECT_KEY = "midnight"

EXIT_NOT_FOUND = 2
EXIT_INVALID_REQUEST = 4


def _insight_document(insight: ProjectInsight, candidate: TerminalCandidate, exposure: Exposure, outcome: ExposureOutcome | None) -> dict:
    return {
        "identity": insight.identity.canonical,
        "exposureId": exposure.identity.canonical,
        "statement": insight.statement,
        "claimKind": insight.claim_kind.value,
        "confidence": insight.confidence,
        "uncertainty": insight.uncertainty,
        "whyNow": candidate.why_now,
        "projectConnection": candidate.project_connection,
        "nextLearningAction": candidate.next_learning_action,
        "externalConnection": candidate.external_connection,
        "evidenceBundle": insight.evidence_bundle.canonical,
        "lineageReceipt": insight.lineage_receipt.canonical if insight.lineage_receipt else None,
        "channel": exposure.channel.value,
        "outcome": (outcome or exposure.outcome).value,
    }


def get_terminal_card(
    data_dir: Path,
    project_key: str,
    repo_root: Path,
    *,
    user_pull: bool = False,
    now: datetime | None = None,
) -> dict:
    """Run one bounded pipeline pass and render its current terminal card, if any."""
    moment = now if now is not None else datetime.now(timezone.utc)
    project = project_identity(project_key)
    ledger = open_project_ledger(data_dir / "evidence.jsonl", project_key)
    api = PerformanceQueryAPI(ledger)
    store = RepoIntelligenceStore.open_for_project(data_dir, project)
    try:
        authorization = RepoIntelligenceAuthorization(project=project, external_access=False, model_access=False)
        providers = production_providers(
            project=project, query_api=api, store=store, repository_key=project_key, repo_root=repo_root
        )
        result = run_pipeline(
            project, project_key, repo_root, providers, authorization, store, now=moment, user_pull=user_pull
        )
        if result.decision is None or result.decision.card is None or result.decision_candidate is None:
            reason = (
                result.decision.reason
                if result.decision is not None
                else "no signals crossed the learning-pressure threshold yet"
            )
            document = {
                "version": BRIDGE_VERSION, "project": project.canonical, "generatedAt": moment.isoformat(),
                "card": None, "reason": reason, "insight": None,
            }
        else:
            insight = next(
                (i for i in store.list_insights(project) if i.identity == result.decision.exposure.insight), None
            )
            if insight is None:
                document = {
                    "version": BRIDGE_VERSION, "project": project.canonical, "generatedAt": moment.isoformat(),
                    "card": None, "reason": "selected insight could not be re-read from the store", "insight": None,
                }
            else:
                feedback = store.get_exposure_feedback(project, result.decision.exposure.identity.canonical)
                document = {
                    "version": BRIDGE_VERSION, "project": project.canonical, "generatedAt": moment.isoformat(),
                    "card": result.decision.card, "reason": result.decision.reason,
                    "insight": _insight_document(insight, result.decision_candidate, result.decision.exposure, feedback),
                }
        validate_project_insight_response(document)
        return document
    finally:
        store.close()


def record_insight_feedback(
    data_dir: Path,
    project_key: str,
    exposure_id: str,
    outcome: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Record open/save/dismiss feedback on one previously-exposed insight."""
    moment = now if now is not None else datetime.now(timezone.utc)
    try:
        outcome_enum = ExposureOutcome(outcome)
    except ValueError as exc:
        raise ValueError(f"'{outcome}' is not a valid outcome") from exc
    if outcome_enum not in (ExposureOutcome.OPENED, ExposureOutcome.SAVED, ExposureOutcome.DISMISSED):
        raise ValueError(f"'{outcome}' is not a recordable feedback outcome")
    project = project_identity(project_key)
    store = RepoIntelligenceStore.open_for_project(data_dir, project)
    try:
        authorization = RepoIntelligenceAuthorization(project=project)
        record_feedback(store, project, authorization, exposure_id, outcome_enum, now=moment)
        document = {
            "version": BRIDGE_VERSION, "project": project.canonical, "recorded": True, "outcome": outcome_enum.value,
        }
        validate_project_insight_feedback_response(document)
        return document
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repo Intelligent's terminal insight card / feedback bridge for Midnight Desktop (stdout JSON).",
    )
    parser.add_argument("--data-dir", type=Path, required=True, help="project ledger/state directory")
    parser.add_argument("--project", default=DEFAULT_PROJECT_KEY, help="local project key (deterministic identity input)")
    parser.add_argument("--repo-root", type=Path, default=None, help="repository root to scan (defaults to the parent of this package's cwd)")
    parser.add_argument("--user-pull", action="store_true", help="a deliberate user visit outranks a proactive push")
    parser.add_argument("--record-feedback", action="store_true", help="record feedback instead of reading the current card")
    parser.add_argument("--exposure-id", default=None, help="the exposure identity to record feedback against")
    parser.add_argument("--outcome", default=None, help="one of opened, saved, dismissed")
    args = parser.parse_args(argv)
    repo_root = args.repo_root if args.repo_root is not None else Path.cwd().parent

    if args.record_feedback:
        if not args.exposure_id or not args.outcome:
            json.dump({"error": "invalid_request", "message": "--record-feedback requires --exposure-id and --outcome"}, sys.stderr)
            sys.stderr.write("\n")
            return EXIT_INVALID_REQUEST
        try:
            document = record_insight_feedback(args.data_dir, args.project, args.exposure_id, args.outcome)
        except KeyError as exc:
            # An unknown exposure id is a "resource doesn't exist" outcome, not a
            # malformed-request one -- mirrors graph_bridge.py's NOT_FOUND convention
            # for an unknown canonical identity, distinct from EXIT_INVALID_REQUEST.
            json.dump({"error": "not_found", "message": str(exc)}, sys.stderr)
            sys.stderr.write("\n")
            return EXIT_NOT_FOUND
        except ValueError as exc:
            json.dump({"error": "invalid_request", "message": str(exc)}, sys.stderr)
            sys.stderr.write("\n")
            return EXIT_INVALID_REQUEST
        json.dump(document, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    document = get_terminal_card(args.data_dir, args.project, repo_root, user_pull=args.user_pull)
    json.dump(document, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
