"""Execution 05, Section E: a diagnostic path over the canonical evidence
ledger — detection only, never repair.

Unlike ``EvidenceLedger.replay()`` (which must stop at the FIRST malformed
line, fail closed) or ``projection_store.build()`` (which reuses that exact
fail-closed behavior), this module's job is the opposite: find and report
EVERY problem in one pass, so an operator can see the full extent of any
corruption before deciding what to do about it. It never rewrites the
ledger, never truncates it, and never silently drops a bad line — the
canonical evidence file is read-only from this module's perspective.

Repair is deliberately NOT implemented in this execution. Section E
requires that any future repair operation be explicit, back up first, and
produce an audit result — building that machinery now, before any real
incident has ever required it, would be exactly the over-engineering the
mission warns against. This is a documented, deliberate deferral, not an
oversight.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from . import projection_store
from .contracts import EntityKind, deterministic_identity
from .ledger import EvidenceLedger
from .observation_model import ObservationEnvelope
from .privacy import PrivacyGuard, PrivacyPolicy


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    line_number: int
    byte_offset: int
    kind: str  # "invalid_json" | "truncated_final_record" | "checksum_mismatch" | "unexpected_project" | "duplicate_identity"
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    ledger_path: Path
    project_canonical: str
    total_lines: int
    valid_records: int
    findings: tuple[DoctorFinding, ...]
    projection_status: "projection_store.ProjectionStatus | None"

    @property
    def healthy(self) -> bool:
        if self.findings:
            return False
        if self.projection_status is not None and not self.projection_status.healthy:
            return False
        return True


def run_doctor(ledger_path: Path, project_key: str, *, projection_path: Path | None = None) -> DoctorReport:
    """Collect-all scan: every malformed/suspicious line is reported, never
    just the first. Never mutates `ledger_path`."""
    from .provenance import verify as verify_provenance

    project = deterministic_identity(EntityKind.PROJECT, project_key)
    findings: list[DoctorFinding] = []
    seen_identities: dict[str, int] = {}
    total_lines = 0
    valid_records = 0

    if ledger_path.exists():
        raw_bytes = ledger_path.read_bytes()
        ends_with_newline = raw_bytes.endswith(b"\n") if raw_bytes else True
        offset = 0
        lines = raw_bytes.split(b"\n")
        # split() on a trailing-newline file yields one empty trailing
        # element; drop it so line numbering matches a real line count.
        if lines and lines[-1] == b"":
            lines = lines[:-1]
        for index, raw_line in enumerate(lines):
            line_number = index + 1
            line_start_offset = offset
            offset += len(raw_line) + 1  # + the newline split() consumed
            is_final_line = index == len(lines) - 1
            if not raw_line.strip():
                total_lines += 1
                continue
            total_lines += 1
            if is_final_line and not ends_with_newline:
                findings.append(DoctorFinding(line_number, line_start_offset, "truncated_final_record", "final record has no trailing newline"))
                continue
            try:
                decoded = json.loads(raw_line.decode("utf-8"))
                envelope = ObservationEnvelope.from_dict(decoded)
            except Exception as exc:  # noqa: BLE001 - collect-all: report every kind of malformed line
                findings.append(DoctorFinding(line_number, line_start_offset, "invalid_json", str(exc)))
                continue
            if envelope.project != project:
                findings.append(DoctorFinding(line_number, line_start_offset, "unexpected_project", f"expected {project.canonical}, found {envelope.project.canonical}"))
                continue
            canonical = envelope.observation.identity.canonical
            if canonical in seen_identities:
                findings.append(DoctorFinding(line_number, line_start_offset, "duplicate_identity", f"{canonical} first seen at line {seen_identities[canonical]}"))
                continue
            seen_identities[canonical] = line_number
            if envelope.integrity_checksum is not None:
                result = verify_provenance(envelope)
                if result is False:
                    findings.append(DoctorFinding(line_number, line_start_offset, "checksum_mismatch", f"{canonical} integrity_checksum does not match its content"))
                    continue
            valid_records += 1

    projection_status = None
    if projection_path is not None:
        ledger = EvidenceLedger(ledger_path, project, PrivacyGuard(PrivacyPolicy()))
        projection_status = projection_store.verify(ledger, projection_path)

    return DoctorReport(
        ledger_path=ledger_path, project_canonical=project.canonical, total_lines=total_lines,
        valid_records=valid_records, findings=tuple(findings), projection_status=projection_status,
    )


def _report_to_dict(report: DoctorReport) -> dict[str, object]:
    return {
        "ledgerPath": str(report.ledger_path),
        "project": report.project_canonical,
        "healthy": report.healthy,
        "totalLines": report.total_lines,
        "validRecords": report.valid_records,
        "findings": [
            {"lineNumber": f.line_number, "byteOffset": f.byte_offset, "kind": f.kind, "detail": f.detail}
            for f in report.findings
        ],
        "projection": None if report.projection_status is None else {
            "healthy": report.projection_status.healthy,
            "reason": report.projection_status.reason,
            "recordCount": report.projection_status.record_count,
            "checkpoint": None if report.projection_status.checkpoint is None else {
                "schemaVersion": report.projection_status.checkpoint.schema_version,
                "ledgerByteOffset": report.projection_status.checkpoint.ledger_byte_offset,
                "ledgerRecordCount": report.projection_status.checkpoint.ledger_record_count,
                "generation": report.projection_status.checkpoint.generation,
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Visible Verification (Execution 05): a dev/diagnostic-only command —
    never wired into any product UI — reporting canonical ledger record
    count, projection checkpoint, indexed record count, and
    healthy/rebuild-required in one JSON document."""
    parser = argparse.ArgumentParser(description="Diagnose the canonical evidence ledger and its read projection (detection only, no repair).")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--project", default="midnight")
    args = parser.parse_args(argv)

    ledger_path = args.data_dir / "evidence.jsonl"
    path = projection_store.projection_path(args.data_dir)
    report = run_doctor(ledger_path, args.project, projection_path=path)
    print(json.dumps(_report_to_dict(report), indent=2))
    return 0 if report.healthy else 1


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
