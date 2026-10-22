"""HTTP API: коды ответов, формат ошибок, X-Correlation-ID. Требует fastapi и httpx."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from services.company_profile.main import create_app  # noqa: E402

from .synthetic import service  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(service()))


def _err(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    assert body["error"]["correlation_id"] == resp.headers["X-Correlation-ID"]


def test_profile_ok(client):
    r = client.get("/api/companies/U_T1/profile", headers={"X-User-ID": "u_cfo", "X-Correlation-ID": "abc-1"})
    assert r.status_code == 200
    assert r.headers["X-Correlation-ID"] == "abc-1"
    assert r.json()["company_id"] == "U_T1"


def test_no_user_401(client):
    _err(client.get("/api/companies/U_T1/profile"), 401, "unauthenticated")


def test_unknown_user_401(client):
    _err(client.get("/api/companies/U_T1/profile", headers={"X-User-ID": "ghost"}), 401, "unauthenticated")


def test_foreign_company_403(client):
    _err(client.get("/api/companies/U_T1/profile", headers={"X-User-ID": "u_acc"}), 403, "forbidden")


def test_unknown_company_404(client):
    _err(client.get("/api/companies/U_NOPE/profile", headers={"X-User-ID": "u_cfo"}), 404, "company_not_found")


def test_quarantined_422(client):
    _err(client.get("/api/companies/U_T6/profile", headers={"X-User-ID": "u_acc"}), 422, "company_id_ambiguous")


def test_related_with_filter(client):
    r = client.get("/api/companies/U_T1/related", params={"types": "same_group"}, headers={"X-User-ID": "u_cfo"})
    assert r.status_code == 200
    assert [x["company_id"] for x in r.json()["relations"]] == ["U_T2"]


def test_related_bad_type_422(client):
    r = client.get("/api/companies/U_T1/related", params={"types": "owner_of"}, headers={"X-User-ID": "u_cfo"})
    _err(r, 422, "validation_error")


def test_my_companies(client):
    r = client.get("/api/users/me/companies", headers={"X-User-ID": "u_acc"})
    assert r.status_code == 200
    assert {c["status"] for c in r.json()["companies"]} == {"ok", "not_found", "quarantined"}


def test_demo_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("COMPANY_PROFILE_DEMO_ENDPOINTS", raising=False)
    _err(client.get("/api/companies/demo", headers={"X-User-ID": "u_cfo"}), 404, "not_found")


def test_health_without_auth(client):
    r = client.get("/api/company-profile/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["storage"] == "csv" and body["rules_match_etl"] is None
