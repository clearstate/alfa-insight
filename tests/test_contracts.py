
from datetime import datetime
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


ClaimType = Literal["fact", "bank_view", "ai_inference", "unknown"]
INSUFFICIENT_DATA = "Недостаточно данных для персонального заключения"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    source_id: str
    field_or_fragment: str
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class Claim(StrictModel):
    claim_type: ClaimType
    text: str
    provenance: Provenance


class AnalysisBlock(StrictModel):
    text: str
    claim_type: ClaimType
    provenance: Provenance


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
    risks: list[str]
    opportunities: list[str]
    recommended_actions: list[str]
    uncertainties: Literal[
                       "Недостаточно данных для персонального заключения"
                   ] | None
    model_metadata: ModelMetadata


def valid_provenance() -> dict:
    return {
        "source_id": "NEWS-test-001",
        "field_or_fragment": "paragraph_1",
        "timestamp": "2026-10-20T12:30:00+03:00",
    }


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
                "provenance": valid_provenance(),
            },
            {
                "text": "Это может повлиять на расходы компании.",
                "claim_type": "ai_inference",
                "provenance": {
                    "source_id": "BANKDOC-test-001",
                    "field_or_fragment": "credit_conditions",
                    "timestamp": "2026-10-20T12:30:00Z",
                },
            },
        ],
        "risks": [],
        "opportunities": [],
        "recommended_actions": [],
        "uncertainties": INSUFFICIENT_DATA,
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
            provenance=valid_provenance(),
        )
        assert claim.claim_type == claim_type


def test_claim_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Claim(
            claim_type="guess",
            text="Example claim",
            provenance=valid_provenance(),
        )


def test_claim_requires_structured_provenance():
    with pytest.raises(ValidationError):
        Claim(claim_type="unknown", text="Not enough evidence")


def test_provenance_accepts_timezone_aware_timestamp():
    provenance = Provenance.model_validate(valid_provenance())
    assert provenance.timestamp.tzinfo is not None


def test_provenance_rejects_timestamp_without_timezone():
    payload = valid_provenance()
    payload["timestamp"] = "2026-10-20T12:30:00"

    with pytest.raises(ValidationError):
        Provenance.model_validate(payload)


def test_provenance_rejects_missing_required_field():
    payload = valid_provenance()
    del payload["source_id"]

    with pytest.raises(ValidationError):
        Provenance.model_validate(payload)


def test_provenance_rejects_unexpected_field():
    payload = valid_provenance()
    payload["source_type"] = "news"

    with pytest.raises(ValidationError):
        Provenance.model_validate(payload)


def test_insight_response_accepts_proposed_contract():
    response = InsightResponse.model_validate(valid_insight_response())

    assert response.schema_version == "2.1.0"
    assert response.company_id == "SYNTHETIC_U"
    assert response.event_id == "EVENT-test-001"
    assert response.analysis_blocks[0].claim_type == "fact"
    assert response.analysis_blocks[0].provenance.source_id == "NEWS-test-001"
    assert response.risks == []
    assert response.opportunities == []
    assert response.recommended_actions == []
    assert response.model_metadata.cache_hit is False


def test_insight_response_allows_null_uncertainties():
    payload = valid_insight_response()
    payload["uncertainties"] = None

    response = InsightResponse.model_validate(payload)
    assert response.uncertainties is None


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


def test_insight_response_rejects_missing_new_contract_field():
    payload = valid_insight_response()
    del payload["recommended_actions"]

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

def test_insight_response_rejects_unknown_uncertainties():
    payload = valid_insight_response()
    payload["uncertainties"] = "Какая-то другая причина"

    with pytest.raises(ValidationError):
        InsightResponse.model_validate(payload)


def test_insight_response_accepts_canonical_uncertainties():
    payload = valid_insight_response()
    payload["uncertainties"] = INSUFFICIENT_DATA

    response = InsightResponse.model_validate(payload)
    assert response.uncertainties == INSUFFICIENT_DATA
