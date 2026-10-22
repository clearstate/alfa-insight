"""Обёртка значения профиля: {value, claim_type, source_*, as_of, method, confidence}.

claim_type в company_profile: fact | inference | unknown.
- fact      — значение взято из поля CSV без преобразования смысла;
- inference — получено правилом (не LLM) из одного или нескольких полей; правило указано в method;
- unknown   — значения нет в данных или его смысл не подтверждён.
as_of всегда null: в исходных данных нет дат (docs/data_audit.md).
"""

from __future__ import annotations

from typing import Any

Confidence = str  # "high" | "medium" | "low"


def row_id(line: int | None) -> str | None:
    return None if line is None else f"line:{int(line)}"


def attr(
    value: Any,
    claim_type: str,
    *,
    source_file: str | None = None,
    source_row_id: str | None = None,
    source_field: str | None = None,
    method: str | None = None,
    confidence: Confidence | None = None,
) -> dict:
    return {
        "value": value,
        "claim_type": claim_type,
        "source_file": source_file,
        "source_row_id": source_row_id,
        "source_field": source_field,
        "as_of": None,
        "method": method,
        "confidence": confidence,
    }


def fact(value: Any, source_file: str, line: int | None, source_field: str) -> dict:
    """Факт из поля CSV; пустое поле -> unknown с сохранением ссылки на источник."""
    return attr(
        value,
        "fact" if value is not None else "unknown",
        source_file=source_file,
        source_row_id=row_id(line),
        source_field=source_field,
    )


def inference(
    value: Any,
    method: str,
    *,
    source_file: str | None = None,
    line: int | None = None,
    source_field: str | None = None,
    confidence: Confidence = "medium",
) -> dict:
    if value is None:
        return unknown(method, source_file=source_file, line=line, source_field=source_field)
    return attr(value, "inference", source_file=source_file, source_row_id=row_id(line),
                source_field=source_field, method=method, confidence=confidence)


def unknown(
    method: str | None = None,
    *,
    source_file: str | None = None,
    line: int | None = None,
    source_field: str | None = None,
) -> dict:
    return attr(None, "unknown", source_file=source_file, source_row_id=row_id(line),
                source_field=source_field, method=method)


def evidence(source_file: str, line: int | None, source_field: str, value: Any) -> dict:
    return {"source_file": source_file, "source_row_id": row_id(line), "source_field": source_field, "value": value}
