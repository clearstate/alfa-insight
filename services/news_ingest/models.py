"""Доменные модели news_ingest (dataclasses). Контракт для других модулей — NewsItem.to_dict() == contracts/news_item.py."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from contracts.news_vocab import SCHEMA_VERSION


@dataclass
class KeyFact:
    text: str
    claim_type: str = "fact"           # fact | bank_view | ai_inference | unknown
    method: str = "rule"               # rule | llm | manual
    span: dict[str, Any] = field(default_factory=dict)   # {field, start, end, page?}
    topics: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class BankView:
    text: str
    kind: str                          # forecast | assessment | recommendation
    topics: list[str] = field(default_factory=list)
    page: int | None = None
    span: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class NumericClaim:
    kind: str                          # key_rate_pct | inflation_yoy_pct | usd_rub
    value: float
    text: str
    claim_type: str = "fact"
    page: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    id: str
    news_item_id: str
    idx: int
    text: str
    page: int | None = None
    kind: str = "text"
    topics: list[str] = field(default_factory=list)
    claim_type: str = "fact"           # bank_view для аналитики банка, fact для остального (грубая метка чанка)


@dataclass
class PageText:
    page: int
    kind: str
    text: str


@dataclass
class Extracted:
    """Результат извлечения из сырья (до нормализации/обогащения)."""
    title: str | None
    text: str
    published_raw: str | None = None
    publisher: str | None = None
    language: str | None = None
    url: str | None = None
    method: str = "html"
    pages: list[PageText] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Indicator:
    """Строка макротаблицы банка: показатель × период (для расчёта рисков участником 3)."""
    item_id: str
    indicator: str                     # канонический ключ (key_rate_eoy) или other:<slug>
    label: str
    period: str                        # 2026 | 2026-07 | 2026-H1 | 2026-Q1
    value: float | None
    unit: str | None
    is_forecast: bool
    page: int | None
    published_at: str | None = None
    table: str | None = None


@dataclass
class NewsItem:
    id: str
    title: str
    text: str
    url: str | None
    publisher: str | None
    source_id: str
    source_type: str
    document_type: str
    published_at: str | None
    date_precision: str | None
    event_date: str | None
    retrieved_at: str
    content_hash: str
    schema_version: str = SCHEMA_VERSION
    version: int = 1
    canonical_url: str | None = None
    summary: str | None = None
    language: str | None = None
    topics: list[str] = field(default_factory=list)
    topic_scores: dict[str, float] = field(default_factory=dict)
    industries: dict[str, Any] = field(default_factory=lambda: {"okved_prefixes": [], "okved_sections": [], "matches": []})
    regions: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    entities: list[dict[str, str]] = field(default_factory=list)
    key_facts: list[KeyFact] = field(default_factory=list)
    bank_views: list[BankView] = field(default_factory=list)
    numeric_claims: list[NumericClaim] = field(default_factory=list)
    event_cluster_id: str | None = None
    dup_of: str | None = None
    source_reliability: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    processing_status: str = "ok"
    status_reasons: list[str] = field(default_factory=list)
    security_flags: list[str] = field(default_factory=list)
    extraction: dict[str, Any] = field(default_factory=dict)
    bank: dict[str, Any] | None = None
    chunk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestResult:
    outcome: str                       # created | updated | duplicate | failed | skipped
    item_id: str | None = None
    version: int | None = None
    status: str | None = None
    dup_of: str | None = None
    cluster_id: str | None = None
    error: str | None = None
    reasons: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
