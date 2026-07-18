from datetime import datetime

import pandas as pd

from app.data.provider import get_initialized_data_repository
from app.schemas.common import FundPath, TraceDirection
from app.schemas.tools import TraceFundsOutput


def trace_funds(
    seed_account_ids: list[str],
    direction: TraceDirection | str,
    max_depth: int = 3,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
) -> TraceFundsOutput:
    repo = get_initialized_data_repository()
    # Access the full transaction graph directly
    graph = repo.transaction_graph
    
    dir_enum = TraceDirection(direction) if isinstance(direction, str) else direction
    
    start = pd.to_datetime(start_time, utc=True) if start_time else None
    end = pd.to_datetime(end_time, utc=True) if end_time else None
    
    paths: list[FundPath] = []
    visited = set()
    
    # queue elements: (current_node, current_depth, path_nodes, path_txns, cumulative_amount, timestamps)
    queue = []
    for seed in seed_account_ids:
        if seed in graph:
            queue.append((seed, 0, [seed], [], 0.0, []))
            visited.add(seed)
            
    while queue:
        current, depth, path_nodes, path_txns, cum_amt, timestamps = queue.pop(0)
        
        if depth >= max_depth:
            continue
            
        # Get neighbors
        if dir_enum == TraceDirection.FORWARD:
            # Edges out of current
            edges = graph.out_edges(current, keys=True, data=True)
        else:
            # Edges into current
            edges = graph.in_edges(current, keys=True, data=True)
            
        for u, v, key, data in edges:
            # u -> v is the edge. For FORWARD, u is current. For BACKWARD, v is current.
            neighbor = v if dir_enum == TraceDirection.FORWARD else u
            
            # Apply time filters
            occurred_at = pd.to_datetime(data["occurred_at"])
            if start and occurred_at < start:
                continue
            if end and occurred_at > end:
                continue
                
            amount = float(data["amount"])
            
            new_path_nodes = path_nodes + [neighbor]
            new_path_txns = path_txns + [key]
            new_timestamps = timestamps + [occurred_at]
            new_cum_amt = cum_amt + amount
            
            paths.append(
                FundPath(
                    path=new_path_nodes,
                    transactions=new_path_txns,
                    total_amount=new_cum_amt,
                    timestamps=new_timestamps
                )
            )
            
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1, new_path_nodes, new_path_txns, new_cum_amt, new_timestamps))
                
    # Build a typed GraphSnapshot for the subgraph of all visited accounts.
    # graph_to_dict() only emits id/attributes bags and cannot validate as
    # GraphSnapshot (which requires node_type / edge_type).
    from app.services.serialization import graph_to_snapshot

    subgraph = repo.transaction_subgraph(list(visited))
    snapshot = graph_to_snapshot(subgraph)

    return TraceFundsOutput(
        paths=paths,
        visited_accounts=list(visited),
        graph_snapshot=snapshot
    )
