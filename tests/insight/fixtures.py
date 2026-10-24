"""Общий стенд для тестов insight: один сервис на весь прогон (демо-срез данных, временный каталог runtime)."""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="alfa_insight_test_")
os.environ["ALFA_RUNTIME_DIR"] = _TMP
os.environ.pop("LLM_BASE_URL", None)
os.environ["ALFA_LIVE_FEEDS"] = "0"         # тесты не ходят в сеть; живые ленты проверяются на локальном сервере
os.environ.pop("ALFA_DEMO_NEWS", None)      # без живых лент демо-новости включены — на них построены сценарии тестов
os.environ.pop("ALFA_AS_OF", None)

from services.insight.service import InsightService  # noqa: E402
from services.insight.settings import Settings  # noqa: E402

_SVC: InsightService | None = None


def svc() -> InsightService:
    global _SVC
    if _SVC is None:
        _SVC = InsightService(Settings())
    return _SVC


def user():
    return svc().dir.authenticate("demo", "demo")


def find(title_part: str) -> dict:
    return next(i for i in svc().kb.items.values() if title_part in i["title"])
