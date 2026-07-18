import networkx as nx
import pandas as pd
from typing import Any

from app.schemas.common import GraphSnapshot, PatternFinding, PatternType
from app.schemas.tools import CalculateGraphRiskOutput

def calculate_graph_risk(graph_snapshot: dict | GraphSnapshot) -> CalculateGraphRiskOutput:
    if isinstance(graph_snapshot, dict):
        graph_snapshot = GraphSnapshot(**graph_snapshot)
        
    G = nx.DiGraph()
    for n in graph_snapshot.nodes:
        G.add_node(n.id, **n.attributes)
        
    for e in graph_snapshot.edges:
        if e.edge_type == "TRANSFERRED_TO":
            amt = float(e.attributes.get("amount", 0.0))
            if G.has_edge(e.source, e.target):
                G[e.source][e.target]["weight"] += amt
            else:
                G.add_edge(e.source, e.target, weight=amt)
                
    if len(G.nodes) == 0:
        return CalculateGraphRiskOutput(risk_scores={}, network_metrics={}, findings=[])
        
    density = nx.density(G)
    num_components = nx.number_weakly_connected_components(G)
    
    try:
        cycles = list(nx.simple_cycles(G))
        cycle_count = len(cycles)
    except Exception:
        cycle_count = 0
        
    network_metrics = {
        "density": density,
        "components_count": num_components,
        "cycle_count": cycle_count
    }
    
    in_degree = dict(G.in_degree())
    out_degree = dict(G.out_degree())
    try:
        betweenness = nx.betweenness_centrality(G)
    except Exception:
        betweenness = {n: 0.0 for n in G.nodes()}
        
    try:
        pagerank = nx.pagerank(G, weight="weight")
    except Exception:
        pagerank = {n: 0.0 for n in G.nodes()}
        
    risk_scores = {}
    findings = []
    
    for node in G.nodes():
        score = 0.0
        
        if betweenness[node] > 0.3:
            score += 0.4
            findings.append(PatternFinding(
                finding_type=PatternType.GATHER_SCATTER,
                statement=f"Node {node} has high betweenness centrality ({betweenness[node]:.2f}), acting as a key intermediary.",
                evidence_ids=[],
                confidence=0.8
            ))
            
        if pagerank[node] > 0.2:
            score += 0.3
            
        if in_degree[node] > 5 and out_degree[node] == 0:
            score += 0.3
        elif out_degree[node] > 5 and in_degree[node] == 0:
            score += 0.3
            
        risk_scores[node] = min(1.0, score)
        
    return CalculateGraphRiskOutput(
        risk_scores=risk_scores,
        network_metrics=network_metrics,
        findings=findings
    )
