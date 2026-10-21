from datetime import datetime

from pydantic import Field

from .claim import Claim
from .common import Base


class BusinessInsight(Base):
    insight_id: str
    company_id: str
    event_id: str
    title: str
    reference: str
    audience: str | None = None
    claims: list[Claim]
    questions: list[str] = Field(default_factory=list, description="Чипы уточняющих вопросов")
    confidence: float = Field(ge=0, le=1)
    generated_at: datetime
