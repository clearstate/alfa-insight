"""Приложение модуля news_ingest.

Запуск:  uvicorn services.news_ingest.main:create_app --factory --host 0.0.0.0 --port 8002
ENV: NEWS_DB_URL (sqlite:///data/news_ingest.db | postgresql://...), NEWS_BOOTSTRAP_BANK=1 (загрузить 9 документов при старте),
     NEWS_STANDALONE_AUTH=demo (автономный запуск без ProfileService), NEWS_INGEST_USERS / NEWS_INGEST_OPEN, LLM_* (см. llm.py), NEWS_ALLOWED_DOMAINS (через запятую; пусто = любые публичные).
Файл не запускался в среде разработки (нет fastapi) — см. README, раздел «Что проверено».
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from services.company_profile import errors

from .api import router
from .auth_shim import StandaloneAuth
from .fetcher import SafeFetcher
from .llm import LLMClient, OpenAICompatTransport
from .pipeline import IngestPipeline, load_sources
from .store import NewsStore


def build(store: NewsStore | None = None) -> tuple[NewsStore, IngestPipeline]:
    store = store or NewsStore(os.getenv("NEWS_DB_URL", "sqlite:///data/news_ingest.db"))
    store.init_schema()
    sources = load_sources()
    doms = [d.strip() for d in os.getenv("NEWS_ALLOWED_DOMAINS", "").split(",") if d.strip()] or None
    d = next(iter(sources.values()))
    fetcher = SafeFetcher(timeout=d.get("timeout_s", 10), max_bytes=d.get("max_bytes", 5_000_000), retries=d.get("retries", 2),
                          backoff=d.get("backoff_s", 1.0), min_interval=d.get("min_interval_s", 2.0),
                          user_agent=d.get("user_agent", "AlfaInsightBot/0.1"), allowed_domains=doms)
    llm = LLMClient(store, OpenAICompatTransport()) if os.getenv("LLM_BASE_URL") else None
    pipe = IngestPipeline(store, llm=llm, fetcher=fetcher, sources=sources)
    if os.getenv("NEWS_BOOTSTRAP_BANK") == "1":
        pipe.ingest_bank_dir()
    return store, pipe


def create_app(store: NewsStore | None = None, auth_service=None) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(title="Alfa Insight — news_ingest", version="0.1.0")
    errors.install(app)
    app.include_router(router)
    app.state.news_store, app.state.news_pipeline = build(store)
    # current_user (company_profile.router) читает app.state.profile_service; в общем приложении его задаёт участник 6.
    if auth_service is not None:
        app.state.profile_service = auth_service
    elif os.getenv("NEWS_STANDALONE_AUTH") == "demo":
        app.state.profile_service = StandaloneAuth()
    else:
        raise RuntimeError("Нет сервиса авторизации: смонтируйте роутер в общее приложение (app.state.profile_service) "
                           "или задайте NEWS_STANDALONE_AUTH=demo для автономного демо-запуска")
    return app
