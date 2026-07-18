"""KYC registration checks at the orchestration boundary."""

from app.investigation_orchestrator.production_tools import (
    register_production_kyc_tools,
)
from app.investigation_orchestrator.tool_registry import ToolRegistry


EXPECTED_KYC_TOOLS = {
    "get_company_profile",
    "get_kyc_documents",
    "build_ownership_graph",
    "calculate_ubo",
    "find_ownership_gaps",
}


def test_kyc_domain_factory_is_registered_only_for_its_owner() -> None:
    registry = ToolRegistry()

    register_production_kyc_tools(registry, facade=object())

    assert {tool.name for tool in registry.tools_for("kyc")} == EXPECTED_KYC_TOOLS
    assert registry.tools_for("transaction") == ()
    assert registry.tools_for("screening") == ()
