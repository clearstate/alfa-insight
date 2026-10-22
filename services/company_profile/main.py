"""Приложение модуля company_profile.

Запуск:  uvicorn services.company_profile.main:create_app --factory --host 0.0.0.0 --port 8001

Переменные окружения:
  DATABASE_URL                 postgresql://user:pass@host:5432/db (основной режим) или sqlite:///file.db
  COMPANY_PROFILE_DATA_DIR     папка с CSV — только если DATABASE_URL не задан (локальная разработка)
  COMPANY_PROFILE_USERS        JSON синтетических пользователей для CSV-режима (по умолчанию data/synthetic_users.json)
  COMPANY_PROFILE_RULES        путь к feature_rules.yaml (по умолчанию config/feature_rules.yaml)
  COMPANY_PROFILE_DEMO_ENDPOINTS=1  включить GET /api/companies/demo

Интеграция в общий сервис (участник 6):
  errors.install(app); app.include_router(router); app.state.profile_service = build_service()
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from . import errors
from .db import SqlStore
from .router import router
from .service import ProfileService

log = logging.getLogger("company_profile")


def build_service() -> ProfileService:
    rules = os.getenv("COMPANY_PROFILE_RULES")
    url = os.getenv("DATABASE_URL")
    if url:
        store = SqlStore.connect(url)
        try:
            svc = ProfileService.from_store(store, rules_path=rules)
        finally:
            store.close()  # данные прочитаны в память; соединение в запросах не нужно
        log.info("company_profile loaded from %s, run %s", svc.storage, svc.data_run_id)
        return svc
    data_dir = os.getenv("COMPANY_PROFILE_DATA_DIR")
    if not data_dir:
        raise RuntimeError("Задайте DATABASE_URL (PostgreSQL) или COMPANY_PROFILE_DATA_DIR (CSV)")
    return ProfileService.from_data_dir(data_dir, rules_path=rules,
                                        users_path=os.getenv("COMPANY_PROFILE_USERS", "data/synthetic_users.json"))


def create_app(service: ProfileService | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(title="Alfa Insight — company_profile", version="0.3.0")
    errors.install(app)
    app.include_router(router)
    app.state.profile_service = service or build_service()
    return app
