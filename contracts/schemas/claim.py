from typing import Literal

from pydantic import Field

from .common import Base, Provenance

ClaimType = Literal[
    "fact",           # подтверждено источником
    "inference",      # вывод на основе фактов
    "recommendation", # совет к действию
    "estimate",       # оценка/прогноз, может быть приблизительной
]


class Claim(Base):
    claim_id: str
    text: str
    claim_type: ClaimType
    confidence: float = Field(ge=0, le=1)
    provenance: list[Provenance] = Field(
        default_factory=list, description="Пусто допустимо только для recommendation/estimate"
    )
