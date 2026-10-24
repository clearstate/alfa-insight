"""Приложение модуля news_ingest.

Запуск:  uvicorn services.news_ingest.main:create_app --factory --host 0.0.0.0 --port 8002
ENV: NEWS_DB_URL (sqlite:///data/news_ingest.db | postgresql://...), NEWS_BOOTSTRAP_BANK=1 (загрузить 9 документов при старте),
     NEWS_STANDALONE_AUTH=token + NEWS_API_TOKENS (автономный запуск: Bearer-токены, см. auth_shim) | demo (только локально),
     NEWS_INGEST_USERS (кому разрешён ингест) / NEWS_INGEST_OPEN=1 (ингест всем аутентифицированным — только демо),
     LLM_* (см. llm.py), NEWS_ALLOWED_DOMAINS (через запятую; пусто = любые публичные).
Обход лент по расписанию — отдельный процесс: `python -m services.news_ingest.cli schedule --loop` (scheduler.py).
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from services.company_profile import errors
from services.company_profile.router import current_user

from .api import router, token_user
from .auth_shim import StandaloneAuth, TokenAuth
from .pipeline import IngestPipeline, build_pipeline
from .store import NewsStore

log = logging.getLogger("news_ingest")


def build(store: NewsStore | None = None) -> tuple[NewsStore, IngestPipeline]:
    store = store or NewsStore(os.getenv("NEWS_DB_URL", "sqlite:///data/news_ingest.db"))
    store.init_schema()
    pipe = build_pipeline(store)
    if os.getenv("NEWS_BOOTSTRAP_BANK") == "1":
        pipe.ingest_bank_dir()
    return store, pipe


def create_app(store: NewsStore | None = None, auth_service=None) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(title="Alfa Insight — news_ingest", version="0.1.0")
    errors.install(app)
    app.include_router(router)
    # Авторизация настраивается до загрузки данных: ошибка конфигурации не должна оставлять полузапущенный сервис.
    # current_user (company_profile.router) читает app.state.profile_service; в общем приложении его задаёт участник 6.
    mode = os.getenv("NEWS_STANDALONE_AUTH", "")
    if auth_service is not None:
        app.state.profile_service = auth_service
    elif mode == "token":
        try:
            app.state.news_token_auth = TokenAuth(os.getenv("NEWS_API_TOKENS"))
        except ValueError as e:
            raise RuntimeError(str(e)) from None
        app.dependency_overrides[current_user] = token_user
    elif mode == "demo":
        log.warning("NEWS_STANDALONE_AUTH=demo: любой X-User-ID принимается без проверки — только для локальной разработки, "
                    "не публиковать порт в сеть")
        app.state.profile_service = StandaloneAuth()
    else:
        raise RuntimeError("Нет сервиса авторизации: смонтируйте роутер в общее приложение (app.state.profile_service) или задайте "
                           "NEWS_STANDALONE_AUTH=token и NEWS_API_TOKENS (NEWS_STANDALONE_AUTH=demo — только локально)")
    if os.getenv("NEWS_INGEST_OPEN") == "1":
        log.warning("NEWS_INGEST_OPEN=1: запуск ингеста разрешён любому аутентифицированному пользователю — только для демо")
    app.state.news_store, app.state.news_pipeline = build(store)
    return app
