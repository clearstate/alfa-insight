from pydantic import Field

from .common import Base
from .event import Event


class RankedEvent(Base):
    event: Event
    score: float = Field(ge=0, le=1)
    relevance_explanation: str
    matched_features: list[str] = Field(default_factory=list)
    rank: int = Field(ge=1)


class RankedEvents(Base):
    company_id: str
    items: list[RankedEvent]
    generated_at: str | None = None
