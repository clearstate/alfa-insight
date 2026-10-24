"""Настройки сервиса из переменных окружения (секреты — только из ENV)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


# Допустимые семейства моделей (Приложение 3 кейса). Другие LLM использовать нельзя.
ALLOWED_MODEL_MARKERS = ("gemma-4", "gemma4", "glm-5", "qwen3.6", "qwen3-vl", "deepseek-v4", "kimi-k2")


@dataclass
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: _resolve_data_dir())
    runtime_dir: Path = field(default_factory=lambda: Path(_env("ALFA_RUNTIME_DIR", str(ROOT / "data" / "runtime"))))
    news_demo_dir: Path = field(default_factory=lambda: Path(_env("ALFA_NEWS_DEMO_DIR", str(ROOT / "data" / "news_demo"))))
    frontend_dir: Path = field(default_factory=lambda: Path(_env("ALFA_FRONTEND_DIR", str(ROOT / "frontend" / "dist"))))
    bank_pdf_dir: Path = field(default_factory=lambda: Path(_env("ALFA_BANK_PDF_DIR", str(ROOT / "data" / "bank_pdf"))))
    # Опорная дата демонстрации. Данные кейса датированы сентябрём–октябрём 2026 г.; без фиксации даты лента «протухает».
    # С живыми лентами (ALFA_LIVE_FEEDS=1) и без явной ALFA_AS_OF опорная дата — сегодняшняя (МСК).
    as_of: str = field(default_factory=lambda: _env("ALFA_AS_OF") or (today_msk() if _live_feeds() else "2026-10-21"))
    # опорная дата «плывёт» вместе с календарём (живые ленты без ALFA_AS_OF): KnowledgeBase сдвигает её при смене суток
    as_of_auto: bool = field(default_factory=lambda: _live_feeds() and not _env("ALFA_AS_OF"))
    # Живые ленты (по умолчанию включены): обход включённых RSS из services/news_ingest/config/sources.yaml по расписанию,
    # в ту же базу знаний. ALFA_LIVE_FEEDS=0 — офлайн-режим с воспроизводимой демо-лентой.
    live_feeds: bool = field(default_factory=lambda: _live_feeds())
    # Синтетические демо-новости (data/news_demo). По умолчанию — только без живых лент: рядом с реальными новостями
    # вымышленные события могут ввести в заблуждение. ALFA_DEMO_NEWS=1 — показывать всегда, 0 — никогда.
    demo_news: bool = field(default_factory=lambda: (_env("ALFA_DEMO_NEWS") or ("0" if _live_feeds() else "1")) == "1")
    live_feeds_tick: float = field(default_factory=lambda: float(_env("ALFA_LIVE_FEEDS_TICK", "60") or 60))
    host: str = field(default_factory=lambda: _env("ALFA_HOST", "0.0.0.0") or "0.0.0.0")
    port: int = field(default_factory=lambda: int(_env("PORT", _env("ALFA_PORT", "8080")) or 8080))
    secret: str = field(default_factory=lambda: _env("ALFA_SECRET", "") or "")
    cors_origin: str | None = field(default_factory=lambda: _env("ALFA_CORS_ORIGIN"))
    # LLM
    llm_base_url: str | None = field(default_factory=lambda: _env("LLM_BASE_URL"))
    # запасной адрес шлюза (инструкция организаторов: для российских хостингов) — используется при сетевой ошибке основного
    llm_base_url_fallback: str | None = field(default_factory=lambda: _env("LLM_BASE_URL_FALLBACK"))
    llm_api_key: str | None = field(default_factory=lambda: _env("LLM_API_KEY"))
    # идентификаторы — точно как в /v1/models шлюза организаторов
    llm_model_simple: str = field(default_factory=lambda: _env("LLM_MODEL_SIMPLE", "google/gemma-4-26b-a4b-it") or "")
    llm_model_reason: str = field(default_factory=lambda: _env("LLM_MODEL_REASON", "z-ai/glm-5.3-flash") or "")
    llm_model_general: str = field(default_factory=lambda: _env("LLM_MODEL_GENERAL", "qwen/qwen3.6-35b-a3b") or "")
    # «рассуждения» моделей (reasoning) по умолчанию выключены: на задачах сервиса (переписать вывод, ответить по фрагментам)
    # они не улучшают ответ, но дороже в 3–50 раз и съедают max_tokens (ответ приходит пустым). 1 — включить.
    llm_reasoning: bool = field(default_factory=lambda: (_env("LLM_REASONING", "0") or "0") == "1")
    # Лимиты на сутки (сброс в 03:00 МСК, как у шлюза). Бюджет шлюза — 500 ₽/сутки на всю команду и все модели; стоимость
    # шлюз возвращает в usage.cost (в рублях). Разбор моделью glm-5.3-flash — около 0,08 ₽ и 6–8 тыс. токенов.
    llm_daily_token_budget: int = field(default_factory=lambda: int(_env("LLM_DAILY_TOKEN_BUDGET", "3000000") or 3000000))
    llm_daily_cost_budget: float = field(default_factory=lambda: float(_env("LLM_DAILY_COST_BUDGET", "300") or 300))
    # сколько верхних карточек ленты переписывать моделью заранее, в фоне (0 — только по открытию разбора)
    llm_prewarm: int = field(default_factory=lambda: int(_env("LLM_PREWARM", "3") or 0))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "45") or 45))
    llm_enabled: bool = field(default_factory=lambda: (_env("LLM_ENABLED", "1") or "1") == "1")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_enabled and self.llm_base_url and self.llm_api_key)


def _live_feeds() -> bool:
    return (_env("ALFA_LIVE_FEEDS", "1") or "1") == "1"


def today_msk() -> str:
    return datetime.now(timezone(timedelta(hours=3))).date().isoformat()


def _resolve_data_dir() -> Path:
    explicit = _env("ALFA_DATA_DIR")
    if explicit:
        return Path(explicit)
    raw = ROOT / "data" / "raw"
    if (raw / "df_Uid_data_hack.csv").exists():
        return raw            # полные CSV кейса (85 тыс. компаний)
    return ROOT / "data" / "demo"   # компактный демо-срез (см. README, «Данные»)


def load_dotenv(path: Path | None = None) -> list[str]:
    """Переменные из .env в окружение процесса (только отсутствующие: окружение и секреты платформы важнее файла).
    Вызывается при запуске сервера (start.bat/start.sh не читают .env сами; docker compose передаёт его через env_file).
    Тесты .env не читают — иначе они ходили бы в реальный шлюз LLM. Возвращает имена загруженных переменных."""
    path = path or ROOT / ".env"
    if not path.is_file() or os.environ.get("ALFA_DOTENV") == "0":
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.split(" #", 1)[0].strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            loaded.append(k)
    return loaded


def load_settings() -> Settings:
    return Settings()
