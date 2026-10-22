"""Контракт news_item/1.0 (Pydantic v2). Владелец контракта — участник 6; автор схемы и поставщик данных — участник 2.

Потребители: участник 3 (бизнес-выводы), участник 4 (поиск/ранжирование), участник 5 (UI), участник 6 (интеграция).
Любое изменение — PR в contracts/ с ревью потребителей и schema_version++.
ВАЖНО: файл написан под Pydantic v2, но в среде разработки pydantic не был установлен — модель не запускалась. Соответствие полей
dataclass-модели services/news_ingest/models.py и словарям contracts/news_vocab.py проверяется без Pydantic
(tests/news_ingest/test_contract_static.py, через AST); полная проверка NewsItem.model_validate(item_dict) — tests/news_ingest/test_contract_pydantic.py.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.news_vocab import SCHEMA_VERSION

ClaimType = Literal["fact", "bank_view", "ai_inference", "unknown"]
SourceType = Literal["regulator", "statistics", "media", "bank_analytics", "user_submitted"]
DocumentType = Literal["news", "press_release", "statistics_release", "bank_analytics"]
ProcessingStatus = Literal["ok", "needs_review", "failed", "duplicate"]
FactMethod = Literal["rule", "llm", "manual"]
BankViewKind = Literal["forecast", "assessment", "recommendation"]
DatePrecision = Literal["day", "second"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyFact(_Strict):
    text: str
    claim_type: ClaimType = "fact"
    method: FactMethod = "rule"
    span: dict[str, Any] = Field(default_factory=dict, description="{field,start,end,page}: позиция в NewsItem.text")
    topics: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class BankView(_Strict):
    text: str
    kind: BankViewKind
    topics: list[str] = Field(default_factory=list)
    page: int | None = None
    span: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class NumericClaim(_Strict):
    kind: Literal["key_rate_pct", "inflation_yoy_pct", "usd_rub"]
    value: float
    text: str
    claim_type: ClaimType = "fact"
    page: int | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class Industries(_Strict):
    okved_prefixes: list[str] = Field(default_factory=list, description="префиксы ОКВЭД2 для match_company(); основной ключ")
    okved_sections: list[str] = Field(default_factory=list, description="разделы-буквы, выведены из префиксов; только грубый фильтр")
    matches: list[dict[str, Any]] = Field(default_factory=list)


class Entity(_Strict):
    name: str
    type: str


class Reliability(_Strict):
    score: float = Field(ge=0, le=1)
    rule: str


class BankMeta(_Strict):
    author_unit: str | None = None
    doc_family: str | None = None
    stale: bool = False
    stale_reason: str | None = None
    superseded_note: str | None = None
    published_at_note: str | None = None
    case_list_title: str | None = None
    source_file: str | None = None


class NewsItem(_Strict):
    id: str
    title: str
    text: str
    url: str | None = None
    publisher: str | None = None
    source_id: str
    source_type: SourceType
    document_type: DocumentType
    published_at: str | None = Field(None, description="ISO 8601 UTC; null если дата не найдена (status needs_review)")
    date_precision: DatePrecision | None = None
    event_date: str | None = None
    retrieved_at: str
    content_hash: str
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION  # type: ignore[valid-type]
    version: int = 1
    canonical_url: str | None = None
    summary: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list, description="словарь v1 участника 1 (36 тем)")
    topic_scores: dict[str, float] = Field(default_factory=dict)
    industries: Industries = Field(default_factory=Industries)
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    key_facts: list[KeyFact] = Field(default_factory=list)
    bank_views: list[BankView] = Field(default_factory=list)
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    event_cluster_id: str | None = None
    dup_of: str | None = None
    source_reliability: Reliability
    provenance: dict[str, Any]
    processing_status: ProcessingStatus = "ok"
    status_reasons: list[str] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)
    extraction: dict[str, Any] = Field(default_factory=dict)
    bank: BankMeta | None = None
    chunk_count: int = 0


class Chunk(_Strict):
    id: str
    news_item_id: str
    idx: int
    text: str
    page: int | None = None
    kind: str = "text"
    topics: list[str] = Field(default_factory=list)
    claim_type: ClaimType = "fact"


class NewsCandidate(_Strict):
    id: str
    title: str | None = None
    published_at: str | None = None
    event_date: str | None = None
    source_type: SourceType
    document_type: DocumentType
    processing_status: ProcessingStatus
    event_cluster_id: str | None = None
    reliability_score: float | None = None
    version: int


class IndicatorRow(_Strict):
    id: int | None = None
    table_name: str | None = None
    item_id: str
    indicator: str
    label: str | None = None
    period: str
    value: float | None = None
    unit: str | None = None
    is_forecast: bool
    page: int | None = None
    published_at: str | None = None


class IngestRequest(_Strict):
    """POST /api/news/ingest: ровно одно из url / text."""
    url: str | None = None
    text: str | None = Field(None, max_length=200_000)
    title: str | None = Field(None, max_length=500)
    published_at: str | None = None
    publisher: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _one_of(self) -> "IngestRequest":
        if bool(self.url) == bool(self.text):
            raise ValueError("укажите ровно одно из полей: url или text")
        return self


class IngestResponse(_Strict):
    outcome: Literal["created", "updated", "duplicate", "failed", "skipped"]
    item_id: str | None = None
    version: int | None = None
    status: ProcessingStatus | None = None
    dup_of: str | None = None
    cluster_id: str | None = None
    error: str | None = None
    reasons: list[str] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
