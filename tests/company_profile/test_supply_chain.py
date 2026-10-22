"""Цепочка поставок: сводка 0.2.0 сохранена, детализация кодов контрагентов, точное совпадение префиксов.
Отдельный СИНТЕТИЧЕСКИЙ набор: компания-хаб U_S0 и известные контрагенты с кодами разной глубины."""
import copy
import functools
import json
import tempfile
from pathlib import Path

from services.company_profile.access import UserStore, load_roles
from services.company_profile.features import load_rules
from services.company_profile.industry_terms import (
    InvalidOkvedPrefix, match_company, match_supply_chain,
)
from services.company_profile.loader import load_raw
from services.company_profile.prompt_view import build_prompt_view
from services.company_profile.service import ProfileService
from services.company_profile.validation import validate

from .synthetic import company, expect_raises, pay, service, write_dataset

SUPPLIERS = [  # id, ОКВЭД, сумма исходящего платежа от U_S0
    ("U_S1", "45.31.1", "4000000.0"),
    ("U_S2", "45.31.1", "1000000.0"),   # тот же код -> агрегируется, n_counterparties = 2
    ("U_S3", "45.32", "2000000.0"),
    ("U_S4", "41.20", "1000000.0"),
    ("U_S5", "41.2", "500000.0"),       # менее точный код того же подкласса
    ("U_S6", "07.29.41", "3000000.0"),  # глубокий префикс правила precious_metals (07.29.4)
]
KNOWN_OUT = 11_500_000.0


def _companies():
    rows = [company("U_S0", okved="46.90", group="group_s0_sb")]
    rows += [company(cid, okved=code, group=f"group_{cid}_sb") for cid, code, _ in SUPPLIERS]
    rows.append(company("U_S7", okved="47.11", group="group_s7_sb"))
    return rows


def _payments():
    rows = [pay(cid, "U_S0", amt, "1") for cid, _, amt in SUPPLIERS]
    rows.append(pay("U_XS", "U_S0", "10000000.0", "1"))   # неизвестный получатель: в коды не попадает
    rows.append(pay("U_S0", "U_S7", "3000000.0", "2"))    # входящий от розницы
    return rows


def _build(rules=None) -> ProfileService:
    d = write_dataset(Path(tempfile.mkdtemp(prefix="cp_sc_")), companies=_companies(), persons=[],
                      payments=_payments())
    return ProfileService(validate(load_raw(d)), rules or load_rules(), UserStore.from_records([], load_roles()))


@functools.lru_cache(maxsize=1)
def _svc() -> ProfileService:
    return _build()


def _sc(profile):
    return next(f for f in profile["sensitivity_factors"] if f["code"] == "supply_chain_industries")


def test_summary_format_preserved():
    d = _sc(_svc().build_profile("U_S0"))["details"]
    assert [x["okved_division"] for x in d["suppliers"]] == ["45", "07", "41"]
    first = d["suppliers"][0]
    assert set(first) == {"okved_division", "okved_section", "okved_section_name", "pay_amt", "n_counterparties",
                          "example_okved_codes", "share_of_known"}
    assert first["pay_amt"] == 7_000_000.0 and first["n_counterparties"] == 3
    assert first["example_okved_codes"] == ["45.31.1", "45.32"]
    # основной синтетический набор: прежние значения не изменились
    old = _sc(service().build_profile("U_T1"))["details"]
    assert [x["okved_division"] for x in old["customers"]] == ["10"]


def test_codes_aggregated_by_full_code():
    d = _sc(_svc().build_profile("U_S0"))["details"]
    codes = {x["okved_code"]: x for x in d["supplier_codes"]}
    assert list(codes) == ["45.31.1", "07.29.41", "45.32", "41.20", "41.2"]   # по сумме, затем по коду
    assert codes["45.31.1"]["pay_amt"] == 5_000_000.0 and codes["45.31.1"]["n_counterparties"] == 2
    assert codes["45.31.1"]["okved_levels"] == ["45", "45.3", "45.31", "45.31.1"]
    assert codes["41.2"]["okved_levels"] == ["41", "41.2"]
    assert codes["45.31.1"]["share_of_known"] == round(5 / 11.5, 4)
    assert abs(sum(x["pay_amt"] for x in d["supplier_codes"]) - KNOWN_OUT) < 1e-6
    assert d["supplier_codes_meta"] == {"n_codes": 5, "truncated": False, "omitted_share_of_known": 0.0}
    assert [x["okved_code"] for x in d["customer_codes"]] == ["47.11"]
    assert "U_S" not in json.dumps(d["supplier_codes"])  # детализация без id контрагентов


def test_exact_prefix_matching():
    p = _svc().build_profile("U_S0")

    def hits(*prefixes):
        return sorted({(m["direction"], m["okved_code"]) for m in match_supply_chain(list(prefixes), p)})

    assert hits("45.3") == [("suppliers", "45.31.1"), ("suppliers", "45.32")]
    assert hits("45.32") == [("suppliers", "45.32")]          # сосед 45.31.1 не совпадает
    assert hits("45.31") == [("suppliers", "45.31.1")]
    assert hits("41.2") == [("suppliers", "41.2"), ("suppliers", "41.20")]
    assert hits("41.20") == [("suppliers", "41.20")]          # менее точный код 41.2 не совпадает
    assert hits("07.29.4") == [("suppliers", "07.29.41")]
    assert hits("07.29.42") == []
    assert hits("47") == [("customers", "47.11")]
    assert hits("46") == []                                   # собственный ОКВЭД хаба — не цепочка поставок
    assert hits("24") == []


def test_invalid_prefixes_rejected_not_ignored():
    p = _svc().build_profile("U_S0")
    for bad in (["4"], ["45."], ["45.3.1"], ["4.5"], ["1"], [45]):
        expect_raises(InvalidOkvedPrefix, match_supply_chain, bad, p)
        expect_raises(InvalidOkvedPrefix, match_company, bad, ["45", "45.3"])
    assert match_company(["45.3", "45.3"], ["45", "45.3", "45.31"]) == ["45.3"]  # дубли схлопываются


def test_rule_shares_use_deep_prefixes():
    d = _sc(_svc().build_profile("U_S0"))["details"]
    assert d["rule_shares"]["precious_metals"] == round(3 / 11.5, 4)   # 07.29.4 ⊂ 07.29.41
    assert d["rule_shares"]["auto"] == round(7 / 11.5, 4)
    assert d["rule_shares"]["construction_real_estate"] == round(1.5 / 11.5, 4)
    assert d["rule_shares"]["retail_trade"] == 1.0                      # входящие: только 47.11
    assert d["topic_shares"]["gold"] == round(3 / 11.5, 4)             # >= min_share_for_topics 0.2
    assert "construction" not in d["topic_shares"]                      # 0.13 < 0.2
    topics = {t["topic"]: t for t in _svc().build_profile("U_S0")["topics"]}
    assert "factor:supply_chain_industries" in [s["source"] for s in topics["gold"]["sources"]]


def test_truncation_keeps_largest_and_reports_omitted():
    rules = copy.deepcopy(load_rules())
    rules["thresholds"]["supply_chain"]["top_codes"] = 2
    d = _sc(_build(rules).build_profile("U_S0"))["details"]
    assert [x["okved_code"] for x in d["supplier_codes"]] == ["45.31.1", "07.29.41"]
    assert d["supplier_codes_meta"] == {"n_codes": 5, "truncated": True,
                                        "omitted_share_of_known": round(3.5 / 11.5, 4)}
    assert d["rule_shares"]["auto"] == round(7 / 11.5, 4)   # доли считаются по всем кодам, не по обрезанным


def test_unknown_supply_chain_has_full_details_shape():
    d = _sc(service().build_profile("U_T4"))["details"]   # нет платежей
    assert d["supplier_codes"] == [] and d["customer_codes"] == []
    assert d["supplier_codes_meta"] == {"n_codes": 0, "truncated": False, "omitted_share_of_known": None}
    assert d["rule_shares"] == {} and d["topic_shares"] == {}


def test_prompt_view_has_no_code_detail_or_ids():
    view = json.dumps(build_prompt_view(_svc().build_profile("U_S0")), ensure_ascii=False)
    assert "U_S" not in view and "okved_levels" not in view
