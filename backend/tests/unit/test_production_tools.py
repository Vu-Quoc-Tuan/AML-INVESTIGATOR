import pytest

from app.investigation_orchestrator.production_tools import (
    build_production_tool_registry,
    register_production_kyc_tools,
    register_production_transaction_tools,
)
from app.investigation_orchestrator.tool_registry import (
    ToolConfigurationError,
    ToolRegistry,
)


EXPECTED_TRANSACTION_TOOLS = {
    "get_account_transactions",
    "trace_funds",
    "detect_rapid_pass_through",
    "detect_fan_in_fan_out",
    "find_common_funding_sources",
    "find_shared_identifiers",
    "build_case_subgraph",
}
EXPECTED_KYC_TOOLS = {
    "get_company_profile",
    "get_kyc_documents",
    "build_ownership_graph",
    "calculate_ubo",
    "find_ownership_gaps",
}


def test_production_registration_scopes_transaction_tools_to_owner() -> None:
    registry = ToolRegistry()

    register_production_transaction_tools(registry, service=object())

    assert {tool.name for tool in registry.tools_for("transaction")} == (
        EXPECTED_TRANSACTION_TOOLS
    )
    assert registry.tools_for("kyc") == ()
    assert registry.tools_for("screening") == ()


def test_required_owner_validation_reports_only_missing_owners() -> None:
    registry = ToolRegistry()
    register_production_transaction_tools(registry, service=object())

    with pytest.raises(
        ToolConfigurationError,
        match=r"Missing required tools for owners: kyc, screening$",
    ):
        registry.require_tools()


def test_production_registration_scopes_kyc_tools_to_owner() -> None:
    registry = ToolRegistry()

    register_production_kyc_tools(registry, facade=object())

    assert {tool.name for tool in registry.tools_for("kyc")} == EXPECTED_KYC_TOOLS
    assert registry.tools_for("transaction") == ()
    assert registry.tools_for("screening") == ()


def test_duplicate_production_registration_is_a_configuration_error() -> None:
    registry = ToolRegistry()
    register_production_transaction_tools(registry, service=object())

    with pytest.raises(ToolConfigurationError, match="Transaction tool registration"):
        register_production_transaction_tools(registry, service=object())


def test_composition_root_registers_agent_tool_owners_without_legal() -> None:
    registry = build_production_tool_registry()

    registry.require_tools()
    assert {tool.name for tool in registry.tools_for("transaction")} == (
        EXPECTED_TRANSACTION_TOOLS
    )
    assert {tool.name for tool in registry.tools_for("kyc")} == EXPECTED_KYC_TOOLS
    assert registry.tools_for("screening")
    # Legal RAG is a deterministic node, not a required tool owner.
    assert registry.tools_for("legal") == ()
