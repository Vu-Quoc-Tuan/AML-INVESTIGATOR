"""Structured response contracts for the LLM investigation agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


StageName = Literal[
    "transaction_investigation",
    "kyc_entity_investigation",
    "screening_and_compliance",
    "evidence_validation",
    "report_generation",
    "human_review",
]
MANDATORY_STAGES: tuple[StageName, ...] = (
    "transaction_investigation",
    "kyc_entity_investigation",
    "screening_and_compliance",
    "evidence_validation",
    "report_generation",
    "human_review",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanStep(StrictModel):
    stage: StageName
    objective: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class InvestigationPlanResponse(StrictModel):
    case_summary: str = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_mandatory_order(self) -> "InvestigationPlanResponse":
        if tuple(step.stage for step in self.steps) != MANDATORY_STAGES:
            raise ValueError("Plan must contain every mandatory stage in order")
        return self


class AgentFindingResponse(StrictModel):
    finding_id: str = Field(min_length=1)
    finding_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    visibility_level: str | None = None
    entity_scope: str | None = None
    match_basis: str | None = None


class WorkerAnalysisResponse(StrictModel):
    status: Literal["COMPLETED", "INCONCLUSIVE", "ERROR"]
    findings: list[AgentFindingResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScreeningAnalysisResponse(WorkerAnalysisResponse):
    screening_status: Literal[
        "NO_MATCH", "POTENTIAL_MATCH", "CONFIRMED_MATCH", "INCONCLUSIVE"
    ]
    available: bool = True


class InvestigationReportResponse(StrictModel):
    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    evidence_count: int = Field(ge=0)
    screening_status: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)
    workflow_error: str | None = None
    recommended_action: Literal["HUMAN_REVIEW_REQUIRED"] = "HUMAN_REVIEW_REQUIRED"
    automated_compliance_decision: Literal[False] = False
