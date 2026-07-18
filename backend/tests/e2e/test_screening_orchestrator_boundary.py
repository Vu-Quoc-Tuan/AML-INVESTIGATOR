from langchain_core.messages import ToolMessage

from app.investigation_orchestrator.agents import collect_tool_results, invoke_worker
from app.investigation_orchestrator.tool_registry import ToolRegistry
from app.screening import ScreeningFacade, build_screening_tools


class StaticProvider:
    def candidates(self, *args, **kwargs):
        return [
            {
                "watchlist_id": "WL-E2E-001",
                "list_type": "SANCTIONS",
                "full_name": "Nguyen Van An",
                "aliases": [],
                "date_of_birth": "1980-05-05",
                "nationalities": ["VN"],
                "document_numbers": ["P12345"],
                "company_registration_number": None,
                "source_name": "DEMO-SANCTIONS-LIST",
                "effective_from": "2020-01-01",
                "effective_to": None,
                "status": "ACTIVE",
                "screening_dependency": "available",
            }
        ]


PAYLOAD = {
    "request_id": "REQ-E2E-001",
    "subject": {
        "subject_id": "CUST-E2E-001",
        "entity_scope": "SHB_INTERNAL",
        "entity_type": "INDIVIDUAL",
        "name": "Nguyễn Văn An",
        "date_of_birth": "1980-05-05",
        "nationalities": ["VN"],
        "passport_number": "P-12345",
    },
    "screening_types": ["SANCTIONS"],
    "as_of_date": "2026-01-01",
}


def tool_message(tool):
    message = tool.invoke(
        {
            "name": tool.name,
            "args": PAYLOAD,
            "id": "CALL-E2E-001",
            "type": "tool_call",
        }
    )
    assert isinstance(message, ToolMessage)
    return message


class ScreeningAgentFixture:
    def __init__(self, message):
        self.message = message

    def invoke(self, *args, **kwargs):
        return {
            "messages": [self.message],
            "structured_response": {
                "status": "COMPLETED",
                "screening_status": "CONFIRMED_MATCH",
                "available": True,
                "findings": [
                    {
                        "finding_id": "FIND-E2E-001",
                        "finding_type": "SCREENING_RESULT",
                        "summary": "Strong identifier screening match",
                        "evidence_ids": ["EV-SCREENING-WL-E2E-001"],
                        "entity_scope": "SHB_INTERNAL",
                        "match_basis": "IDENTIFIER",
                    }
                ],
            },
        }


def test_screening_tool_to_orchestrator_worker_boundary_end_to_end():
    tools = build_screening_tools(ScreeningFacade(StaticProvider()))
    registry = ToolRegistry()
    registry.register("screening", tools)
    registered = registry.tools_for("screening")
    message = tool_message(registered[0])

    results, warnings = collect_tool_results([message], {registered[0].name})
    output = invoke_worker(
        "screening",
        ScreeningAgentFixture(message),
        registered,
        "case context",
    )

    assert warnings == []
    assert results[0].status == "SUCCESS"
    assert results[0].data["match_basis"] == "IDENTIFIER"
    assert output["available"] is True
    assert output["status"] == "CONFIRMED_MATCH"
    assert output["findings"][0]["finding_id"] == "FIND-E2E-001"
    assert output["evidence"][0]["evidence_id"] == "EV-SCREENING-WL-E2E-001"
