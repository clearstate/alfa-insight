"""Примеры из contracts/examples/ должны проходить валидацию Pydantic-моделями contracts/schemas/."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"
sys.path.insert(0, str(ROOT / "contracts"))

from schemas import (  # noqa: E402
    BusinessInsight,
    Claim,
    CompanyProfile,
    ErrorResponse,
    Event,
    NewsItem,
    RankedEvents,
    RunTrace,
)

CASES = [
    ("company_profile.json", CompanyProfile),
    ("news_item.json", NewsItem),
    ("event.json", Event),
    ("ranked_events.json", RankedEvents),
    ("claim.json", Claim),
    ("business_insight.json", BusinessInsight),
    ("run_trace.json", RunTrace),
    ("error.json", ErrorResponse),
]


@pytest.mark.parametrize(("filename", "model"), CASES)
def test_example_validates(filename: str, model: type) -> None:
    payload = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    model.model_validate(payload)
