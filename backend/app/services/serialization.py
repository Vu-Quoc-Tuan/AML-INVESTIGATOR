"""JSON-safe serialization helpers for backend-owned data services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import networkx as nx
import pandas as pd


def json_safe(value: Any) -> Any:
    """Convert Pandas/NumPy values and nested containers to JSON-safe values."""

    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
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
    """Serialize a copied graph without leaking the NetworkX object."""

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
