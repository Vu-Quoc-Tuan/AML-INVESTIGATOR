from datetime import datetime
import pandas as pd

from app.data.provider import get_initialized_data_repository
from app.schemas.common import GraphSnapshot, NodeType, EdgeType, GraphNode, GraphEdge

def build_case_subgraph(
    seed_entity_ids: list[str],
    max_depth: int = 2,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
) -> GraphSnapshot:
    repo = get_initialized_data_repository()
    
    # 1. Resolve entity IDs to account IDs
    account_ids = set()
    
    for entity_id in seed_entity_ids:
        if entity_id in repo._frames["accounts"]["account_id"].values:
            account_ids.add(entity_id)
        else:
            accs = repo._frames["accounts"][repo._frames["accounts"]["owner_entity_id"] == entity_id]["account_id"].tolist()
            account_ids.update(accs)
            
    # 2. Expand transaction graph to max_depth
    tx_graph = repo._DataRepository__transaction_graph
    neighborhood = set(account_ids)
    current_layer = set(account_ids)
    
    for _ in range(max_depth):
        next_layer = set()
        for node in current_layer:
            if node in tx_graph:
                for succ in tx_graph.successors(node):
                    next_layer.add(succ)
                for pred in tx_graph.predecessors(node):
                    next_layer.add(pred)
        neighborhood.update(next_layer)
        current_layer = next_layer
        
    subgraph = tx_graph.subgraph(neighborhood)
    
    # 3. Build GraphSnapshot with typed nodes and edges
    nodes = []
    edges = []
    
    acc_df = repo._frames["accounts"].set_index("account_id")
    ext_acc_df = repo._frames["external_accounts"].set_index("external_account_id")
    cust_df = repo._frames["customers"].set_index("customer_id")
    comp_df = repo._frames["companies"].set_index("company_id")
    
    for node_id in subgraph.nodes():
        node_attrs = dict(subgraph.nodes[node_id])
        node_type = NodeType.ACCOUNT
        
        if node_id in acc_df.index:
            row = acc_df.loc[node_id]
            node_attrs.update(row.dropna().to_dict())
            node_attrs["is_internal"] = True
        elif node_id in ext_acc_df.index:
            row = ext_acc_df.loc[node_id]
            node_attrs.update(row.dropna().to_dict())
            node_attrs["is_internal"] = False
            # Data completeness flag for external accounts
            node_attrs["data_completeness"] = "PAYMENT_MESSAGE_ONLY"
            
        nodes.append(GraphNode(id=node_id, node_type=node_type, attributes=node_attrs))
        
        # Add Owner nodes for internal accounts
        if node_id in acc_df.index:
            owner_id = acc_df.loc[node_id]["owner_entity_id"]
            owner_type_str = acc_df.loc[node_id]["owner_entity_type"]
            
            owner_node_type = NodeType.PERSON if owner_type_str == "CUSTOMER" else NodeType.COMPANY
            
            if owner_type_str == "CUSTOMER" and owner_id in cust_df.index:
                owner_attrs = cust_df.loc[owner_id].dropna().to_dict()
            elif owner_type_str == "COMPANY" and owner_id in comp_df.index:
                owner_attrs = comp_df.loc[owner_id].dropna().to_dict()
            else:
                owner_attrs = {}
                
            nodes.append(GraphNode(id=owner_id, node_type=owner_node_type, attributes=owner_attrs))
            
            edges.append(GraphEdge(
                source=owner_id,
                target=node_id,
                edge_type=EdgeType.OWNS_ACCOUNT,
                attributes={"relationship": "owner"}
            ))
            
    # Deduplicate nodes
    seen_nodes = set()
    unique_nodes = []
    for n in nodes:
        if n.id not in seen_nodes:
            seen_nodes.add(n.id)
            # Ensure attributes don't contain NaNs
            cleaned_attrs = {}
            for k, v in n.attributes.items():
                if isinstance(v, float) and pd.isna(v):
                    continue
                if isinstance(v, pd.Timestamp) or isinstance(v, datetime):
                    cleaned_attrs[k] = v.isoformat()
                else:
                    cleaned_attrs[k] = v
            n.attributes = cleaned_attrs
            unique_nodes.append(n)
            
    start = pd.to_datetime(start_time, utc=True) if start_time else None
    end = pd.to_datetime(end_time, utc=True) if end_time else None
    
    for u, v, k, data in subgraph.edges(keys=True, data=True):
        occurred_at = pd.to_datetime(data["occurred_at"])
        if start and occurred_at < start: continue
        if end and occurred_at > end: continue
        
        edge_attrs = dict(data)
        if isinstance(edge_attrs["occurred_at"], pd.Timestamp):
            edge_attrs["occurred_at"] = edge_attrs["occurred_at"].isoformat()
            
        edges.append(GraphEdge(
            source=u,
            target=v,
            edge_type=EdgeType.TRANSFERRED_TO,
            key=str(k),
            attributes=edge_attrs
        ))
        
    return GraphSnapshot(nodes=unique_nodes, edges=edges, metadata={"max_depth": max_depth})
