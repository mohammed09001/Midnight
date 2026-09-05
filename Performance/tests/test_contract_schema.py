import unittest

from midnight_performance.contract_schema import (
    ContractValidationError,
    validate_activity_response,
    validate_host_envelope,
    validate_project_descriptor,
)


class ContractSchemaTests(unittest.TestCase):
    def test_valid_project_descriptor_passes(self):
        validate_project_descriptor(
            {"descriptorVersion": 1, "projectId": "midnight", "performanceDataDir": "Performance/data", "workspaceId": None}
        )

    def test_project_descriptor_missing_required_field_fails(self):
        with self.assertRaises(ContractValidationError):
            validate_project_descriptor({"descriptorVersion": 1, "projectId": "midnight"})

    def test_project_descriptor_rejects_unknown_field(self):
        with self.assertRaises(ContractValidationError):
            validate_project_descriptor(
                {"descriptorVersion": 1, "projectId": "midnight", "performanceDataDir": "x", "extra": True}
            )

    def test_valid_request_envelope_passes(self):
        validate_host_envelope({"contractVersion": 1, "operation": "activity.listPromptRuns", "request": {}})

    def test_valid_success_envelope_passes(self):
        validate_host_envelope(
            {"contractVersion": 1, "operation": "activity.listPromptRuns", "ok": True, "result": {"events": []}}
        )

    def test_valid_error_envelope_passes(self):
        validate_host_envelope(
            {
                "contractVersion": 1,
                "operation": None,
                "ok": False,
                "error": {"code": "UNKNOWN_OPERATION", "message": "no such operation"},
            }
        )

    def test_envelope_matching_zero_shapes_fails(self):
        with self.assertRaises(ContractValidationError):
            validate_host_envelope({"contractVersion": 1})

    def test_activity_response_requires_all_fields(self):
        with self.assertRaises(ContractValidationError):
            validate_activity_response({"version": 1, "project": "mp:v1:project:x"})

    def test_activity_response_valid_document_passes(self):
        validate_activity_response(
            {
                "version": 1,
                "project": "mp:v1:project:x",
                "events": [{"promptRunId": "mp:v1:prompt_run:y", "occurredAt": "2026-01-01T00:00:00+00:00"}],
                "totalMatching": 1,
                "limit": 100,
                "complete": True,
                "cursor": None,
                "nextCursor": None,
                "checkpoint": {"schemaVersion": 1, "ledgerByteOffset": 0, "ledgerRecordCount": 1, "generation": "abc123"},
            }
        )


if __name__ == "__main__":
    unittest.main()
