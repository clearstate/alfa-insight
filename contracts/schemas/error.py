from typing import Any, Literal

from pydantic import Field

from .common import Base

ErrorCode = Literal[
    "unauthorized",
    "forbidden",
    "not_found",
    "validation_error",
    "upstream_error",
    "llm_error",
    "rate_limited",
    "internal_error",
]


class ErrorBody(Base):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(Base):
    error: ErrorBody
    request_id: str = Field(description="Коррелирует ответ с журналами шлюза")
