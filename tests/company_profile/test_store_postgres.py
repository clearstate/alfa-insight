"""Интеграционные тесты на ЖИВОМ PostgreSQL.

Запуск: COMPANY_PROFILE_TEST_DATABASE_URL=postgresql://cp:cp@localhost:5433/cp_test uv run pytest tests/company_profile -k postgres
ВНИМАНИЕ: тест перезаписывает схему company_profile в указанной базе — используйте отдельную тестовую БД
(docker compose -f docker-compose.company_profile.yml --profile test up -d postgres-test).
"""
import json
import os

import pytest

psycopg = pytest.importorskip("psycopg")
URL = os.getenv("COMPANY_PROFILE_TEST_DATABASE_URL")
if not URL:
    pytest.skip("COMPANY_PROFILE_TEST_DATABASE_URL не задан", allow_module_level=True)

from services.company_profile.db import SqlStore  # noqa: E402
from services.company_profile.etl import run_etl  # noqa: E402
from services.company_profile.service import ProfileService  # noqa: E402

from .synthetic import dataset_dir, service  # noqa: E402


def _strip(p):
    p = json.loads(json.dumps(p, ensure_ascii=False))
    p.pop("built_at"), p.pop("data_run_id")
    return p


@pytest.fixture(scope="module")
def etl_result():
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS company_profile CASCADE")
    return run_etl(dataset_dir(), URL, profiles="all")


def test_roundtrip_identical_to_csv(etl_result):
    store = SqlStore.connect(URL)
    svc = ProfileService.from_store(store)
    store.close()
    assert svc.storage == "postgres" and svc.data_run_id == etl_result["run_id"]
    for cid in ["U_T1", "U_T2", "U_T3", "U_T4", "U_T5", "U_T7"]:
        assert _strip(svc.build_profile(cid)) == _strip(service().build_profile(cid))
        assert svc.get_related(cid) == service().get_related(cid)


def test_jsonb_queries_for_ranking(etl_result):
    with psycopg.connect(URL) as conn:
        rows = conn.execute(
            "SELECT company_id FROM company_profile.company_profiles WHERE okved_levels ?| %s ORDER BY 1",
            (["47", "56"],)).fetchall()
        assert [r[0] for r in rows] == ["U_T1"]
        rows = conn.execute(
            "SELECT company_id FROM company_profile.company_profiles WHERE topic_names ? 'key_rate' ORDER BY 1"
        ).fetchall()
        assert "U_T1" in [r[0] for r in rows]
        lvl = conn.execute(
            "SELECT f->>'level' FROM company_profile.company_profiles p, "
            "jsonb_array_elements(p.profile->'sensitivity_factors') f "
            "WHERE p.company_id = 'U_T1' AND f->>'code' = 'rate_sensitivity'").fetchone()[0]
        assert lvl == "high"


def test_rerun_and_types(etl_result):
    second = run_etl(dataset_dir(), URL, profiles="large")
    with psycopg.connect(URL) as conn:
        n = conn.execute("SELECT count(*) FROM company_profile.companies").fetchone()[0]
        assert n == etl_result["counts"]["companies"]
        b = conn.execute("SELECT cl_product_loa_mark, revenue_company FROM company_profile.companies "
                         "WHERE synthetic_u = 'U_T1'").fetchone()
        assert b == (True, 20_000_000_000.0)
        st = conn.execute("SELECT status FROM company_profile.etl_runs WHERE run_id = %s",
                          (second["run_id"],)).fetchone()[0]
        assert st == "success"
