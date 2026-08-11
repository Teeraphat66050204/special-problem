from __future__ import annotations

import unittest
from pathlib import Path

from metadata_validation import FieldStatus, ValidationReferenceData, validate_metadata
from metadata_validation._test_support import ABSTRACT_TH, set_field, valid_extraction


class ContentAndAdvisorValidationTests(unittest.TestCase):
    def test_valid_title(self) -> None:
        result = validate_metadata(valid_extraction())
        self.assertEqual(result.fields["title_th"].status, FieldStatus.VALID)

    def test_missing_one_language_title_is_allowed_by_document_policy(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "title_en", None)
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["title_en"].status, FieldStatus.MISSING)
        self.assertFalse(result.requires_manual_review)

    def test_heading_only_title_is_invalid(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "title_th", "บทคัดย่อ")
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["title_th"].status, FieldStatus.INVALID)

    def test_title_contamination_is_invalid(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "title_en", "Project Student ID: 66050204")
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["title_en"].status, FieldStatus.INVALID)

    def test_valid_advisor(self) -> None:
        result = validate_metadata(valid_extraction())
        self.assertEqual(result.fields["advisor"].status, FieldStatus.VALID)

    def test_missing_advisor(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "advisor", None)
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["advisor"].status, FieldStatus.MISSING)

    def test_advisor_also_listed_as_co_advisor(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "co_advisors", [extraction["metadata"]["advisor"]])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["co_advisors"].status, FieldStatus.INVALID)

    def test_duplicate_co_advisor(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "co_advisors", ["Dr. Second", "dr. second"])
        result = validate_metadata(extraction)
        self.assertEqual(
            result.fields["co_advisors"].status,
            FieldStatus.REVIEW_REQUIRED,
        )

    def test_empty_co_advisor_list_is_valid(self) -> None:
        result = validate_metadata(valid_extraction())
        self.assertEqual(result.fields["co_advisors"].status, FieldStatus.VALID)

    def test_advisor_reference_lookup_success(self) -> None:
        fixture = Path(__file__).with_name("test_reference_data.json")
        references = ValidationReferenceData.from_json(fixture)
        result = validate_metadata(valid_extraction(), references)
        self.assertEqual(result.fields["advisor"].status, FieldStatus.VALID)
        self.assertEqual(result.fields["advisor"].reference_check, "performed")

    def test_advisor_reference_lookup_unavailable_does_not_invalidate(self) -> None:
        result = validate_metadata(valid_extraction(), reference_data=None)
        self.assertEqual(result.fields["advisor"].status, FieldStatus.VALID)
        self.assertEqual(result.fields["advisor"].reference_check, "skipped_unavailable")

    def test_unknown_advisor_with_supplied_reference_requires_review(self) -> None:
        references = ValidationReferenceData.from_mapping({"advisors": ["Other Advisor"]})
        result = validate_metadata(valid_extraction(), references)
        self.assertEqual(result.fields["advisor"].status, FieldStatus.REVIEW_REQUIRED)

    def test_valid_abstract(self) -> None:
        result = validate_metadata(valid_extraction())
        self.assertEqual(result.fields["abstract_th"].status, FieldStatus.VALID)

    def test_short_abstract_requires_review(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "abstract_th", "เนื้อหาสั้น")
        result = validate_metadata(extraction)
        self.assertEqual(
            result.fields["abstract_th"].status,
            FieldStatus.REVIEW_REQUIRED,
        )

    def test_missing_both_abstracts_requires_document_review(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "abstract_th", None)
        set_field(extraction, "abstract_en", None)
        result = validate_metadata(extraction)
        self.assertTrue(result.requires_manual_review)
        self.assertEqual(result.fields["abstract_th"].status, FieldStatus.MISSING)

    def test_abstract_upstream_warning_requires_review(self) -> None:
        extraction = valid_extraction()
        extraction["fields"]["abstract_th"]["warnings"] = [
            "suspicious_thai_character_spacing"
        ]
        result = validate_metadata(extraction)
        self.assertEqual(
            result.fields["abstract_th"].status,
            FieldStatus.REVIEW_REQUIRED,
        )

    def test_abstract_keyword_tail_requires_review(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "abstract_th", ABSTRACT_TH + " คำสำคัญ: ระบบ")
        result = validate_metadata(extraction)
        self.assertEqual(
            result.fields["abstract_th"].status,
            FieldStatus.REVIEW_REQUIRED,
        )

    def test_empty_keywords_are_valid_by_default(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "keywords", [])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["keywords"].status, FieldStatus.VALID)

    def test_duplicate_keywords_require_review(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "keywords", ["Metadata", " metadata "])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["keywords"].status, FieldStatus.REVIEW_REQUIRED)

    def test_page_footer_keyword_requires_review(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "keywords", ["validation", "page 4"])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["keywords"].status, FieldStatus.REVIEW_REQUIRED)


if __name__ == "__main__":
    unittest.main()
