from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Base

SourceType = Literal["news", "analytics_pdf", "press_release", "synthetic"]


class NewsItem(Base):
    item_id: str
    title: str
    text: str
    url: str | None = None
    source_name: str
    source_type: SourceType = "news"
    published_at: datetime
    language: str = "ru"
    companies: list[str] = Field(default_factory=list, description="Упомянутые компании")
    industries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    dedup_group_id: str | None = None
    ingested_at: datetime
