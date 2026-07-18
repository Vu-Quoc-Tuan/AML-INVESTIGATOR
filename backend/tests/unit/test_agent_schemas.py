"""Structured response contract tests."""

import pytest
from pydantic import ValidationError

from app.investigation_orchestrator.agent_schemas import (
    InvestigationPlanResponse,
    InvestigationReportResponse,
    ScreeningAnalysisResponse,
)


def _valid_plan() -> dict:
    stages = (
        "transaction_investigation",
        "kyc_entity_investigation",
        "screening_and_compliance",
        "evidence_validation",
        "report_generation",
        "human_review",
    )
    return {
        "case_summary": "Review the alert",
        "steps": [
            {"stage": stage, "objective": f"Run {stage}", "rationale": "Mandatory"}
            for stage in stages
        ],
    }


def test_plan_requires_all_mandatory_stages_in_order() -> None:
    assert len(InvestigationPlanResponse.model_validate(_valid_plan()).steps) == 6
    invalid = _valid_plan()
    invalid["steps"] = list(reversed(invalid["steps"]))
    with pytest.raises(ValidationError, match="mandatory stage"):
        InvestigationPlanResponse.model_validate(invalid)


def test_plan_json_schema_exposes_exact_step_count_to_the_model() -> None:
    steps_schema = InvestigationPlanResponse.model_json_schema()["properties"]["steps"]

    assert steps_schema["minItems"] == 6
    assert steps_schema["maxItems"] == 6


def test_report_contract_cannot_authorize_an_automated_decision() -> None:
    with pytest.raises(ValidationError):
        InvestigationReportResponse.model_validate(
            {
                "case_id": "CASE-1",
                "title": "Dossier",
                "summary": "Summary",
                "evidence_count": 0,
                "recommended_action": "AUTO_APPROVE",
                "automated_compliance_decision": True,
            }
        )


def test_screening_schema_tracks_availability_and_match_status() -> None:
    response = ScreeningAnalysisResponse(
        status="COMPLETED",
        screening_status="INCONCLUSIVE",
        available=False,
    )
    assert response.available is False
    assert response.screening_status == "INCONCLUSIVE"
