"""Сборка company_profile (синтетические данные)."""
import json

from services.company_profile.prompt_view import build_prompt_view
from services.company_profile.service import CompanyNotFound

from .synthetic import EXPECTED_INCOMING_T1, expect_raises, service


def _factor(p, code):
    return next(f for f in p["sensitivity_factors"] if f["code"] == code)


def test_full_profile():
    p = service().build_profile("U_T1")
    assert p["company_id"] == "U_T1" and p["schema_version"] == "0.3.0"
    assert p["data_run_id"] is None  # CSV-режим
    code = p["industry"]["okved_code"]
    assert code == {"value": "47.11", "claim_type": "fact", "source_file": "df_Uid_data_hack.csv",
                    "source_row_id": "line:2", "source_field": "MAINOKVED_CODE", "as_of": None,
                    "method": None, "confidence": None}
    assert p["industry"]["okved_section"]["value"] == "G"
    assert p["industry"]["okved_levels"]["value"] == ["47", "47.1", "47.11"]
    assert p["size"]["revenue"]["value"] == 20_000_000_000.0
    assert (p["size"]["revenue_unit"]["value"], p["size"]["revenue_period"]["value"]) == ("RUB", "2025")  # вебинар, вопрос 14
    assert p["size"]["is_large_business"]["value"] is True
    assert p["size"]["is_large_business"]["claim_type"] == "inference"
    assert p["size"]["is_large_business"]["confidence"] == "high"          # по выручке самого юрлица
    assert p["foreign_trade"]["countries"]["value"] == ["КИТАЙ", "ТУРЦИЯ"]
    assert p["foreign_trade"]["direction"]["claim_type"] == "unknown"
    assert p["bank_relationship"]["products"]["loans"]["value"] is True
    assert "restricted" not in p and "NEGATIVEMARK" not in json.dumps(p)  # минимизация
    assert "no_dates" in {g["code"] for g in p["data_gaps"]}
    assert "revenue_unit_unknown" not in {g["code"] for g in p["data_gaps"]}
    json.dumps(p, ensure_ascii=False)  # сериализуемо


def test_factors_full_profile():
    p = service().build_profile("U_T1")
    assert _factor(p, "rate_sensitivity")["level"] == "high"
    assert _factor(p, "deposit_income")["level"] == "medium"
    fx = _factor(p, "fx_and_trade_exposure")
    assert fx["level"] == "high" and fx["details"]["countries"] == ["КИТАЙ", "ТУРЦИЯ"]
    assert _factor(p, "consumer_exposure")["level"] == "high"
    assert _factor(p, "payroll_exposure")["level"] == "high"
    for f in p["sensitivity_factors"]:
        assert f["claim_type"] == "inference" and f["rule_id"] and f["rationale"] and f["based_on"]


def test_missing_revenue():
    p = service().build_profile("U_T2")
    rev = p["size"]["revenue"]
    assert rev["value"] is None and rev["claim_type"] == "unknown" and rev["source_field"] == "REVENUE_COMPANY"
    # своя выручка неизвестна, но группа group_1_sb (U_T1, 20 млрд) — крупный бизнес: сегмент по группе (вопрос 16)
    large = p["size"]["is_large_business"]
    assert (large["value"], large["confidence"]) == (True, "medium") and "группы" in large["method"]
    codes = {g["code"] for g in p["data_gaps"]}
    assert {"revenue_missing", "eco_stage_missing", "product_meaning_unconfirmed"} <= codes


def test_unknown_company_not_found():
    expect_raises(CompanyNotFound, service().build_profile, "U_NOPE")
    expect_raises(CompanyNotFound, service().get_related, "U_NOPE")


def test_shared_group():
    p = service().build_profile("U_T1")
    assert p["group"]["group_id"]["value"] == "group_1_sb"
    assert p["group"]["size"] == 2 and p["group"]["members"] == ["U_T2"]
    rel = service().get_related("U_T1", types=["same_group"])
    assert [r["company_id"] for r in rel["relations"]] == ["U_T2"]


def test_shared_person():
    p = service().build_profile("U_T1")
    links = {x["company_id"]: x for x in p["related_by_people"]}
    assert set(links) == {"U_T2", "U_T3"}
    assert links["U_T3"]["shared_persons"] == 1 and links["U_T3"]["same_group"] is False
    assert links["U_T2"]["same_group"] is True
    assert all(x["relation_type"] == "shared_person" for x in p["related_by_people"])


def test_multiple_counterparties():
    inc = service().build_profile("U_T1")["counterparties"]["incoming"]
    assert inc["total_amt"] == EXPECTED_INCOMING_T1["total_amt"]
    assert inc["n_counterparties"] == EXPECTED_INCOMING_T1["n_counterparties"]
    top = inc["top"][0]
    assert top["company_id"] == EXPECTED_INCOMING_T1["top_id"]
    assert top["pay_amt"] == EXPECTED_INCOMING_T1["top_amt"] and top["pay_cnt"] == EXPECTED_INCOMING_T1["top_cnt"]
    assert top["known"] is True and top["okved_code"] == "10.11"
    assert abs(sum(e["share"] for e in inc["top"]) - 1.0) < 1e-3
    assert inc["known_coverage"] == round(7 / 11, 4)
    assert [e["pay_amt"] for e in inc["top"]] == sorted((e["pay_amt"] for e in inc["top"]), reverse=True)


def test_self_payments_excluded_from_shares():
    c = service().build_profile("U_T1")["counterparties"]
    assert c["self_payments_excluded"] == {"pay_amt": 100_000_000.0, "pay_cnt": 10, "n_rows": 1}
    assert "U_T1" not in {e["company_id"] for e in c["incoming"]["top"] + c["outgoing"]["top"]}


def test_concentration_rules():
    p1 = service().build_profile("U_T1")
    conc = _factor(p1, "counterparty_concentration")
    assert conc["details"]["incoming"]["level"] == "high"      # 7/11 >= 0.5 при 5 контрагентах
    assert conc["confidence"] == "low"
    assert "критичес" not in conc["rationale"].lower()
    p3 = service().build_profile("U_T3")
    assert _factor(p3, "counterparty_concentration")["level"] == "unknown"  # 1 контрагент < min


def test_no_payments():
    p = service().build_profile("U_T4")
    assert p["counterparties"]["incoming"]["n_counterparties"] == 0
    assert p["counterparties"]["self_payments_excluded"] is None
    assert any(g["code"] == "no_payments" for g in p["data_gaps"])
    assert _factor(p, "supply_chain_industries")["level"] == "unknown"


def test_workers_conflict():
    p = service().build_profile("U_T1")
    assert p["size"]["workers_fns"]["value"] == "Более 251"
    assert p["size"]["workers_spark"]["value"] == "101-250"
    assert p["size"]["workers_conflict"]["value"] is True
    assert any(g["code"] == "workers_conflict" for g in p["data_gaps"])
    p4 = service().build_profile("U_T4")
    assert p4["size"]["workers_conflict"]["claim_type"] == "unknown"


def test_supply_chain_uses_known_counterparties_only():
    sc = _factor(service().build_profile("U_T1"), "supply_chain_industries")
    assert [x["okved_division"] for x in sc["details"]["customers"]] == ["10"]
    assert sc["details"]["known_coverage_incoming"] == round(7 / 11, 4)


def test_topics_weighted_with_sources():
    topics = service().build_profile("U_T1")["topics"]
    names = [t["topic"] for t in topics]
    assert "consumer_demand" in names and "key_rate" in names and "fx_rates" in names
    for t in topics:
        assert 0 < t["weight"] <= 1.0 and t["sources"]


def test_related_types_and_payments():
    rel = service().get_related("U_T1")
    by_id = {r["company_id"]: r for r in rel["relations"]}
    assert set(by_id["U_T3"]["relation_types"]) == {"shared_person", "payment_in", "payment_out"}
    assert by_id["U_T3"]["pay_amt_in"] == 7_000_000.0 and by_id["U_T3"]["pay_amt_out"] == 3_000_000.0
    assert by_id["U_X1"]["known"] is False and by_id["U_X1"]["okved_code"] is None
    assert rel["total"] == len(rel["relations"])
    limited = service().get_related("U_T1", limit=2)
    assert len(limited["relations"]) == 2 and limited["truncated"] is True


def test_prompt_view_is_minimized():
    view = build_prompt_view(service().build_profile("U_T1"))
    dumped = json.dumps(view, ensure_ascii=False)
    assert "U_T" not in dumped and "U_X" not in dumped and "F_T" not in dumped
    assert "negative" not in dumped.lower()
    assert view["size"]["revenue_magnitude"] == "~1e10"


def test_profile_is_cached_and_deterministic():
    svc = service()
    assert svc.build_profile("U_T3") is svc.build_profile("U_T3")


def test_revenue_placeholder_and_group_segment():
    """Вебинар: выручка 1000 — заглушка (вопрос 15); крупный бизнес — по выручке группы (вопрос 16)."""
    import tempfile
    from pathlib import Path

    from services.company_profile.features import load_rules
    from services.company_profile.loader import load_raw
    from services.company_profile.service import ProfileService
    from services.company_profile.validation import validate

    from .synthetic import company, write_dataset
    rows = [company("U_P1", revenue="1000.0", group="group_p_sb"),               # заглушка, единственный в группе
            company("U_G1", revenue="9000000000.0", group="group_g_sb"),          # 9 + 7 млрд = 16 млрд по группе
            company("U_G2", revenue="7000000000.0", group="group_g_sb"),
            company("U_G3", revenue="1000.0", group="group_g_sb"),               # заглушка не входит в сумму
            company("U_S1", revenue="14000000000.0", group="group_s_sb")]        # одна, ниже порога
    data = validate(load_raw(write_dataset(Path(tempfile.mkdtemp(prefix="cp_rev_")), companies=rows, persons=[], payments=[])))
    svc = ProfileService(data, load_rules(), None)
    p1 = svc.build_profile("U_P1")
    assert p1["size"]["revenue"]["value"] is None
    assert p1["size"]["is_large_business"]["claim_type"] == "unknown"
    assert "revenue_missing" in {g["code"] for g in p1["data_gaps"]}
    assert "revenue_placeholder" in {i.code for i in data.company_issues["U_P1"]}
    g1 = svc.build_profile("U_G1")
    assert g1["group"]["group_revenue_sum"]["value"] == 16_000_000_000.0
    assert (g1["size"]["is_large_business"]["value"], g1["size"]["is_large_business"]["confidence"]) == (True, "medium")
    assert svc.build_profile("U_G3")["size"]["is_large_business"]["value"] is True
    assert svc.build_profile("U_S1")["size"]["is_large_business"]["value"] is False
    assert svc.company_summary("U_G2")["is_large_business"] is True
    from services.company_profile.etl import profile_scope
    assert profile_scope(svc, "large", []) == ["U_G1", "U_G2", "U_G3"]

