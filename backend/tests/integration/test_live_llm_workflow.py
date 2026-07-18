"""Live full-workflow verification through Human Review."""

import pytest
from langchain_core.tools import tool
from langgraph.types import Command

from app.investigation_orchestrator import ToolRegistry, build_workflow, initial_state
from app.investigation_orchestrator.tool_registry import ToolResult


pytestmark = pytest.mark.live_llm


@tool
def get_account_transactions(case_id: str) -> dict:
    """Return deterministic internal transaction evidence for a workflow test."""

    return ToolResult(
        status="SUCCESS",
        data={"case_id": case_id, "pattern": "rapid_pass_through"},
        evidence=[
            {
                "evidence_id": "E-WORKFLOW-TX",
                "source_system": "SHB_TRANSACTION_LEDGER",
                "source_record_id": "TX-WORKFLOW-1",
                "visibility_level": "FULL_INTERNAL",
            }
        ],
    ).model_dump()


@tool
def get_kyc_documents(case_id: str) -> dict:
    """Return deterministic internal KYC evidence for a workflow test."""

    return ToolResult(
        status="SUCCESS",
        data={
            "case_id": case_id,
            "profile_status": "verified",
            "entity_scope": "SHB_INTERNAL",
        },
        evidence=[
            {
                "evidence_id": "E-WORKFLOW-KYC",
                "source_system": "SHB_KYC_REPOSITORY",
                "source_record_id": "KYC-WORKFLOW-1",
            }
        ],
    ).model_dump()


@tool
def screen_internal_watchlist(case_id: str) -> dict:
    """Return deterministic no-match screening evidence for a workflow test."""

    return ToolResult(
        status="SUCCESS",
        data={"case_id": case_id, "screening_status": "NO_MATCH"},
        evidence=[
            {
                "evidence_id": "E-WORKFLOW-SCREEN",
                "source_system": "INTERNAL_SCREENING_SERVICE",
                "source_record_id": "SCREEN-WORKFLOW-1",
            }
        ],
    ).model_dump()


def test_live_workflow_interrupts_and_resumes_with_tool_provenance() -> None:
    registry = ToolRegistry()
    registry.register("transaction", [get_account_transactions])
    registry.register("kyc", [get_kyc_documents])
    registry.register("screening", [screen_internal_watchlist])
    graph = build_workflow(tool_registry=registry)
    config = {"configurable": {"thread_id": "live-full-workflow"}}

    result = graph.invoke(
        initial_state(
            "CASE-LIVE-WORKFLOW",
            {"data_visibility": "FULL_INTERNAL", "subject_bank_id": "BANK-SHB-001"},
        ),
        config,
    )

    assert "__interrupt__" in result
    state = graph.get_state(config).values
    evidence_ids = {item["evidence_id"] for item in state["case_file"]["evidence"]}
    assert {
        "E-WORKFLOW-TX",
        "E-WORKFLOW-KYC",
        "E-WORKFLOW-SCREEN",
    } <= evidence_ids, state.get("agent_outputs", {}).get("screening", {}).get(
        "metadata", {}
    )
    assert "messages" not in state
    assert state["report"]["automated_compliance_decision"] is False
    assert state["report"]["workflow_error"] is None

    completed = graph.invoke(
        Command(
            resume={
                "decision": "APPROVED",
                "reviewer": "live-test-reviewer",
                "comments": "Live workflow verified",
            }
        ),
        config,
    )
    assert completed["case_status"] == "APPROVED"
