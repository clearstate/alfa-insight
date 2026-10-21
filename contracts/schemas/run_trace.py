from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .common import Base

StepStatus = Literal["ok", "error", "skipped"]


class TraceStep(Base):
    step: int
    kind: Literal["plan", "tool", "synthesis", "critic", "revision"]
    name: str
    status: StepStatus
    started_at: datetime
    duration_ms: int
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None


class RunTrace(Base):
    run_id: str
    company_id: str
    event_id: str | None = None
    schema_version: str
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    steps: list[TraceStep]
    critic_passed: bool | None = None
    total_duration_ms: int
