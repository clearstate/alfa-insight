"""Настройки сервиса из переменных окружения (секреты — только из ENV)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    as_of: str = field(default_factory=lambda: _env("ALFA_AS_OF", "2026-10-21") or "2026-10-21")
    host: str = field(default_factory=lambda: _env("ALFA_HOST", "0.0.0.0") or "0.0.0.0")
    port: int = field(default_factory=lambda: int(_env("PORT", _env("ALFA_PORT", "8080")) or 8080))
    secret: str = field(default_factory=lambda: _env("ALFA_SECRET", "") or "")
    cors_origin: str | None = field(default_factory=lambda: _env("ALFA_CORS_ORIGIN"))
    # LLM
    llm_base_url: str | None = field(default_factory=lambda: _env("LLM_BASE_URL"))
    llm_api_key: str | None = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model_simple: str = field(default_factory=lambda: _env("LLM_MODEL_SIMPLE", "gemma-4-26b-a4b") or "")
    llm_model_reason: str = field(default_factory=lambda: _env("LLM_MODEL_REASON", "glm-5.3-flash") or "")
    llm_model_general: str = field(default_factory=lambda: _env("LLM_MODEL_GENERAL", "qwen3.6-35b-a3b") or "")
    llm_daily_token_budget: int = field(default_factory=lambda: int(_env("LLM_DAILY_TOKEN_BUDGET", "150000") or 150000))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "45") or 45))
    llm_enabled: bool = field(default_factory=lambda: (_env("LLM_ENABLED", "1") or "1") == "1")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_enabled and self.llm_base_url and self.llm_api_key)


def _resolve_data_dir() -> Path:
    explicit = _env("ALFA_DATA_DIR")
    if explicit:
        return Path(explicit)
    raw = ROOT / "data" / "raw"
    if (raw / "df_Uid_data_hack.csv").exists():
        return raw            # полные CSV кейса (85 тыс. компаний)
    return ROOT / "data" / "demo"   # компактный демо-срез (см. README, «Данные»)


def load_settings() -> Settings:
    return Settings()
