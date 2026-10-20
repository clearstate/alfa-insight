
from datetime import datetime
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError


ClaimType = Literal["fact", "bank_view", "ai_inference", "unknown"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(StrictModel):
    claim_type: ClaimType
    text: str
    provenance: str | None = None


class AnalysisBlock(StrictModel):
    text: str
    claim_type: ClaimType
    provenance: str


class ModelMetadata(StrictModel):
    model_name: str
    cost_rub: float = Field(ge=0)
    cache_hit: bool


class InsightResponse(StrictModel):
    schema_version: str
    insight_id: str
    company_id: str
    event_id: str
    headline: str
    summary: str
    why_it_matters: str
    analysis_blocks: list[AnalysisBlock]
    model_metadata: ModelMetadata


def valid_insight_response() -> dict:
    return {
        "schema_version": "2.1.0",
        "insight_id": "INS-test-001",
        "company_id": "SYNTHETIC_U",
        "event_id": "EVENT-test-001",
        "headline": "Изменение условий кредитования",
        "summary": "Краткое описание события.",
        "why_it_matters": "Возможное влияние на компанию.",
        "analysis_blocks": [
            {
                "text": "В новости сообщается об изменении условий.",
                "claim_type": "fact",
                "provenance": "news_item",
            },
            {
                "text": "Это может повлиять на расходы компании.",
                "claim_type": "ai_inference",
                "provenance": "orchestrator_calculation",
            },
        ],
        "model_metadata": {
            "model_name": "DeepSeek-V4.1-Flash",
            "cost_rub": 0.45,
            "cache_hit": False,
        },
    }


def test_claim_accepts_all_supported_types():
    for claim_type in ("fact", "bank_view", "ai_inference", "unknown"):
        claim = Claim(
            claim_type=claim_type,
            text="Example claim",
            provenance="news_item",
        )
        assert claim.claim_type == claim_type


def test_claim_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Claim(claim_type="guess", text="Example claim")


def test_claim_allows_missing_provenance():
    claim = Claim(claim_type="unknown", text="Not enough evidence")
    assert claim.provenance is None


def test_iso_timestamp_can_be_parsed_with_timezone():
    timestamp = datetime.fromisoformat("2026-10-20T12:30:00+03:00")
    assert timestamp.tzinfo is not None


def test_insight_response_accepts_proposed_contract():
    response = InsightResponse.model_validate(valid_insight_response())

    assert response.schema_version == "2.1.0"
    assert response.company_id == "SYNTHETIC_U"
    assert response.analysis_blocks[0].claim_type == "fact"
    assert response.model_metadata.cache_hit is False


def test_insight_response_rejects_unknown_claim_type():
    payload = valid_insight_response()
    payload["analysis_blocks"][0]["claim_type"] = "guess"

    with pytest.raises(ValidationError):
        InsightResponse.model_validate(payload)


def test_insight_response_rejects_missing_required_field():
    payload = valid_insight_response()
    del payload["why_it_matters"]

    with pytest.raises(ValidationError):
        InsightResponse.model_validate(payload)


def test_insight_response_rejects_unexpected_field():
    payload = valid_insight_response()
    payload["unexpected_field"] = "not part of the contract"

    with pytest.raises(ValidationError):
        InsightResponse.model_validate(payload)


def test_model_metadata_rejects_negative_cost():
    payload = valid_insight_response()
    payload["model_metadata"]["cost_rub"] = -1

    with pytest.raises(ValidationError):
        InsightResponse.model_validate(payload)

class ApiErrorDetail(StrictModel):
    code: str
    message: str
    details: dict | list | str | int | float | bool | None
    correlation_id: str


class ApiErrorResponse(StrictModel):
    error: ApiErrorDetail


def test_api_error_accepts_common_envelope():
    payload = {
        "error": {
            "code": "PROMPT_INJECTION_DETECTED",
            "message": "Анализ заблокирован в целях безопасности.",
            "details": None,
            "correlation_id": "request-test-001",
        }
    }

    response = ApiErrorResponse.model_validate(payload)

    assert response.error.code == "PROMPT_INJECTION_DETECTED"
    assert response.error.details is None
    assert response.error.correlation_id == "request-test-001"


def test_api_error_rejects_missing_correlation_id():
    payload = {
        "error": {
            "code": "PROMPT_INJECTION_DETECTED",
            "message": "Анализ заблокирован в целях безопасности.",
            "details": None,
        }
    }

    with pytest.raises(ValidationError):
        ApiErrorResponse.model_validate(payload)


def test_api_error_rejects_unexpected_fields():
    payload = {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Внутренняя ошибка.",
            "details": None,
            "correlation_id": "request-test-002",
            "secret": "must-not-be-here",
        }
    }

    with pytest.raises(ValidationError):
        ApiErrorResponse.model_validate(payload)
