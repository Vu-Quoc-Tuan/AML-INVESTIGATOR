import pytest
from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from app.investigation_orchestrator.tool_registry import ToolRegistry, ToolResult
from app.transaction_investigation.tool_adapter import build_transaction_tools


TRANSACTION_TOOL_NAMES = {
    "get_account_transactions",
    "trace_funds",
    "detect_rapid_pass_through",
    "detect_fan_in_fan_out",
    "find_common_funding_sources",
    "find_shared_identifiers",
    "build_case_subgraph",
}

VALID_TOOL_INPUTS = {
    "get_account_transactions": {"account_id": "ACCT-SHB-001"},
    "trace_funds": {
        "seed_account_ids": ["ACCT-SHB-001"],
        "direction": "FORWARD",
    },
    "detect_rapid_pass_through": {"account_id": "ACCT-SHB-001"},
    "detect_fan_in_fan_out": {"account_id": "ACCT-SHB-001"},
    "find_common_funding_sources": {
        "account_ids": ["ACCT-SHB-001", "ACCT-SHB-002"]
    },
    "find_shared_identifiers": {
        "account_ids": ["ACCT-SHB-001", "ACCT-SHB-002"]
    },
    "build_case_subgraph": {"seed_entity_ids": ["ACCT-SHB-001"]},
}


def transaction(transaction_id: str = "TX-001") -> dict:
    return {
        "transaction_id": transaction_id,
        "source_account_ref": "ACCT-SHB-001",
        "destination_account_ref": "ACCT-SHB-002",
        "amount": 1250000.0,
        "occurred_at": "2026-01-01T10:00:00+00:00",
        "evidence_source": "SHB_TRANSACTION_LEDGER",
        "data_visibility": "FULL_INTERNAL",
    }


class StaticTransactionService:
    def get_account_transactions(self, *args, **kwargs):
        item = transaction()
        return {
            "transactions": [item],
            "counterparty_summary": [],
            "total_inbound_amount": 1250000.0,
            "total_outbound_amount": 0.0,
            "net_flow": 1250000.0,
            "count": 1,
        }

    def trace_funds(self, *args, **kwargs):
        item = transaction()
        return {
            "paths": [
                {
                    "path": ["ACCT-SHB-001", "ACCT-SHB-002"],
                    "transactions": [item["transaction_id"]],
                    "total_amount": item["amount"],
                    "timestamps": [item["occurred_at"]],
                }
            ],
            "visited_accounts": ["ACCT-SHB-001", "ACCT-SHB-002"],
            "graph_snapshot": {
                "nodes": [],
                "edges": [
                    {
                        "source": item["source_account_ref"],
                        "target": item["destination_account_ref"],
                        "edge_type": "TRANSFERRED_TO",
                        "key": item["transaction_id"],
                        "attributes": {
                            key: value
                            for key, value in item.items()
                            if key
                            not in {
                                "transaction_id",
                                "source_account_ref",
                                "destination_account_ref",
                            }
                        },
                    }
                ],
                "metadata": {},
            },
        }

    def detect_rapid_pass_through(self, *args, **kwargs):
        return {
            "pass_through_findings": [
                {
                    "finding_type": "RAPID_PASS_THROUGH",
                    "statement": "Funds moved rapidly",
                    "evidence_ids": ["TX-001"],
                    "confidence": 0.95,
                }
            ]
        }

    def detect_fan_in_fan_out(self, *args, **kwargs):
        return {"fan_in_findings": [], "fan_out_findings": []}

    def find_common_funding_sources(self, *args, **kwargs):
        return {"common_sources": [], "findings": []}

    def find_shared_identifiers(self, *args, **kwargs):
        return {
            "shared_devices": [],
            "shared_ips": [],
            "shared_addresses": [],
            "findings": [],
        }

    def build_case_subgraph(self, *args, **kwargs):
        return self.trace_funds()["graph_snapshot"]


class EmptyTransactionService(StaticTransactionService):
    def get_account_transactions(self, *args, **kwargs):
        return {
            "transactions": [],
            "counterparty_summary": [],
            "total_inbound_amount": 0.0,
            "total_outbound_amount": 0.0,
            "net_flow": 0.0,
            "count": 0,
        }


def invoke_tool(tool, args: dict) -> ToolMessage:
    message = tool.invoke(
        {"name": tool.name, "args": args, "id": "CALL-TX-001", "type": "tool_call"}
    )
    assert isinstance(message, ToolMessage)
    return message


def test_factory_exposes_only_approved_transaction_tools() -> None:
    tools = build_transaction_tools(StaticTransactionService())

    assert {tool.name for tool in tools} == TRANSACTION_TOOL_NAMES
    assert len(tools) == len(TRANSACTION_TOOL_NAMES)


@pytest.mark.parametrize("tool_name", sorted(TRANSACTION_TOOL_NAMES))
def test_every_approved_tool_returns_the_orchestrator_contract(tool_name: str) -> None:
    tool = next(
        tool
        for tool in build_transaction_tools(StaticTransactionService())
        if tool.name == tool_name
    )

    result = ToolResult.model_validate(
        invoke_tool(tool, VALID_TOOL_INPUTS[tool_name]).artifact
    )

    assert result.status in {"SUCCESS", "NO_DATA"}


def test_account_query_artifact_preserves_transaction_provenance() -> None:
    tool = next(
        tool
        for tool in build_transaction_tools(StaticTransactionService())
        if tool.name == "get_account_transactions"
    )

    parsed = ToolResult.model_validate(
        invoke_tool(tool, {"account_id": "ACCT-SHB-001"}).artifact
    )

    assert parsed.status == "SUCCESS"
    assert parsed.evidence[0].evidence_id == "TX-001"
    assert parsed.evidence[0].source_system == "SHB_TRANSACTION_LEDGER"
    assert parsed.evidence[0].source_record_id == "TX-001"
    assert parsed.evidence[0].visibility_level == "FULL_INTERNAL"


def test_pattern_tool_resolves_only_tool_referenced_evidence() -> None:
    tool = next(
        tool
        for tool in build_transaction_tools(StaticTransactionService())
        if tool.name == "detect_rapid_pass_through"
    )

    parsed = ToolResult.model_validate(
        invoke_tool(
            tool,
            {"account_id": "ACCT-SHB-001", "time_window_hours": 24.0},
        ).artifact
    )

    assert parsed.status == "SUCCESS"
    assert [item.evidence_id for item in parsed.evidence] == ["TX-001"]


def test_empty_account_query_returns_no_data_without_evidence() -> None:
    tool = next(
        tool
        for tool in build_transaction_tools(EmptyTransactionService())
        if tool.name == "get_account_transactions"
    )

    parsed = ToolResult.model_validate(
        invoke_tool(tool, {"account_id": "ACCT-SHB-MISSING"}).artifact
    )

    assert parsed.status == "NO_DATA"
    assert parsed.evidence == []


def test_transaction_inputs_are_strict_and_tools_are_owner_scoped() -> None:
    tools = build_transaction_tools(StaticTransactionService())
    registry = ToolRegistry()
    registry.register("transaction", tools)

    assert registry.tools_for("kyc") == ()
    assert registry.tools_for("screening") == ()
    with pytest.raises(ValidationError):
        registry.get_tool("transaction", "get_account_transactions").invoke(
            {"account_id": "ACCT-SHB-001", "unexpected": True}
        )
