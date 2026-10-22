"""Словарь «отраслевой термин -> префиксы ОКВЭД2» (contracts/industry_terms.yaml) и сопоставление с профилем.

Формат news_item.industries (предложение участника 1, на согласование с 2 и 6):
  okved_prefixes: list[str]  — префиксы ОКВЭД2 уровня класса и глубже ("47", "45.32", "07.29.4");
  okved_sections: list[str]  — буквы разделов, ВЫВОДЯТСЯ из префиксов (sections_for), только для грубой фильтрации.
Сопоставление с компанией — по уровням кода: префикс новости ∈ profile.industry.okved_levels.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .okved import OkvedDirectory, okved_levels

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "industry_terms.yaml"


def load_industry_terms(path: str | Path | None = None) -> dict[str, dict]:
    with open(path or DEFAULT_PATH, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return {e["id"]: e for e in doc["entries"]}


def prefixes_for(entries: dict[str, dict], entry_ids: list[str]) -> list[str]:
    out: list[str] = []
    for eid in entry_ids:
        for p in entries[eid]["okved_prefixes"]:
            if p["prefix"] not in out:
                out.append(p["prefix"])
    return out


def sections_for(prefixes: list[str], directory: OkvedDirectory) -> list[str]:
    out: list[str] = []
    for p in prefixes:
        info = directory.parse(p)
        if info and info.section and info.section not in out:
            out.append(info.section)
    return out


class InvalidOkvedPrefix(ValueError):
    """Префикс не является кодом ОКВЭД2 (например "4", "45.", "45.3.1")."""


def _check_prefixes(prefixes: list[str]) -> list[str]:
    bad = [p for p in prefixes if not isinstance(p, str) or okved_levels(p) is None]
    if bad:
        raise InvalidOkvedPrefix(f"некорректные префиксы ОКВЭД2: {bad}")
    return list(dict.fromkeys(p.strip() for p in prefixes))


def match_company(news_prefixes: list[str], company_levels: list[str]) -> list[str]:
    """Префиксы новости, совпавшие с уровнями ОКВЭД компании.

    Совпадение — только точное равенство префикса одному из уровней кода (не startswith):
    "45.3" совпадает с 45.31.1, "45.32" — нет; "41.20" не совпадает с менее точным кодом 41.2.
    """
    levels = set(company_levels)
    return [p for p in _check_prefixes(news_prefixes) if p in levels]


def match_supply_chain(news_prefixes: list[str], profile: dict) -> list[dict]:
    """Совпадения префиксов новости с полными кодами ОКВЭД контрагентов профиля.

    Возвращает строки {direction, prefix, okved_code, share_of_known, pay_amt, n_counterparties},
    отсортированные по доле. direction: suppliers (исходящие платежи) | customers (входящие).
    Учитываются только коды из детализации (top_codes); при *_codes_meta.truncated мелкие коды не видны.
    """
    prefixes = _check_prefixes(news_prefixes)
    factor = next((f for f in profile["sensitivity_factors"] if f["code"] == "supply_chain_industries"), None)
    if factor is None:
        return []
    out = []
    for direction, key in (("suppliers", "supplier_codes"), ("customers", "customer_codes")):
        for item in factor["details"].get(key, []):
            levels = set(item["okved_levels"])
            for p in prefixes:
                if p in levels:
                    out.append({"direction": direction, "prefix": p, "okved_code": item["okved_code"],
                                "share_of_known": item["share_of_known"], "pay_amt": item["pay_amt"],
                                "n_counterparties": item["n_counterparties"]})
    return sorted(out, key=lambda x: (-(x["share_of_known"] or 0), x["direction"], x["okved_code"], x["prefix"]))


def validate_prefix(prefix: str) -> bool:
    return okved_levels(prefix) is not None
