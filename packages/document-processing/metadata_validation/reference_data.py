"""Injected offline reference-data abstraction with no database dependency."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .comparison import canonical_text


@dataclass(frozen=True)
class DepartmentReference:
    faculty: str | None = None


@dataclass(frozen=True)
class ValidationReferenceData:
    departments: Mapping[str, DepartmentReference] = field(default_factory=dict)
    faculties: tuple[str, ...] = ()
    degrees: tuple[str, ...] = ()
    advisors: tuple[str, ...] = ()
    programs: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ValidationReferenceData":
        raw_departments = value.get("departments", {})
        departments: dict[str, DepartmentReference] = {}
        if isinstance(raw_departments, Mapping):
            for name, item in raw_departments.items():
                faculty = (
                    item.get("faculty")
                    if isinstance(item, Mapping)
                    else getattr(item, "faculty", None)
                )
                departments[str(name)] = DepartmentReference(
                    faculty=str(faculty) if faculty is not None else None
                )

        def strings(name: str) -> tuple[str, ...]:
            raw = value.get(name, ())
            if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple, set)):
                return ()
            return tuple(str(item) for item in raw if str(item).strip())

        return cls(
            departments=departments,
            faculties=strings("faculties"),
            degrees=strings("degrees"),
            advisors=strings("advisors"),
            programs=strings("programs"),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "ValidationReferenceData":
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise ValueError("reference data JSON must contain an object")
        return cls.from_mapping(payload)

    def contains(self, collection: str, value: Any) -> bool:
        values = getattr(self, collection)
        key = canonical_text(value)
        return any(canonical_text(item) == key for item in values)

    def department(self, value: Any) -> DepartmentReference | None:
        key = canonical_text(value)
        for name, reference in self.departments.items():
            if canonical_text(name) == key:
                return reference
        return None


def coerce_reference_data(value: Any) -> ValidationReferenceData | None:
    if value is None or isinstance(value, ValidationReferenceData):
        return value
    if isinstance(value, Mapping):
        return ValidationReferenceData.from_mapping(value)
    attributes = {
        name: getattr(value, name, ())
        for name in ("departments", "faculties", "degrees", "advisors", "programs")
    }
    return ValidationReferenceData.from_mapping(attributes)
