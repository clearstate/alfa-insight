"""Загрузка и валидация (синтетические данные)."""
from pathlib import Path
import tempfile

from services.company_profile.loader import DataFormatError, load_raw
from services.company_profile.service import CompanyQuarantined

from .synthetic import expect_raises, service, write_dataset


def test_exact_duplicate_row_deduplicated():
    svc = service()
    assert "U_T5" in svc.data.companies.index
    codes = [i.code for i in svc.data.company_issues["U_T5"]]
    assert "duplicate_row" in codes
    p = svc.build_profile("U_T5")
    assert any(i["code"] == "duplicate_row" for i in p["quality_issues"])


def test_id_collision_quarantined():
    svc = service()
    assert "U_T6" in svc.data.quarantined and len(svc.data.quarantined["U_T6"]) == 2
    expect_raises(CompanyQuarantined, svc.build_profile, "U_T6")


def test_invalid_payment_amounts_dropped():
    rep = service().data.report
    assert rep.counters["invalid_pay_amt"] == 3        # "abc", "-5", "0"
    assert rep.counters["invalid_pay_cnt"] == 1        # "1.5"
    p = service().build_profile("U_T1")
    ids = {e["company_id"] for e in p["counterparties"]["incoming"]["top"]}
    assert not ids & {"U_X5", "U_X6", "U_X7", "U_X8"}


def test_self_payments_separated_and_pairs_aggregated():
    svc = service()
    assert svc.data.report.stats["payments_self_rows"] == 1
    assert svc.data.report.counters["duplicate_payment_pair"] == 1
    assert ((svc.data.payments["PAYER"] == svc.data.payments["BENEFICIARY"]).sum()) == 0


def test_invalid_mark_becomes_unknown():
    p = service().build_profile("U_T7")
    dep = p["bank_relationship"]["products"]["deposits"]
    assert dep["value"] is None and dep["claim_type"] == "unknown"
    assert any(i["code"] == "invalid_mark" and i["field"] == "CL_PRODUCT_DEP_MARK" for i in p["quality_issues"])


def test_fts_inconsistent_flagged():
    p = service().build_profile("U_T7")
    assert p["foreign_trade"]["consistent"] is False
    assert p["foreign_trade"]["has_foreign_trade"]["confidence"] == "low"
    assert any(g["code"] == "fts_inconsistent" for g in p["data_gaps"])


def test_person_links_dedup_and_unknown_company():
    svc = service()
    assert svc.data.report.counters["duplicate_person_link"] == 1
    assert svc.data.report.stats["person_links_unknown_company"] == 1


def test_missing_columns_raise():
    d = Path(tempfile.mkdtemp(prefix="cp_bad_"))
    write_dataset(d)
    (d / "df_Uid_payment_hack.csv").write_text("BENEFICIARY;PAYER\nU_1;U_2\n", encoding="utf-8")
    err = expect_raises(DataFormatError, load_raw, d)
    assert "PAY_AMT" in str(err)


def test_missing_file_raises():
    d = Path(tempfile.mkdtemp(prefix="cp_empty_"))
    expect_raises(DataFormatError, load_raw, d)
