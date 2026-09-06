"""Repo Intelligent's own derived-state store: a project-scoped SQLite file.

Ownership invariant (see the Execution 12 plan and ``repo_intelligence``'s
own module docstrings): Repo Intelligent owns only its derived
project-intelligence state -- graph projections, research jobs, relevance
scores, synthesis artifacts, cost ledger rows, and **user exposure
history** -- never a second copy of Performance evidence or Memory's
durable knowledge. This module never opens Performance's ``evidence.jsonl``/
``projection.sqlite3`` or Memory's own storage; every record it holds is
either (a) a rebuildable cache of a pure local computation (signals,
questions, lineage receipts, graph links -- rerunning the pipeline against
the same Performance evidence reproduces them byte-for-byte), or (b) real
event history Repo Intelligent is the durable owner of by design (exposures,
their feedback outcomes, and later learning-outcome associations).

The file lives at ``repo_intelligence.authorization.project_state_dir(data_dir,
project) / "state.sqlite3"`` -- a project-isolated path, never shared across
projects (:func:`project_state_dir` embeds the project identity in the path
itself, so cross-project collisions fail closed at the filesystem level).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .contracts import Identity
from .ledger import _cross_process_lock
from .repo_intelligence.authorization import project_state_dir
from .repo_intelligence.contracts import (
    AnalogyRecord,
    CostRecord,
    Exposure,
    ExposureOutcome,
    GraphLink,
    InternalAnswerStatus,
    LearnedDecisionRecord,
    LearningOutcome,
    LineageReceipt,
    ProjectInsight,
    ProjectIntelligenceJob,
    QuestionStatus,
    ResearchQuestion,
)
from .repo_intelligence.contracts import InternalSignal
from .repo_intelligence.identities import RepoIdentity

STORE_SCHEMA_VERSION = 1
STORE_FILENAME = "state.sqlite3"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS internal_signals (
    project TEXT NOT NULL, identity TEXT NOT NULL, signal_kind TEXT NOT NULL,
    window_end TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS lineage_receipts (
    project TEXT NOT NULL, identity TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS research_questions (
    project TEXT NOT NULL, identity TEXT NOT NULL, dedup_key TEXT NOT NULL,
    status TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS project_insights (
    project TEXT NOT NULL, identity TEXT NOT NULL, valid_from TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS exposures (
    project TEXT NOT NULL, identity TEXT NOT NULL, insight TEXT NOT NULL,
    occurred_at TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS exposure_feedback (
    project TEXT NOT NULL, exposure TEXT NOT NULL, outcome TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (project, exposure)
);
CREATE TABLE IF NOT EXISTS learning_outcomes (
    project TEXT NOT NULL, identity TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS cost_records (
    project TEXT NOT NULL, identity TEXT NOT NULL, resource TEXT NOT NULL,
    cost_micros INTEGER, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS graph_links (
    project TEXT NOT NULL, identity TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    project TEXT PRIMARY KEY, last_run_at TEXT NOT NULL, window_end TEXT NOT NULL,
    memory_status TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    project TEXT NOT NULL, identity TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS signal_receipts (
    project TEXT NOT NULL, signal_identity TEXT NOT NULL, receipt_identity TEXT NOT NULL,
    PRIMARY KEY (project, signal_identity)
);
CREATE TABLE IF NOT EXISTS question_jobs (
    project TEXT NOT NULL, dedup_key TEXT NOT NULL, job_identity TEXT NOT NULL,
    PRIMARY KEY (project, dedup_key, job_identity)
);
CREATE TABLE IF NOT EXISTS analogy_records (
    project TEXT NOT NULL, identity TEXT NOT NULL, internal_entity_ref TEXT NOT NULL,
    confidence REAL NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS learned_decisions (
    project TEXT NOT NULL, identity TEXT NOT NULL, decision_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, identity)
);
CREATE TABLE IF NOT EXISTS online_learning_events (
    project TEXT NOT NULL, event_id TEXT NOT NULL, decision_id TEXT NOT NULL,
    disposition TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY (project, event_id)
);
CREATE TABLE IF NOT EXISTS online_model_checkpoints (
    project TEXT NOT NULL, decision_type TEXT NOT NULL, checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (project, decision_type)
);
"""


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a store file already existed on disk."""
    try:
        conn.execute("ALTER TABLE pipeline_runs ADD COLUMN memory_status TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    _apply_migrations(conn)
    return conn


class RepoIntelligenceStore:
    """A project-scoped derived-state store; open once per bridge/pipeline invocation."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn = _connect(path)

    @classmethod
    def open_for_project(cls, data_dir: Path, project: Identity) -> "RepoIntelligenceStore":
        return cls(project_state_dir(data_dir, project) / STORE_FILENAME)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with _cross_process_lock(lock_path):
            yield

    # -- signals -----------------------------------------------------
    def upsert_signal(self, signal: InternalSignal) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO internal_signals (project, identity, signal_kind, window_end, document_json) VALUES (?, ?, ?, ?, ?)",
                (signal.project.canonical, signal.identity.canonical, signal.signal_kind,
                 signal.window_end.isoformat(), json.dumps(signal.to_dict())),
            )
            self._conn.commit()

    def list_signals(self, project: Identity) -> tuple[InternalSignal, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM internal_signals WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(InternalSignal.from_dict(json.loads(row[0])) for row in rows)

    # -- lineage receipts ---------------------------------------------
    def upsert_lineage_receipt(self, receipt: LineageReceipt) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO lineage_receipts (project, identity, document_json) VALUES (?, ?, ?)",
                (receipt.project.canonical, receipt.identity.canonical, json.dumps(receipt.to_dict())),
            )
            self._conn.commit()

    def get_lineage_receipt(self, project: Identity, identity_canonical: str) -> LineageReceipt | None:
        row = self._conn.execute(
            "SELECT document_json FROM lineage_receipts WHERE project = ? AND identity = ?",
            (project.canonical, identity_canonical),
        ).fetchone()
        return LineageReceipt.from_dict(json.loads(row[0])) if row else None

    # -- research questions --------------------------------------------
    def upsert_research_question(self, question: ResearchQuestion) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO research_questions (project, identity, dedup_key, status, document_json) VALUES (?, ?, ?, ?, ?)",
                (question.project.canonical, question.identity.canonical, question.dedup_key,
                 question.status.value, json.dumps(question.to_dict())),
            )
            self._conn.commit()

    def question_status_by_dedup_key(self, project: Identity) -> dict[str, QuestionStatus]:
        rows = self._conn.execute(
            "SELECT dedup_key, status FROM research_questions WHERE project = ?", (project.canonical,)
        ).fetchall()
        return {row[0]: QuestionStatus(row[1]) for row in rows}

    def list_research_questions(self, project: Identity) -> tuple[ResearchQuestion, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM research_questions WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(ResearchQuestion.from_dict(json.loads(row[0])) for row in rows)

    # -- insights --------------------------------------------------------
    def upsert_insight(self, insight: ProjectInsight) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO project_insights (project, identity, valid_from, document_json) VALUES (?, ?, ?, ?)",
                (insight.project.canonical, insight.identity.canonical, insight.valid_from.isoformat(),
                 json.dumps(insight.to_dict())),
            )
            self._conn.commit()

    def list_insights(self, project: Identity) -> tuple[ProjectInsight, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM project_insights WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(ProjectInsight.from_dict(json.loads(row[0])) for row in rows)

    # -- exposures + feedback -----------------------------------------
    def append_exposure(self, exposure: Exposure) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO exposures (project, identity, insight, occurred_at, document_json) VALUES (?, ?, ?, ?, ?)",
                (exposure.project.canonical, exposure.identity.canonical, exposure.insight.canonical,
                 exposure.occurred_at.isoformat(), json.dumps(exposure.to_dict())),
            )
            self._conn.commit()

    def list_exposures(self, project: Identity) -> tuple[Exposure, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM exposures WHERE project = ? ORDER BY occurred_at", (project.canonical,)
        ).fetchall()
        return tuple(Exposure.from_dict(json.loads(row[0])) for row in rows)

    def get_exposure(self, project: Identity, exposure_identity_canonical: str) -> Exposure | None:
        row = self._conn.execute(
            "SELECT document_json FROM exposures WHERE project = ? AND identity = ?",
            (project.canonical, exposure_identity_canonical),
        ).fetchone()
        return Exposure.from_dict(json.loads(row[0])) if row else None

    def record_exposure_feedback(
        self, project: Identity, exposure_identity_canonical: str, outcome: ExposureOutcome, *, now: datetime
    ) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO exposure_feedback (project, exposure, outcome, recorded_at) VALUES (?, ?, ?, ?)",
                (project.canonical, exposure_identity_canonical, outcome.value, now.isoformat()),
            )
            self._conn.commit()

    def get_exposure_feedback(self, project: Identity, exposure_identity_canonical: str) -> ExposureOutcome | None:
        row = self._conn.execute(
            "SELECT outcome FROM exposure_feedback WHERE project = ? AND exposure = ?",
            (project.canonical, exposure_identity_canonical),
        ).fetchone()
        return ExposureOutcome(row[0]) if row else None

    def dismissal_count(self, project: Identity, insight_identity_canonical: str) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM exposure_feedback f
            JOIN exposures e ON e.project = f.project AND e.identity = f.exposure
            WHERE f.project = ? AND e.insight = ? AND f.outcome = ?
            """,
            (project.canonical, insight_identity_canonical, ExposureOutcome.DISMISSED.value),
        ).fetchone()
        return int(row[0]) if row else 0

    # -- learning outcomes -------------------------------------------
    def append_learning_outcome(self, outcome: LearningOutcome) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO learning_outcomes (project, identity, document_json) VALUES (?, ?, ?)",
                (outcome.project.canonical, outcome.identity.canonical, json.dumps(outcome.to_dict())),
            )
            self._conn.commit()

    def list_learning_outcomes(self, project: Identity) -> tuple[LearningOutcome, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM learning_outcomes WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(LearningOutcome.from_dict(json.loads(row[0])) for row in rows)

    # -- cost ledger -----------------------------------------------------
    def append_cost_record(self, cost: CostRecord) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO cost_records (project, identity, resource, cost_micros, document_json) VALUES (?, ?, ?, ?, ?)",
                (cost.project.canonical, cost.identity.canonical, cost.resource.value,
                 cost.cost_micros, json.dumps(cost.to_dict())),
            )
            self._conn.commit()

    def list_cost_records(self, project: Identity) -> tuple[CostRecord, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM cost_records WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(CostRecord.from_dict(json.loads(row[0])) for row in rows)

    # -- learned decisions + disposable online state ----------------------
    def append_learned_decision(self, decision: LearnedDecisionRecord) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO learned_decisions (project, identity, decision_type, occurred_at, document_json) VALUES (?, ?, ?, ?, ?)",
                (decision.project.canonical, decision.identity.canonical, decision.decision_type,
                 decision.occurred_at.isoformat(), json.dumps(decision.to_dict())),
            )
            self._conn.commit()

    def get_learned_decision(self, project: Identity, identity: str) -> LearnedDecisionRecord | None:
        row = self._conn.execute(
            "SELECT document_json FROM learned_decisions WHERE project = ? AND identity = ?",
            (project.canonical, identity),
        ).fetchone()
        return LearnedDecisionRecord.from_dict(json.loads(row[0])) if row else None

    def list_learned_decisions(self, project: Identity) -> tuple[LearnedDecisionRecord, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM learned_decisions WHERE project = ? ORDER BY occurred_at, identity",
            (project.canonical,),
        ).fetchall()
        return tuple(LearnedDecisionRecord.from_dict(json.loads(row[0])) for row in rows)

    def online_event_exists(self, project: Identity, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM online_learning_events WHERE project = ? AND event_id = ?",
            (project.canonical, event_id),
        ).fetchone()
        return row is not None

    def record_online_no_update(self, label: object, disposition: object) -> bool:
        """Persist a rejected/no-label event so replay remains idempotent."""
        document = label.to_dict()  # type: ignore[attr-defined]
        with self._locked():
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO online_learning_events (project, event_id, decision_id, disposition, document_json) VALUES (?, ?, ?, ?, ?)",
                (label.project.canonical, label.event_id, label.decision_id, disposition.value, json.dumps(document)),  # type: ignore[attr-defined]
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def apply_online_update(self, label: object, decision: LearnedDecisionRecord, checkpoint: object) -> bool:
        """Atomically claim the event, attach its label, and replace the checkpoint."""
        from dataclasses import replace

        labeled = replace(decision, outcome_label=label.value, label_recorded_at=label.occurred_at)  # type: ignore[attr-defined]
        with self._locked():
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO online_learning_events (project, event_id, decision_id, disposition, document_json) VALUES (?, ?, ?, ?, ?)",
                    (label.project.canonical, label.event_id, label.decision_id, "updated", json.dumps(label.to_dict())),  # type: ignore[attr-defined]
                )
                if cursor.rowcount != 1:
                    self._conn.rollback()
                    return False
                self._conn.execute(
                    "UPDATE learned_decisions SET document_json = ? WHERE project = ? AND identity = ?",
                    (json.dumps(labeled.to_dict()), label.project.canonical, label.decision_id),  # type: ignore[attr-defined]
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO online_model_checkpoints (project, decision_type, checkpoint_json) VALUES (?, ?, ?)",
                    (label.project.canonical, decision.decision_type, json.dumps(checkpoint.to_dict())),  # type: ignore[attr-defined]
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def load_online_checkpoint(self, project: Identity, decision_type: str) -> object | None:
        from .repo_intelligence.online_learning import ModelCheckpoint

        row = self._conn.execute(
            "SELECT checkpoint_json FROM online_model_checkpoints WHERE project = ? AND decision_type = ?",
            (project.canonical, decision_type),
        ).fetchone()
        if not row:
            return None
        try:
            checkpoint = ModelCheckpoint.from_dict(json.loads(row[0]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return checkpoint if checkpoint.project == project else None

    def save_online_checkpoint(self, checkpoint: object) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO online_model_checkpoints (project, decision_type, checkpoint_json) VALUES (?, ?, ?)",
                (checkpoint.project.canonical, checkpoint.decision_type, json.dumps(checkpoint.to_dict())),  # type: ignore[attr-defined]
            )
            self._conn.commit()

    def discard_online_learning_state(self, project: Identity) -> None:
        """Delete disposable parameters/checkpoints; canonical evidence is untouched."""
        with self._locked():
            self._conn.execute("DELETE FROM online_model_checkpoints WHERE project = ?", (project.canonical,))
            self._conn.commit()

    # -- graph links -----------------------------------------------------
    def replace_graph_links(self, project: Identity, links: tuple[GraphLink, ...]) -> None:
        with self._locked():
            self._conn.execute("DELETE FROM graph_links WHERE project = ?", (project.canonical,))
            for link in links:
                self._conn.execute(
                    "INSERT OR REPLACE INTO graph_links (project, identity, document_json) VALUES (?, ?, ?)",
                    (link.project.canonical, link.identity.canonical, json.dumps(link.to_dict())),
                )
            self._conn.commit()

    def list_graph_links(self, project: Identity) -> tuple[GraphLink, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM graph_links WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(GraphLink.from_dict(json.loads(row[0])) for row in rows)

    # -- pipeline run bookkeeping ---------------------------------------
    def record_pipeline_run(
        self, project: Identity, *, now: datetime, window_end: datetime, memory_status: InternalAnswerStatus | None = None
    ) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO pipeline_runs (project, last_run_at, window_end, memory_status) VALUES (?, ?, ?, ?)",
                (project.canonical, now.isoformat(), window_end.isoformat(), memory_status.value if memory_status else None),
            )
            self._conn.commit()

    def last_pipeline_run(self, project: Identity) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_run_at FROM pipeline_runs WHERE project = ?", (project.canonical,)
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def last_memory_status(self, project: Identity) -> InternalAnswerStatus | None:
        """The internal/Memory knowledge-sufficiency status recorded by the most recent pipeline pass."""
        row = self._conn.execute(
            "SELECT memory_status FROM pipeline_runs WHERE project = ?", (project.canonical,)
        ).fetchone()
        return InternalAnswerStatus(row[0]) if row and row[0] else None

    # -- jobs --------------------------------------------------------------
    def upsert_job(self, job: ProjectIntelligenceJob) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs (project, identity, idempotency_key, document_json) VALUES (?, ?, ?, ?)",
                (job.project.canonical, job.identity.canonical, job.idempotency_key, json.dumps(job.to_dict())),
            )
            self._conn.commit()

    def get_job(self, project: Identity, identity_canonical: str) -> ProjectIntelligenceJob | None:
        row = self._conn.execute(
            "SELECT document_json FROM jobs WHERE project = ? AND identity = ?",
            (project.canonical, identity_canonical),
        ).fetchone()
        return ProjectIntelligenceJob.from_dict(json.loads(row[0])) if row else None

    def list_jobs(self, project: Identity) -> tuple[ProjectIntelligenceJob, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM jobs WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(ProjectIntelligenceJob.from_dict(json.loads(row[0])) for row in rows)

    # -- signal <-> lineage receipt link (both upserted independently) -----
    def link_signal_receipt(self, project: Identity, signal_identity: RepoIdentity, receipt_identity: RepoIdentity) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO signal_receipts (project, signal_identity, receipt_identity) VALUES (?, ?, ?)",
                (project.canonical, signal_identity.canonical, receipt_identity.canonical),
            )
            self._conn.commit()

    def receipt_identity_for_signal(self, project: Identity, signal_identity_canonical: str) -> str | None:
        row = self._conn.execute(
            "SELECT receipt_identity FROM signal_receipts WHERE project = ? AND signal_identity = ?",
            (project.canonical, signal_identity_canonical),
        ).fetchone()
        return row[0] if row else None

    # -- research question <-> job link (a question may be reopened across jobs) --
    def record_question_job(self, project: Identity, dedup_key: str, job_identity: RepoIdentity) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO question_jobs (project, dedup_key, job_identity) VALUES (?, ?, ?)",
                (project.canonical, dedup_key, job_identity.canonical),
            )
            self._conn.commit()

    def job_identities_for_question(self, project: Identity, dedup_key: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT job_identity FROM question_jobs WHERE project = ? AND dedup_key = ? ORDER BY job_identity",
            (project.canonical, dedup_key),
        ).fetchall()
        return tuple(row[0] for row in rows)

    # -- analogy records (Execution RI-14) --------------------------------
    def upsert_analogy_record(self, record: AnalogyRecord) -> None:
        with self._locked():
            self._conn.execute(
                "INSERT OR REPLACE INTO analogy_records (project, identity, internal_entity_ref, confidence, document_json) VALUES (?, ?, ?, ?, ?)",
                (record.project.canonical, record.identity.canonical, record.internal_entity_ref.canonical,
                 record.confidence, json.dumps(record.to_dict())),
            )
            self._conn.commit()

    def list_analogy_records(self, project: Identity) -> tuple[AnalogyRecord, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM analogy_records WHERE project = ? ORDER BY identity", (project.canonical,)
        ).fetchall()
        return tuple(AnalogyRecord.from_dict(json.loads(row[0])) for row in rows)

    def analogies_for_entity(self, project: Identity, internal_entity_ref_canonical: str) -> tuple[AnalogyRecord, ...]:
        rows = self._conn.execute(
            "SELECT document_json FROM analogy_records WHERE project = ? AND internal_entity_ref = ? ORDER BY identity",
            (project.canonical, internal_entity_ref_canonical),
        ).fetchall()
        return tuple(AnalogyRecord.from_dict(json.loads(row[0])) for row in rows)

    # -- rebuild / verify (signals, questions, receipts, links are pure caches) --
    def discard_rebuildable_state(self, project: Identity) -> None:
        """Drop the purely-derived cache (never the durable exposure/feedback/outcome history)."""
        with self._locked():
            for table in (
                "internal_signals", "lineage_receipts", "research_questions", "graph_links",
                "signal_receipts", "question_jobs", "analogy_records",
            ):
                self._conn.execute(f"DELETE FROM {table} WHERE project = ?", (project.canonical,))
            self._conn.execute("DELETE FROM pipeline_runs WHERE project = ?", (project.canonical,))
            self._conn.commit()


__all__ = ["RepoIntelligenceStore", "STORE_FILENAME", "STORE_SCHEMA_VERSION"]
