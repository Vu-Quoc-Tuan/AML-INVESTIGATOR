"""Structured response contracts for the LLM investigation agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


StageName = Literal[
    "transaction_investigation",
    "kyc_entity_investigation",
    "screening_and_compliance",
    "legal_enrichment",
    "evidence_validation",
    "risk_dossier_generation",
]
MANDATORY_STAGES: tuple[StageName, ...] = (
    "transaction_investigation",
    "kyc_entity_investigation",
    "screening_and_compliance",
    "legal_enrichment",
    "evidence_validation",
    "risk_dossier_generation",
)

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "INCONCLUSIVE"]


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


class RagQuerySpec(StrictModel):
    query_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    linked_finding_ids: list[str] = Field(default_factory=list)
    hypothesis_tag: str | None = None


class RiskHypothesis(StrictModel):
    tag: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class BehaviorMappingResponse(StrictModel):
    """Intermediate mapping from scout findings to legal RAG queries.

    Empty ``rag_queries`` is valid when there are no scout findings to ground
    legal retrieval (no invented legal enrichment).
    """

    behavior_summary: str = Field(min_length=1)
    rag_queries: list[RagQuerySpec] = Field(default_factory=list, max_length=5)
    risk_hypotheses: list[RiskHypothesis] = Field(default_factory=list)


class LegalMappingItem(StrictModel):
    finding_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    article: str = Field(min_length=1)
    relevance_note: str = Field(min_length=1)


class InvestigationReportResponse(StrictModel):
    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    overall_risk_level: RiskLevel = "INCONCLUSIVE"
    risk_rationale: str = Field(default="", min_length=0)
    legal_mappings: list[LegalMappingItem] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    evidence_count: int = Field(ge=0)
    screening_status: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)
    workflow_error: str | None = None
