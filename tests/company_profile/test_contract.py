"""Соответствие ответов сервиса контракту Pydantic (contracts/company_profile.py).
Требует pydantic v2; без него модуль пропускается."""
import pytest

pytest.importorskip("pydantic")

from contracts.company_profile import (  # noqa: E402
    CompanyProfile, DemoCompany, HealthResponse, RelatedResponse, SupplyChainDetails, UserCompaniesResponse,
)

from .synthetic import service  # noqa: E402


@pytest.mark.parametrize("cid", ["U_T1", "U_T2", "U_T3", "U_T4", "U_T5", "U_T7"])
def test_profile_matches_contract(cid):
    model = CompanyProfile.model_validate(service().build_profile(cid))
    assert model.company_id == cid


def test_related_matches_contract():
    RelatedResponse.model_validate(service().get_related("U_T1"))


@pytest.mark.parametrize("uid", ["u_cfo", "u_acc", "u_ceo"])
def test_user_companies_matches_contract(uid):
    svc = service()
    UserCompaniesResponse.model_validate(svc.user_companies(svc.get_user(uid)))


def test_demo_matches_contract():
    for item in service().select_demo_companies(5):
        DemoCompany.model_validate(item)


def test_health_matches_contract():
    HealthResponse.model_validate(service().health())


@pytest.mark.parametrize("cid", ["U_T1", "U_T3", "U_T4"])
def test_supply_chain_details_match_contract(cid):
    f = next(x for x in service().build_profile(cid)["sensitivity_factors"] if x["code"] == "supply_chain_industries")
    SupplyChainDetails.model_validate(f["details"])
