"""Хранилище и ETL на SQLite (тот же код, что для PostgreSQL, кроме DDL-типов и COPY)."""
import json
import sqlite3
import tempfile
from pathlib import Path

from services.company_profile.db import SQLiteDialect, PostgresDialect, SqlStore, T, render_ddl
from services.company_profile.etl import run_etl
from services.company_profile.service import ProfileService

from .synthetic import dataset_dir, expect_raises, service

ALL_IDS = ["U_T1", "U_T2", "U_T3", "U_T4", "U_T5", "U_T7"]


def _strip_volatile(p: dict) -> dict:
    p = json.loads(json.dumps(p, ensure_ascii=False))
    p.pop("built_at")
    p.pop("data_run_id")
    return p


def _db_url() -> str:
    return "sqlite:///" + str(Path(tempfile.mkdtemp(prefix="cp_db_")) / "cp.db")


def _etl(url: str, profiles: str = "large") -> dict:
    return run_etl(dataset_dir(), url, profiles=profiles)


def test_migrate_idempotent():
    store = SqlStore.connect(_db_url())
    store.migrate()
    store.migrate()
    assert store.count("schema_migrations") == 1
    store.close()


def test_etl_roundtrip_profiles_identical_to_csv():
    url = _db_url()
    result = _etl(url)
    assert result["status"] == "success"
    store = SqlStore.connect(url)
    svc_db = ProfileService.from_store(store)
    store.close()
    svc_csv = service()
    assert svc_db.data_run_id == result["run_id"] and svc_db.storage == "sqlite"
    for cid in ALL_IDS:
        assert _strip_volatile(svc_db.build_profile(cid)) == _strip_volatile(svc_csv.build_profile(cid)), cid
        assert svc_db.get_related(cid) == svc_csv.get_related(cid), cid
    assert svc_db.data.quarantined == svc_csv.data.quarantined
    assert svc_db.quality_report()["counters"] == svc_csv.quality_report()["counters"]
    assert svc_db.build_profile("U_T1")["data_run_id"] == result["run_id"]


def test_marks_roundtrip_as_python_bools():
    url = _db_url()
    _etl(url)
    store = SqlStore.connect(url)
    data = ProfileService.from_store(store).data
    store.close()
    loa = data.companies.at["U_T1", "CL_PRODUCT_LOA_MARK"]
    dep7 = data.companies.at["U_T7", "CL_PRODUCT_DEP_MARK"]
    assert loa is True and dep7 is None


def test_etl_materializes_profiles_users_demo():
    url = _db_url()
    result = _etl(url)
    store = SqlStore.connect(url)
    assert result["counts"]["companies"] == 6  # U_T1..U_T5, U_T7 (U_T6 в карантине, дубль U_T5 удалён)
    assert store.count("quarantined_companies") == 1
    prof = store.get_profile("U_T1")  # единственная крупная компания
    assert prof is not None and prof["data_run_id"] == result["run_id"]
    assert [d["company_id"] for d in result["demo"]] == ["U_T1"]
    assert store.get_profile("U_T3") is None  # не крупная и не демо -> не материализуется
    users = {u["user_id"]: u for u in store.load_users()}
    assert users["u_other_demo"]["company_ids"] == []
    assert all(u["synthetic"] is True for u in users.values())
    run = store.latest_run()
    assert run["status"] == "success" and run["counters"]["id_collision"] == 1
    store.close()


def test_profiles_scope_all_and_none():
    url = _db_url()
    assert _etl(url, "all")["counts"]["company_profiles"] == 6
    url2 = _db_url()
    res = _etl(url2, "none")
    # demo/пользовательские компании материализуются всегда
    assert res["counts"]["company_profiles"] == len({d["company_id"] for d in res["demo"]})


def test_reload_replaces_data():
    url = _db_url()
    first = _etl(url)
    second = _etl(url)
    store = SqlStore.connect(url)
    assert store.count("companies") == first["counts"]["companies"] == second["counts"]["companies"]
    assert store.count("payments") == first["counts"]["payments"]
    assert store.count("etl_runs") == 2
    assert store.latest_run()["run_id"] == second["run_id"]
    store.close()


def test_failed_run_recorded_and_previous_data_kept():
    url = _db_url()
    ok = _etl(url)
    bad_dir = Path(tempfile.mkdtemp(prefix="cp_missing_"))
    expect_raises(Exception, run_etl, bad_dir, url)
    store = SqlStore.connect(url)
    cur = store.conn.cursor()
    cur.execute("SELECT status, error FROM company_profile_etl_runs ORDER BY started_at")
    statuses = cur.fetchall()
    assert [s for s, _ in statuses] == ["success", "failed"] and "not found" in statuses[1][1]
    assert store.latest_run()["run_id"] == ok["run_id"]
    assert store.count("companies") == ok["counts"]["companies"]
    store.close()


def test_from_store_without_runs_fails_clearly():
    store = SqlStore.connect(_db_url())
    store.migrate()
    err = expect_raises(RuntimeError, ProfileService.from_store, store)
    assert "ETL" in str(err)
    store.close()


def test_health_reports_storage_and_rules_match():
    url = _db_url()
    res = _etl(url)
    store = SqlStore.connect(url)
    h = ProfileService.from_store(store).health()
    store.close()
    assert h["storage"] == "sqlite" and h["data_run_id"] == res["run_id"] and h["rules_match_etl"] is True
    assert h["companies"] == 6 and h["users"] == 6


def test_postgres_ddl_shape():
    ddl = "\n".join(render_ddl(PostgresDialect()))
    assert ddl.startswith("CREATE SCHEMA IF NOT EXISTS company_profile")
    assert "company_profile.company_profiles" in ddl and "JSONB" in ddl and "USING GIN (okved_levels)" in ddl
    assert "revenue_company DOUBLE PRECISION" in ddl and "cl_product_loa_mark BOOLEAN" in ddl
    assert "PRIMARY KEY (payer, beneficiary)" in ddl


def test_sqlite_ddl_executes_and_every_table_created():
    conn = sqlite3.connect(":memory:")
    for stmt in render_ddl(SQLiteDialect()):
        conn.execute(stmt)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {f"company_profile_{t}" for t in T}


def test_bad_url_rejected():
    expect_raises(ValueError, SqlStore.connect, "mysql://x")
