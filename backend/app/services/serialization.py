"""JSON-safe serialization helpers for backend-owned data services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import networkx as nx
import pandas as pd

from app.schemas.common import EdgeType, GraphEdge, GraphNode, GraphSnapshot, NodeType


def json_safe(value: Any) -> Any:
    """Convert Pandas/NumPy values and nested containers to JSON-safe values."""

    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def series_to_dict(series: pd.Series | None) -> dict[str, Any] | None:
    return None if series is None else json_safe(series.to_dict())


def frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [json_safe(record) for record in frame.to_dict(orient="records")]


def graph_to_dict(graph: nx.Graph) -> dict[str, Any]:
    """Serialize a copied graph without leaking the NetworkX object.

    This remains a generic JSON bag. Prefer :func:`graph_to_snapshot` when the
    caller needs the typed ``GraphSnapshot`` contract (node_type / edge_type).
    """

    nodes = [
        {"id": str(node_id), "attributes": json_safe(dict(attributes))}
        for node_id, attributes in graph.nodes(data=True)
    ]
    if graph.is_multigraph():
        edges = [
            {
                "source": str(source),
                "target": str(target),
                "key": str(key),
                "attributes": json_safe(dict(attributes)),
            }
            for source, target, key, attributes in graph.edges(keys=True, data=True)
        ]
    else:
        edges = [
            {
                "source": str(source),
                "target": str(target),
                "attributes": json_safe(dict(attributes)),
            }
            for source, target, attributes in graph.edges(data=True)
        ]
    return {"metadata": json_safe(dict(graph.graph)), "nodes": nodes, "edges": edges}


def _as_attribute_dict(attributes: Any) -> dict[str, Any]:
    cleaned = json_safe(dict(attributes))
    return cleaned if isinstance(cleaned, dict) else {}


def _infer_node_type(
    node_id: str,
    attributes: dict[str, Any],
    graph_type: str | None,
) -> NodeType:
    raw = attributes.get("node_type")
    if isinstance(raw, NodeType):
        return raw
    if isinstance(raw, str):
        try:
            return NodeType(raw)
        except ValueError:
            pass

    entity_type = attributes.get("entity_type")
    if entity_type == "CUSTOMER":
        return NodeType.PERSON
    if entity_type == "COMPANY":
        return NodeType.COMPANY

    if graph_type == "transaction" or "account_type" in attributes:
        return NodeType.ACCOUNT

    if node_id.startswith(("ACCT-", "EXT-ACC-")):
        return NodeType.ACCOUNT
    if node_id.startswith("CUST-"):
        return NodeType.PERSON
    if node_id.startswith("COMP-"):
        return NodeType.COMPANY

    # Repository transaction graphs only store account endpoints.
    return NodeType.ACCOUNT


def _infer_edge_type(
    attributes: dict[str, Any],
    graph_type: str | None,
) -> EdgeType:
    raw = attributes.get("edge_type")
    if isinstance(raw, EdgeType):
        return raw
    if isinstance(raw, str):
        try:
            return EdgeType(raw)
        except ValueError:
            pass

    if graph_type == "ownership" or "ownership_percentage" in attributes:
        return EdgeType.OWNS_ACCOUNT
    if graph_type == "entity_relationship":
        # Entity relationship edges are not ownership or transfers; keep a
        # stable, allowed EdgeType for snapshot consumers that only inspect
        # TRANSFERRED_TO when scoring risk.
        return EdgeType.SHARES_ADDRESS

    # Default for transaction MultiDiGraphs used by fund tracing.
    return EdgeType.TRANSFERRED_TO


def graph_to_snapshot(graph: nx.Graph) -> GraphSnapshot:
    """Convert a NetworkX graph into the typed ``GraphSnapshot`` contract.

    Repository graphs store type hints as attributes / graph metadata, not as
    top-level NetworkX fields. This helper materializes ``node_type`` and
    ``edge_type`` so callers can validate against ``GraphSnapshot``.
    """

    graph_type = graph.graph.get("graph_type")
    if graph_type is not None and not isinstance(graph_type, str):
        graph_type = str(graph_type)

    nodes: list[GraphNode] = []
    for node_id, raw_attrs in graph.nodes(data=True):
        attrs = _as_attribute_dict(raw_attrs)
        nodes.append(
            GraphNode(
                id=str(node_id),
                node_type=_infer_node_type(str(node_id), attrs, graph_type),
                attributes=attrs,
            )
        )

    edges: list[GraphEdge] = []
    if graph.is_multigraph():
        for source, target, key, raw_attrs in graph.edges(keys=True, data=True):
            attrs = _as_attribute_dict(raw_attrs)
            edges.append(
                GraphEdge(
                    source=str(source),
                    target=str(target),
                    edge_type=_infer_edge_type(attrs, graph_type),
                    key=str(key),
                    attributes=attrs,
                )
            )
    else:
        for source, target, raw_attrs in graph.edges(data=True):
            attrs = _as_attribute_dict(raw_attrs)
            edges.append(
                GraphEdge(
                    source=str(source),
                    target=str(target),
                    edge_type=_infer_edge_type(attrs, graph_type),
                    attributes=attrs,
                )
            )

    metadata = json_safe(dict(graph.graph))
    return GraphSnapshot(
        nodes=nodes,
        edges=edges,
        metadata=metadata if isinstance(metadata, dict) else {},
    )
