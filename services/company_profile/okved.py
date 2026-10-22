"""Разбор кодов ОКВЭД2 и построение иерархии.

Форматы в данных: XX, XX.X, XX.XX, XX.XX.X, XX.XX.XX (см. docs/data_audit.md §3).
Уровни ОКВЭД2: класс (XX) -> подкласс (XX.X) -> группа (XX.XX) -> подгруппа (XX.XX.X) -> вид (XX.XX.XX).
Коды "41.2" и "41.20" — разные уровни (подкласс и группа), поэтому сравниваем по уровням, а не по строке.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# XX | XX.X | XX.XX | XX.XX.X | XX.XX.XX. Подгруппа/вид — только после группы из 2 цифр (45.3.1 некорректен).
_CODE_RE = re.compile(r"^\d{2}(\.\d{1,2}|\.\d{2}\.\d{1,2})?$")


@dataclass(frozen=True)
class OkvedInfo:
    code: str
    levels: tuple[str, ...]
    division: str  # класс, 2 цифры
    section: str | None
    section_name: str | None


def okved_levels(code: str) -> tuple[str, ...] | None:
    """Возвращает уровни кода от общего к частному или None, если код некорректен."""
    code = code.strip()
    if not _CODE_RE.match(code):
        return None
    parts = code.split(".")
    levels = [parts[0]]
    if len(parts) >= 2:
        p1 = parts[1]
        levels.append(f"{parts[0]}.{p1[0]}")
        if len(p1) == 2:
            levels.append(f"{parts[0]}.{p1}")
        if len(parts) == 3:
            p2 = parts[2]
            base = f"{parts[0]}.{p1}"
            levels.append(f"{base}.{p2[0]}")
            if len(p2) == 2:
                levels.append(f"{base}.{p2}")
    # убираем повторы, сохраняя порядок
    seen: list[str] = []
    for lvl in levels:
        if lvl not in seen:
            seen.append(lvl)
    return tuple(seen)


class OkvedDirectory:
    """Сопоставление класса ОКВЭД с разделом (буквой) по конфигу feature_rules.yaml."""

    def __init__(self, sections_cfg: dict[str, dict[str, Any]]):
        self._by_division: dict[int, tuple[str, str]] = {}
        for letter, spec in sections_cfg.items():
            for div in range(int(spec["from"]), int(spec["to"]) + 1):
                self._by_division[div] = (letter, spec["name"])

    def parse(self, code: str | None) -> OkvedInfo | None:
        if code is None:
            return None
        levels = okved_levels(code)
        if levels is None:
            return None
        division = levels[0]
        section = self._by_division.get(int(division))
        return OkvedInfo(
            code=code.strip(),
            levels=levels,
            division=division,
            section=section[0] if section else None,
            section_name=section[1] if section else None,
        )


def matches_prefix(levels: tuple[str, ...], prefixes: list[str]) -> list[str]:
    """Какие префиксы из конфига совпадают с одним из уровней кода."""
    lv = set(levels)
    return [p for p in prefixes if p in lv]
