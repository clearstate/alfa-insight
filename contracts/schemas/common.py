"""Общие типы контрактов."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"

Currency = Literal["RUB", "USD", "EUR"]
Severity = Literal["low", "medium", "high", "critical"]


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Provenance(Base):
    """Откуда взято утверждение — обязательна для каждого claim."""

    source_id: str
    source_name: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    fragment: str = Field(description="Цитата/фрагмент, на котором основано утверждение")
    retrieved_at: datetime
