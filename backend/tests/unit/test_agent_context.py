"""Tests for minimum, secret-free agent context."""

import json

from app.investigation_orchestrator.agent_schemas import MANDATORY_STAGES
from app.investigation_orchestrator.prompts import (
    PLANNER_PROMPT,
    planner_context,
    report_context,
)


def test_planner_prompt_exposes_the_exact_mandatory_stage_order() -> None:
    for position, stage in enumerate(MANDATORY_STAGES, start=1):
        assert f"{position}. {stage}" in PLANNER_PROMPT

    assert "Do not repeat, omit, rename, or add any stage." in PLANNER_PROMPT
    assert "legal_enrichment" in PLANNER_PROMPT
    assert "risk_dossier_generation" in PLANNER_PROMPT
    assert "report_generation" not in PLANNER_PROMPT


def test_context_builders_exclude_unrelated_state_and_secrets() -> None:
    state = {
        "case_id": "CASE-1",
        "alert": {"type": "rapid_movement"},
        "case_file": {"findings": []},
        "evidence_validation": {"status": "PASSED"},
        "workflow_error": "safe error",
        "api_key": "must-not-leak",
        "messages": ["private agent message"],
        "model": "private model object",
    }
    planner_payload = json.loads(planner_context(state))
    report_payload = json.loads(report_context(state))

    assert set(planner_payload) == {"case_id", "alert"}
    assert set(report_payload) == {
        "case_id",
        "case_file",
        "behavior_mapping",
        "evidence_validation",
        "workflow_error",
        "errors",
    }
    serialized = json.dumps((planner_payload, report_payload))
    assert "must-not-leak" not in serialized
    assert "private agent message" not in serialized
    assert "private model object" not in serialized
