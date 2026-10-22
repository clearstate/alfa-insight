"""Единый формат ошибок и X-Correlation-ID.

Формат: {"error": {"code", "message", "details", "correlation_id"}}.
Локальная реализация модуля; при появлении общей у участника 6 — заменить импортом.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CORRELATION_HEADER = "X-Correlation-ID"
audit_log = logging.getLogger("company_profile.audit")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or str(uuid.uuid4())


def error_response(request: Request, status: int, code: str, message: str,
                   details: dict[str, Any] | None = None) -> JSONResponse:
    cid = correlation_id(request)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details, "correlation_id": cid}},
        headers={CORRELATION_HEADER: cid},
    )


def audit(event: str, request: Request, **fields: Any) -> None:
    """Журнал обращений: кто, к какой компании, через какой эндпоинт, результат. Без данных профиля."""
    record = {"event": event, "correlation_id": correlation_id(request), "path": request.url.path, **fields}
    audit_log.info(json.dumps(record, ensure_ascii=False))


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def _correlation(request: Request, call_next):
        request.state.correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = request.state.correlation_id
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "validation_error", "Некорректные параметры запроса",
                              {"errors": json.loads(json.dumps(exc.errors(), default=str))})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return error_response(request, exc.status_code, "http_error", str(exc.detail))
