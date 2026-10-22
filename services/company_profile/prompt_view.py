"""Минимизированное представление профиля для промптов LLM (участник 3).

Правила минимизации:
- без идентификаторов контрагентов, связанных компаний и физлиц;
- без построчных ссылок на источник (NEGATIVEMARK в профиль не входит вообще);
- суммы — только порядок величины и доли; признаки — уровень + обоснование + rule_id.
Ссылки на источники агент берёт из полного профиля по rule_id / пути поля, а не из промпта.
"""

from __future__ import annotations

import math


def _magnitude(x: float | None) -> str | None:
    if x is None or x <= 0:
        return None
    exp = int(math.floor(math.log10(x)))
    return f"~1e{exp}"


def build_prompt_view(profile: dict) -> dict:
    ind, size, ft = profile["industry"], profile["size"], profile["foreign_trade"]
    rel = profile["bank_relationship"]
    return {
        "company_ref": "client_company",  # без реального id
        "industry": {
            "okved_code": ind["okved_code"]["value"],
            "okved_name": ind["okved_name"]["value"],
            "section": ind["okved_section_name"]["value"],
        },
        "region": profile["geography"]["region"]["value"],
        "size": {
            "revenue_magnitude": _magnitude(size["revenue"]["value"]),
            "revenue_unit": "unknown (assumed RUB)",
            "is_large_business": size["is_large_business"]["value"],
            "workers_fns": size["workers_fns"]["value"],
            "company_age": size["company_age"]["value"],
        },
        "client_type": rel["client_type"]["value"],
        "products": [k for k, v in rel["products"].items() if v["value"] is True],
        "foreign_trade": {
            "has_foreign_trade": ft["has_foreign_trade"]["value"],
            "countries": ft["countries"]["value"] or [],
            "direction": "unknown",
        },
        "group": {"size": profile["group"]["size"], "is_mega_group": profile["group"]["is_mega_group"]},
        "sensitivity_factors": [
            {"code": f["code"], "level": f["level"], "confidence": f["confidence"], "rule_id": f["rule_id"],
             "rationale": f["rationale"]}
            for f in profile["sensitivity_factors"] if f["level"] not in ("none",)
        ],
        "supply_chain": _supply_chain(profile),
        "topics": [t["topic"] for t in profile["topics"][:10]],
        "data_gaps": [g["code"] for g in profile["data_gaps"]],
    }


def _supply_chain(profile: dict) -> dict:
    f = next((x for x in profile["sensitivity_factors"] if x["code"] == "supply_chain_industries"), None)
    if not f:
        return {}
    d = f["details"]
    strip = lambda items: [{"section": i["okved_section_name"], "share_of_known": i["share_of_known"]} for i in items]
    return {"suppliers": strip(d.get("suppliers", [])), "customers": strip(d.get("customers", [])),
            "known_coverage_outgoing": d.get("known_coverage_outgoing"),
            "known_coverage_incoming": d.get("known_coverage_incoming")}
