from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Base

EventType = Literal[
    "mna",
    "regulation",
    "market_shift",
    "supply_chain",
    "finance",
    "personnel",
    "product",
    "risk",
    "other",
]


class Event(Base):
    event_id: str
    event_type: EventType
    title: str
    summary: str
    companies: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    severity: str | None = None
    occurred_at: datetime | None = None
    news_item_ids: list[str] = Field(default_factory=list)
