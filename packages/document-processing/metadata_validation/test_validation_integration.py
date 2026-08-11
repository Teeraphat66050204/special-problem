from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from metadata_validation import DocumentStatus, FieldStatus, validate_metadata
from metadata_validation._test_support import set_field, valid_extraction


class ValidationIntegrationTests(unittest.TestCase):
    def test_valid_document(self) -> None:
        result = validate_metadata(valid_extraction())
        self.assertEqual(result.document_status, DocumentStatus.VALID)
        self.assertFalse(result.requires_manual_review)

    def test_review_required_document(self) -> None:
        extraction = valid_extraction()
        extraction["fields"]["advisor"]["confidence"] = 0.4
        result = validate_metadata(extraction)
        self.assertEqual(result.document_status, DocumentStatus.REVIEW_REQUIRED)

    def test_invalid_document(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "students", [{"name": "Test", "student_id": "BAD"}])
        result = validate_metadata(extraction)
        self.assertEqual(result.document_status, DocumentStatus.INVALID)

    def test_missing_required_field_requests_review_not_failure(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "department", None)
        result = validate_metadata(extraction)
        self.assertEqual(result.document_status, DocumentStatus.REVIEW_REQUIRED)
        self.assertEqual(result.fields["department"].status, FieldStatus.MISSING)

    def test_failed_extraction_input(self) -> None:
        extraction = {
            "metadata": {},
            "fields": {},
            "warnings": ["no_metadata_extracted"],
            "extraction_status": "failed",
        }
        result = validate_metadata(extraction)
        self.assertEqual(result.document_status, DocumentStatus.FAILED)

    def test_non_mapping_input_fails_structurally(self) -> None:
        result = validate_metadata("invalid")
        self.assertEqual(result.document_status, DocumentStatus.FAILED)

    def test_partial_extraction_with_metadata_is_not_failed(self) -> None:
        extraction = valid_extraction()
        extraction["extraction_status"] = "partial"
        set_field(extraction, "faculty", None)
        result = validate_metadata(extraction)
        self.assertEqual(result.document_status, DocumentStatus.REVIEW_REQUIRED)

    def test_low_confidence_requires_review(self) -> None:
        extraction = valid_extraction()
        extraction["fields"]["title_th"]["confidence"] = 0.69
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["title_th"].status, FieldStatus.REVIEW_REQUIRED)

    def test_unresolved_candidate_conflict_requires_review(self) -> None:
        extraction = valid_extraction()
        field = extraction["fields"]["advisor"]
        field["candidates"] = [{"value": "Advisor A"}, {"value": "Advisor B"}]
        field["warnings"] = ["conflicting_advisor_candidates"]
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["advisor"].status, FieldStatus.REVIEW_REQUIRED)

    def test_whitespace_only_conflict_is_resolved(self) -> None:
        extraction = valid_extraction()
        field = extraction["fields"]["degree"]
        field["candidates"] = [
            {"value": "วิทยาศาสตรบัณฑิต"},
            {"value": "  วิทยาศาสตรบัณฑิต  "},
        ]
        field["warnings"] = ["conflicting_degree_candidates"]
        extraction["warnings"] = ["conflicting_degree_candidates"]
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["degree"].status, FieldStatus.VALID)
        self.assertFalse(result.requires_manual_review)

    def test_english_case_only_conflict_is_resolved(self) -> None:
        extraction = valid_extraction()
        field = extraction["fields"]["title_en"]
        field["candidates"] = [
            {"value": "Information System for Project Data Management"},
            {"value": "INFORMATION SYSTEM FOR PROJECT DATA MANAGEMENT"},
        ]
        field["warnings"] = ["conflicting_title_en_candidates"]
        extraction["warnings"] = ["conflicting_title_en_candidates"]
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["title_en"].status, FieldStatus.VALID)
        self.assertFalse(result.requires_manual_review)

    def test_extraction_warning_is_propagated(self) -> None:
        extraction = valid_extraction()
        extraction["warnings"] = ["unusable_normalized_page"]
        result = validate_metadata(extraction)
        self.assertEqual(result.document_status, DocumentStatus.REVIEW_REQUIRED)
        self.assertEqual(result.warnings[0].code, "upstream_warning")

    def test_validation_does_not_mutate_extraction_result(self) -> None:
        extraction = valid_extraction()
        original = copy.deepcopy(extraction)
        validate_metadata(extraction)
        self.assertEqual(extraction, original)

    def test_output_is_deterministic(self) -> None:
        extraction = valid_extraction()
        self.assertEqual(
            validate_metadata(extraction).to_dict(),
            validate_metadata(extraction).to_dict(),
        )

    def test_reference_data_none_works(self) -> None:
        result = validate_metadata(valid_extraction(), reference_data=None)
        self.assertEqual(result.document_status, DocumentStatus.VALID)

    def test_structured_output_preserves_metadata(self) -> None:
        extraction = valid_extraction()
        output = validate_metadata(extraction).to_dict()
        self.assertEqual(output["metadata"], extraction["metadata"])
        self.assertIn("validation", output)
        self.assertIn("reasons", output["validation"]["fields"]["advisor"])

    def test_cli_reads_stdin(self) -> None:
        script = Path(__file__).with_name("validate_metadata.py")
        completed = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(valid_extraction()),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["validation"]["document_status"], "VALID")


if __name__ == "__main__":
    unittest.main()
