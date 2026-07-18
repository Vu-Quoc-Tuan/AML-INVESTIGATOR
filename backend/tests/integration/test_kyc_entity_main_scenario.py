"""Main-scenario integration through the production KYC tool boundary."""

import json
from datetime import date
from pathlib import Path

from langchain_core.messages import ToolMessage

from app.data.provider import (
    _reset_data_repository_for_testing,
    initialize_data_repository,
)
from app.investigation_orchestrator.production_tools import (
    build_production_tool_registry,
)
from app.investigation_orchestrator.tool_registry import ToolResult


AS_OF = date(2025, 12, 20)


def invoke_tool(tools: dict, name: str, args: dict) -> ToolResult:
    tool = tools[name]
    message = tool.invoke(
        {"name": name, "args": args, "id": f"CALL-{name}", "type": "tool_call"}
    )
    assert isinstance(message, ToolMessage)
    return ToolResult.model_validate(message.artifact)


def test_main_company_profile_documents_ownership_and_ubo_tools() -> None:
    _reset_data_repository_for_testing()
    data_path = Path(__file__).resolve().parents[2] / "data" / "generated"
    initialize_data_repository(data_path)
    try:
        registry = build_production_tool_registry()
        tools = {tool.name: tool for tool in registry.tools_for("kyc")}
        profile = invoke_tool(
            tools,
            "get_company_profile",
            {"company_id": "COMP-000008", "as_of_date": AS_OF},
        )
        documents = invoke_tool(
            tools,
            "get_kyc_documents",
            {"entity_id": "COMP-000008"},
        )
        ownership = invoke_tool(
            tools,
            "build_ownership_graph",
            {"company_id": "COMP-000008", "as_of_date": AS_OF, "max_depth": 3},
        )
        ubo = invoke_tool(
            tools,
            "calculate_ubo",
            {
                "company_id": "COMP-000008",
                "as_of_date": AS_OF,
                "max_depth": 3,
                "ownership_threshold": 0.25,
            },
        )
        gaps = invoke_tool(
            tools,
            "find_ownership_gaps",
            {"company_id": "COMP-000008", "as_of_date": AS_OF, "max_depth": 3},
        )

        assert all(
            result.status == "SUCCESS"
            for result in (profile, documents, ownership, ubo, gaps)
        )
        assert all(
            result.data["entity_scope"] == "SHB_INTERNAL"
            for result in (profile, documents, ownership, ubo, gaps)
        )
        assert profile.data["ownership_coverage_percentage"] == 100.0
        assert documents.data["documents"]
        assert ownership.data["edges"]
        assert all(edge["verified"] for edge in ownership.data["edges"])
        assert any(item["verified"] for item in ubo.data["identified_ubos"])

        evidence_ids = {item.evidence_id for item in ubo.evidence}
        assert all(
            set(item["evidence_ids"]) <= evidence_ids
            for item in ubo.data["identified_ubos"]
        )
        json.dumps(
            [
                result.model_dump(mode="json")
                for result in (profile, documents, ownership, ubo, gaps)
            ],
            allow_nan=False,
        )
    finally:
        _reset_data_repository_for_testing()
