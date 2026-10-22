"""HTTP-слой модуля news_ingest (FastAPI). Интеграция в общий сервис (участник 6):
    errors.install(app); app.include_router(news_router); app.state.news_store = store; app.state.news_pipeline = pipeline

Авторизация — как у company_profile: заголовок X-User-ID (current_user). Новости не персональны, поэтому читать может любой
аутентифицированный пользователь; персональный отбор и ранжирование — участник 4. Запуск ingest — только пользователи из
NEWS_INGEST_USERS (через запятую) либо при NEWS_INGEST_OPEN=1 (демо). Каждое обращение пишется в audit-журнал.
ВНИМАНИЕ: файл не запускался в среде разработки (нет fastapi/pydantic) — проверить на docker compose (см. README).
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from contracts.news_item import (Chunk, IndicatorRow, IngestRequest, IngestResponse, NewsCandidate, NewsItem)
from services.company_profile.access import UserContext
from services.company_profile.errors import ApiError, audit, correlation_id
from services.company_profile.router import current_user

from . import indicators as ind
from .pipeline import IngestPipeline
from .store import NewsStore

router = APIRouter(prefix="/api", tags=["news_ingest"])


def get_store(request: Request) -> NewsStore:
    return request.app.state.news_store


def get_pipeline(request: Request) -> IngestPipeline:
    return request.app.state.news_pipeline


def _may_ingest(user: UserContext) -> bool:
    if os.getenv("NEWS_INGEST_OPEN") == "1":
        return True
    return user.user_id in {u.strip() for u in os.getenv("NEWS_INGEST_USERS", "").split(",") if u.strip()}


@router.get("/news/health")
def health(store: NewsStore = Depends(get_store)) -> dict[str, Any]:
    return {"status": "ok", **store.stats()}


@router.post("/news/ingest", response_model=IngestResponse)
def ingest(body: IngestRequest, request: Request, user: UserContext = Depends(current_user),
           pipe: IngestPipeline = Depends(get_pipeline)) -> IngestResponse:
    cid = correlation_id(request)
    if not _may_ingest(user):
        audit("news_ingest", request, user_id=user.user_id, outcome="forbidden")
        raise ApiError(403, "forbidden", "Нет права запускать ингест новостей")
    if body.url:
        res = pipe.ingest_url(body.url, "manual_file", cid)
        if isinstance(res, list):                       # URL оказался RSS-лентой: возвращаем сводный результат
            created = [r for r in res if r.outcome in ("created", "updated")]
            audit("news_ingest", request, user_id=user.user_id, url=body.url, outcome="feed", count=len(res))
            first = created[0] if created else res[0]
            return IngestResponse(**first.to_dict())
    else:
        res = pipe.ingest_text(body.text or "", body.title, published_at=body.published_at, publisher=body.publisher, correlation_id=cid)
    audit("news_ingest", request, user_id=user.user_id, outcome=res.outcome, item_id=res.item_id)
    if res.outcome == "failed":
        code = (res.error or "ingest_failed").split(":")[0]
        status = 422 if code in ("empty_content", "text_too_short") else 502
        raise ApiError(status, code, res.error or "ингест не удался", {"reasons": res.reasons})
    return IngestResponse(**res.to_dict())


@router.get("/news", response_model=list[NewsCandidate])
def list_news(topic: list[str] = Query(default=[]), okved: list[str] = Query(default=[]), region: list[str] = Query(default=[]),
              since: str | None = None, until: str | None = None, source_type: list[str] = Query(default=[]),
              include_duplicates: bool = False, limit: int = Query(100, ge=1, le=500),
              user: UserContext = Depends(current_user), store: NewsStore = Depends(get_store)):
    return store.search_candidates(topic or None, okved or None, region or None, since, until, source_type or None,
                                   include_duplicates, limit)


@router.get("/news/changes")
def changes(since_id: int = 0, limit: int = Query(500, ge=1, le=1000), user: UserContext = Depends(current_user),
            store: NewsStore = Depends(get_store)):
    """События ингеста для участника 4 (поллинг: created/updated/duplicate) — вместо push-уведомлений."""
    return store.changes_since(since_id, limit)


@router.get("/news/{item_id}", response_model=NewsItem)
def get_item(item_id: str, user: UserContext = Depends(current_user), store: NewsStore = Depends(get_store)):
    it = store.get_item(item_id)
    if it is None:
        raise ApiError(404, "news_not_found", "Новость не найдена", {"item_id": item_id})
    return it


@router.get("/news/{item_id}/chunks", response_model=list[Chunk])
def get_chunks(item_id: str, user: UserContext = Depends(current_user), store: NewsStore = Depends(get_store)):
    if store.get_row(item_id) is None:
        raise ApiError(404, "news_not_found", "Новость не найдена", {"item_id": item_id})
    return store.list_chunks(item_id)


@router.get("/indicators", response_model=list[IndicatorRow])
def indicators(indicator: str | None = None, period: str | None = None, forecast_only: bool = False,
               user: UserContext = Depends(current_user), store: NewsStore = Depends(get_store)):
    return store.indicators(indicator, period, forecast_only)


@router.get("/indicators/conflicts")
def indicator_conflicts(user: UserContext = Depends(current_user), store: NewsStore = Depends(get_store)):
    """Расхождения прогнозов банка между документами; действует значение из самого позднего (latest)."""
    return ind.compare_forecasts(store.indicators(forecast_only=True))


@router.get("/pipeline/errors")
def pipeline_errors(limit: int = Query(100, ge=1, le=500), user: UserContext = Depends(current_user),
                    store: NewsStore = Depends(get_store)):
    return store.errors(limit)
