"""Representative extraction-result fixtures shared by validation tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


ABSTRACT_TH = (
    "งานวิจัยนี้ศึกษาการออกแบบระบบสารสนเทศเพื่อสนับสนุนการทำงาน "
    "โดยประเมินความถูกต้อง ความครบถ้วน และประสิทธิภาพของระบบจากข้อมูลตัวอย่าง "
    "ผลการศึกษาพบว่าระบบสามารถสนับสนุนกระบวนการทำงานได้ตามวัตถุประสงค์ที่กำหนด"
)
ABSTRACT_EN = (
    "This study designs an information system to support a documented workflow. "
    "The evaluation measures correctness, completeness, and local performance "
    "against representative data, and the results satisfy the stated objectives."
)


def _field(value: Any, *, confidence: float = 0.95) -> dict[str, Any]:
    return {
        "value": deepcopy(value),
        "confidence": confidence,
        "source_page": 4,
        "source_pages": [4],
        "source_language": "thai",
        "source_languages": ["thai"],
        "method": "test_fixture",
        "evidence": [str(value)],
        "candidates": [
            {
                "value": deepcopy(value),
                "confidence": confidence,
                "source_page": 4,
                "source_language": "thai",
                "source_line_indexes": [0],
                "method": "test_fixture",
                "evidence": [str(value)],
            }
        ] if value not in (None, []) else [],
        "alternatives": [],
        "warnings": [],
    }


def valid_extraction() -> dict[str, Any]:
    metadata = {
        "title_th": "ระบบสารสนเทศสำหรับการจัดการข้อมูลโครงการ",
        "title_en": "Information System for Project Data Management",
        "students": [{"name": "นายทดสอบ ระบบ", "student_id": "66050204"}],
        "degree": "วิทยาศาสตรบัณฑิต",
        "department": "วิทยาการคอมพิวเตอร์",
        "faculty": "วิทยาศาสตร์",
        "academic_year": "2569",
        "advisor": "ดร. อาจารย์ ตัวอย่าง",
        "co_advisors": [],
        "abstract_th": ABSTRACT_TH,
        "abstract_en": ABSTRACT_EN,
        "keywords": ["ระบบสารสนเทศ", "metadata validation"],
    }
    return {
        "metadata": deepcopy(metadata),
        "fields": {name: _field(value) for name, value in metadata.items()},
        "warnings": [],
        "extraction_status": "success",
        "requires_manual_review": False,
        "stats": {"fields_extracted": 12},
    }


def set_field(
    extraction: dict[str, Any],
    name: str,
    value: Any,
    *,
    confidence: float = 0.95,
) -> None:
    extraction["metadata"][name] = deepcopy(value)
    extraction["fields"][name] = _field(value, confidence=confidence)
