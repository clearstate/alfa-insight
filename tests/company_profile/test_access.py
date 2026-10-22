"""user_context и права доступа (синтетические пользователи)."""
from services.company_profile.access import AccessDenied, UserNotFound, UserStore, load_roles
from services.company_profile.service import CompanyNotFound, CompanyQuarantined

from .synthetic import expect_raises, service


def test_user_companies_statuses():
    svc = service()
    res = svc.user_companies(svc.get_user("u_acc"))
    assert res["role"] == "chief_accountant" and res["synthetic"] is True
    status = {c["company_id"]: c["status"] for c in res["companies"]}
    assert status == {"U_T3": "ok", "U_GONE": "not_found", "U_T6": "quarantined"}
    assert "taxes" in res["priority_topics"]


def test_foreign_company_forbidden():
    svc = service()
    expect_raises(AccessDenied, svc.authorize, svc.get_user("u_acc"), "U_T1")


def test_own_company_allowed():
    svc = service()
    svc.authorize(svc.get_user("u_cfo"), "U_T1")


def test_unknown_company_checked_before_access():
    svc = service()
    expect_raises(CompanyNotFound, svc.authorize, svc.get_user("u_cfo"), "U_NOPE")
    expect_raises(CompanyQuarantined, svc.authorize, svc.get_user("u_acc"), "U_T6")


def test_unknown_user():
    expect_raises(UserNotFound, service().get_user, "nobody")


def test_unknown_role_rejected():
    expect_raises(ValueError, UserStore.from_records, [{"user_id": "x", "role": "intern", "company_ids": []}],
                  load_roles())


def test_all_roles_have_config():
    roles = load_roles()
    assert set(roles) == {"owner", "ceo", "cfo", "chief_accountant", "treasury", "other_c_level", "other"}
    assert roles["cfo"]["priority_topics"][0] == "key_rate"
