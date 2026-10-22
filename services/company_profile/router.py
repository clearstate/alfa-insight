"""HTTP API модуля company_profile.

GET /api/users/me/companies
GET /api/companies/{company_id}/profile
GET /api/companies/{company_id}/related
GET /api/companies/demo  (только при COMPANY_PROFILE_DEMO_ENDPOINTS=1)
GET /api/company-profile/health  (без аутентификации: только счётчики, для healthcheck)

Аутентификация в прототипе — заглушка: заголовок X-User-ID с id синтетического пользователя.
Реальная аутентификация и сессия — зона участника 6.
Порядок проверок: 401 (нет пользователя) -> 404/422 (нет компании / id в карантине) -> 403 (нет доступа).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, Query, Request

from contracts.company_profile import (
    CompanyProfile, DemoCompany, ErrorResponse, HealthResponse, RelatedResponse, RelationType,
    UserCompaniesResponse,
)

from .access import AccessDenied, UserContext, UserNotFound
from .errors import ApiError, audit
from .service import CompanyNotFound, CompanyQuarantined, ProfileService

USER_HEADER = "X-User-ID"
_ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 422)}

router = APIRouter(prefix="/api", tags=["company_profile"])


def get_service(request: Request) -> ProfileService:
    return request.app.state.profile_service


def current_user(
    request: Request,
    x_user_id: str | None = Header(default=None, alias=USER_HEADER),
    svc: ProfileService = Depends(get_service),
) -> UserContext:
    if not x_user_id:
        audit("auth_failed", request, reason="missing_user_header")
        raise ApiError(401, "unauthenticated", f"Требуется заголовок {USER_HEADER}")
    try:
        return svc.get_user(x_user_id)
    except UserNotFound:
        audit("auth_failed", request, reason="unknown_user")
        raise ApiError(401, "unauthenticated", "Пользователь не найден")


def _authorized(request: Request, svc: ProfileService, user: UserContext, company_id: str, action: str) -> None:
    try:
        svc.authorize(user, company_id)
    except CompanyNotFound:
        audit(action, request, user_id=user.user_id, company_id=company_id, outcome="not_found")
        raise ApiError(404, "company_not_found", "Компания не найдена", {"company_id": company_id})
    except CompanyQuarantined:
        audit(action, request, user_id=user.user_id, company_id=company_id, outcome="quarantined")
        raise ApiError(422, "company_id_ambiguous",
                       "Идентификатор компании неоднозначен в исходных данных; профиль не строится",
                       {"company_id": company_id})
    except AccessDenied:
        audit(action, request, user_id=user.user_id, company_id=company_id, outcome="forbidden")
        raise ApiError(403, "forbidden", "Нет доступа к этой компании", {"company_id": company_id})


@router.get("/company-profile/health", response_model=HealthResponse)
def health(svc: ProfileService = Depends(get_service)):
    return svc.health()


@router.get("/users/me/companies", response_model=UserCompaniesResponse, responses=_ERRORS)
def my_companies(request: Request, user: UserContext = Depends(current_user),
                 svc: ProfileService = Depends(get_service)):
    audit("list_companies", request, user_id=user.user_id, outcome="ok", count=len(user.company_ids))
    return svc.user_companies(user)


@router.get("/companies/demo", response_model=list[DemoCompany], responses=_ERRORS)
def demo_companies(request: Request, n: int = Query(default=5, ge=1, le=6),
                   user: UserContext = Depends(current_user), svc: ProfileService = Depends(get_service)):
    if os.getenv("COMPANY_PROFILE_DEMO_ENDPOINTS") != "1":
        raise ApiError(404, "not_found", "Эндпоинт отключён")
    audit("demo_companies", request, user_id=user.user_id, outcome="ok")
    return svc.select_demo_companies(n)


@router.get("/companies/{company_id}/profile", response_model=CompanyProfile, responses=_ERRORS)
def company_profile(company_id: str, request: Request, user: UserContext = Depends(current_user),
                    svc: ProfileService = Depends(get_service)):
    _authorized(request, svc, user, company_id, "get_profile")
    profile = svc.build_profile(company_id)
    audit("get_profile", request, user_id=user.user_id, company_id=company_id, outcome="ok")
    return profile


@router.get("/companies/{company_id}/related", response_model=RelatedResponse, responses=_ERRORS)
def company_related(company_id: str, request: Request,
                    limit: int = Query(default=100, ge=1, le=500),
                    types: list[RelationType] | None = Query(default=None),
                    user: UserContext = Depends(current_user), svc: ProfileService = Depends(get_service)):
    _authorized(request, svc, user, company_id, "get_related")
    result = svc.get_related(company_id, limit=limit, types=list(types) if types else None)
    audit("get_related", request, user_id=user.user_id, company_id=company_id, outcome="ok",
          returned=len(result["relations"]))
    return result
