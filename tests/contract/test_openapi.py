"""contracts/openapi.yaml должен быть валидной OpenAPI-спецификацией."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_is_valid() -> None:
    spec = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))
    validator = pytest.importorskip("openapi_spec_validator")
    validator.validate(spec)
