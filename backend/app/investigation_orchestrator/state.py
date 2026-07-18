"""Serializable state contracts for the investigation workflow."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict


WorkflowPhase = Literal[
    "new",
    "planning",
    "parallel_investigation",
    "merged",
    "screening",
    "evidence_validation",
    "reporting",
    "human_review",
    "complete",
]
CaseStatus = Literal[
    "OPEN",
    "IN_REVIEW",
    "APPROVED",
    "REJECTED",
    "AWAITING_INFORMATION",
    "FAILED",
]
ReviewDecision = Literal["APPROVED", "REJECTED", "MORE_INFORMATION_REQUIRED"]


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge parallel state updates without mutating either input."""

    return {**(left or {}), **(right or {})}


def append_lists(left: list[Any], right: list[Any]) -> list[Any]:
    """Append audit entries emitted by separate graph nodes."""

    return [*(left or []), *(right or [])]


class Evidence(TypedDict, total=False):
    evidence_id: str
    source_system: str
    source_record_id: str
    visibility_level: str
    payload: dict[str, Any]


class Finding(TypedDict, total=False):
    finding_id: str
    finding_type: str
    summary: str
    evidence_ids: list[str]
    visibility_level: str
    entity_scope: str
    match_basis: str


class AgentOutput(TypedDict, total=False):
    agent: str
    status: str
    available: bool
    findings: list[Finding]
    evidence: list[Evidence]
    metadata: dict[str, Any]


class HandoffRecord(TypedDict):
    source: str
    target: str
    reason: str


class ReviewResult(TypedDict, total=False):
    decision: ReviewDecision
    reviewer: str
    comments: str
    requested_target: str


class InvestigationInput(TypedDict):
    case_id: str
    alert: dict[str, Any]


class InvestigationState(InvestigationInput, total=False):
    phase: WorkflowPhase
    case_status: CaseStatus
    investigation_plan: dict[str, Any]
    agent_outputs: Annotated[dict[str, AgentOutput], merge_dicts]
    case_file: dict[str, Any]
    evidence_validation: dict[str, Any]
    report: dict[str, Any]
    human_review: ReviewResult
    workflow_error: str
    handoff_log: Annotated[list[HandoffRecord], append_lists]
    errors: Annotated[list[str], append_lists]


def initial_state(case_id: str, alert: dict[str, Any]) -> InvestigationInput:
    """Create the minimal input accepted by the compiled workflow."""

    return {"case_id": case_id, "alert": alert}
