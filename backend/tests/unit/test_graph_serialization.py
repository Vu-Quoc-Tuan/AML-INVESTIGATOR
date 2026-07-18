"""Typed GraphSnapshot serialization for repository NetworkX graphs."""

from pathlib import Path

import networkx as nx
import pytest

from app.data.provider import (
    _reset_data_repository_for_testing,
    initialize_data_repository,
)
from app.investigation_orchestrator.production_tools import build_production_tool_registry
from app.schemas.common import EdgeType, GraphSnapshot, NodeType
from app.services.serialization import graph_to_dict, graph_to_snapshot
from app.transaction_investigation.fund_tracing import trace_funds


@pytest.fixture(autouse=True)
def reset_repository_provider():
    _reset_data_repository_for_testing()
    yield
    _reset_data_repository_for_testing()


def test_graph_to_snapshot_adds_required_types_for_transaction_graph() -> None:
    graph = nx.MultiDiGraph(graph_type="transaction")
    graph.add_node("ACCT-SHB-1", account_type="INTERNAL_SHB", bank_id="BANK-SHB-001")
    graph.add_node("EXT-ACC-1", account_type="EXTERNAL", bank_id="BANK-X")
    graph.add_edge(
        "ACCT-SHB-1",
        "EXT-ACC-1",
        key="TX-1",
        amount=100.0,
        occurred_at="2026-01-01T00:00:00+00:00",
        evidence_source="SHB_TRANSACTION_LEDGER",
        data_visibility="FULL_INTERNAL",
    )

    snapshot = graph_to_snapshot(graph)

    assert isinstance(snapshot, GraphSnapshot)
    assert {node.id: node.node_type for node in snapshot.nodes} == {
        "ACCT-SHB-1": NodeType.ACCOUNT,
        "EXT-ACC-1": NodeType.ACCOUNT,
    }
    assert len(snapshot.edges) == 1
    edge = snapshot.edges[0]
    assert edge.edge_type == EdgeType.TRANSFERRED_TO
    assert edge.key == "TX-1"
    assert edge.attributes["amount"] == 100.0


def test_graph_to_dict_remains_untyped_bag() -> None:
    graph = nx.MultiDiGraph(graph_type="transaction")
    graph.add_node("ACCT-1", account_type="INTERNAL_SHB")
    bag = graph_to_dict(graph)

    assert bag["nodes"][0] == {
        "id": "ACCT-1",
        "attributes": {"account_type": "INTERNAL_SHB"},
    }
    assert "node_type" not in bag["nodes"][0]


def test_trace_funds_returns_valid_graph_snapshot_on_generated_data() -> None:
    data_path = Path(__file__).resolve().parents[2] / "data" / "generated"
    initialize_data_repository(data_path)

    result = trace_funds(
        seed_account_ids=["ACCT-SHB-000001"],
        direction="FORWARD",
        max_depth=1,
    )

    snapshot = result.graph_snapshot
    assert isinstance(snapshot, GraphSnapshot)
    assert snapshot.nodes
    assert all(node.node_type == NodeType.ACCOUNT for node in snapshot.nodes)
    assert all(
        edge.edge_type == EdgeType.TRANSFERRED_TO for edge in snapshot.edges
    )
    assert "ACCT-SHB-000001" in result.visited_accounts


def test_trace_funds_production_tool_invokes_without_validation_error() -> None:
    data_path = Path(__file__).resolve().parents[2] / "data" / "generated"
    initialize_data_repository(data_path)

    tool = build_production_tool_registry().get_tool("transaction", "trace_funds")
    out = tool.invoke(
        {
            "seed_account_ids": ["ACCT-SHB-000001"],
            "direction": "FORWARD",
            "max_depth": 1,
        }
    )

    import json

    payload = json.loads(out) if isinstance(out, str) else out
    if isinstance(payload, tuple):
        payload = payload[1]

    assert payload["status"] in {"SUCCESS", "NO_DATA", "INCONCLUSIVE"}
    assert payload.get("error_code") is None
    data = payload["data"]
    assert "graph_snapshot" in data
    assert data["graph_snapshot"]["nodes"]
    assert all("node_type" in node for node in data["graph_snapshot"]["nodes"])
    assert all("edge_type" in edge for edge in data["graph_snapshot"]["edges"])
