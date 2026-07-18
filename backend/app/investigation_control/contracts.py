"""Typed contracts for investigation control configuration and runs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.detection.contracts import RunMode, RunTrigger


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ControlConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    soft_prompt: str | None = None
    updated_at: datetime

    @field_validator("soft_prompt", mode="before")
    @classmethod
    def normalize_soft_prompt(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > 4_000:
            raise ValueError("soft_prompt must contain at most 4000 characters")
        return normalized


class InvestigationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    trigger: RunTrigger
    status: RunStatus
    soft_prompt_snapshot: str | None = None
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class QueueCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    pending: int = Field(default=0, ge=0)
    processing: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class ControlSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: RunMode
    queue: QueueCounts
    active_run: InvestigationRun | None = None

