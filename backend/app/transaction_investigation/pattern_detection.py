import pandas as pd

from app.data.provider import get_initialized_data_repository
from app.schemas.common import PatternFinding, PatternType
from app.schemas.tools import (
    DetectFanInOutOutput,
    DetectRapidPassThroughOutput,
    DetectStructuringOutput,
    DetectCyclesOutput,
    FindCommonSourcesOutput,
    FindCommonDestinationsOutput,
    FindSharedIdentifiersOutput,
    FindCoordinatedAmountsOutput,
    DetectRoundTrippingOutput
)
from app.transaction_investigation.config import load_config
from app.transaction_investigation.transaction_queries import get_account_transactions

def detect_fan_in_fan_out(account_id: str, time_window_hours: float = 24.0) -> DetectFanInOutOutput:
    config = load_config()
    
    txns = get_account_transactions(account_id).transactions
    if not txns:
        return DetectFanInOutOutput(fan_in_findings=[], fan_out_findings=[])
        
    df = pd.DataFrame(txns)
    df["occurred_at"] = pd.to_datetime(df["occurred_at"])
    df = df.sort_values("occurred_at")
    
    fan_in_findings = []
    fan_out_findings = []
    
    for index, row in df.iterrows():
        end_time = row["occurred_at"]
        start_time = end_time - pd.Timedelta(hours=time_window_hours)
        
        window_df = df[(df["occurred_at"] >= start_time) & (df["occurred_at"] <= end_time)]
        
        inbound = window_df[window_df["effective_direction"] == "INBOUND"]
        outbound = window_df[window_df["effective_direction"] == "OUTBOUND"]
        
        unique_sources = inbound["source_account_ref"].nunique()
        if unique_sources >= config.thresholds.fan_in_min_sources:
            evidence_ids = inbound["transaction_id"].tolist()
            statement = f"Fan-in pattern detected: {unique_sources} unique sources within {time_window_hours} hours."
            confidence = min(1.0, unique_sources / (config.thresholds.fan_in_min_sources * 2))
            finding = PatternFinding(
                finding_type=PatternType.FAN_IN,
                statement=statement,
                evidence_ids=evidence_ids,
                confidence=confidence
            )
            if not any(set(evidence_ids).issubset(set(f.evidence_ids)) for f in fan_in_findings):
                fan_in_findings.append(finding)
                
        unique_dests = outbound["destination_account_ref"].nunique()
        if unique_dests >= config.thresholds.fan_out_min_destinations:
            evidence_ids = outbound["transaction_id"].tolist()
            statement = f"Fan-out pattern detected: {unique_dests} unique destinations within {time_window_hours} hours."
            confidence = min(1.0, unique_dests / (config.thresholds.fan_out_min_destinations * 2))
            finding = PatternFinding(
                finding_type=PatternType.FAN_OUT,
                statement=statement,
                evidence_ids=evidence_ids,
                confidence=confidence
            )
            if not any(set(evidence_ids).issubset(set(f.evidence_ids)) for f in fan_out_findings):
                fan_out_findings.append(finding)
                
    return DetectFanInOutOutput(fan_in_findings=fan_in_findings, fan_out_findings=fan_out_findings)

def detect_rapid_pass_through(account_id: str, time_window_hours: float = 24.0) -> DetectRapidPassThroughOutput:
    config = load_config()
    txns = get_account_transactions(account_id).transactions
    if not txns:
        return DetectRapidPassThroughOutput(pass_through_findings=[])
        
    df = pd.DataFrame(txns)
    df["occurred_at"] = pd.to_datetime(df["occurred_at"])
    df = df.sort_values("occurred_at")
    
    findings = []
    
    for index, row in df.iterrows():
        if row["effective_direction"] != "INBOUND":
            continue
            
        start_time = row["occurred_at"]
        end_time = start_time + pd.Timedelta(hours=time_window_hours)
        
        window_df = df[(df["occurred_at"] >= start_time) & (df["occurred_at"] <= end_time)]
        inbound_sum = window_df[window_df["effective_direction"] == "INBOUND"]["amount"].sum()
        outbound_sum = window_df[window_df["effective_direction"] == "OUTBOUND"]["amount"].sum()
        
        if inbound_sum == 0:
            continue
            
        ratio = outbound_sum / inbound_sum
        if ratio >= config.thresholds.pass_through_min_ratio:
            evidence_ids = window_df["transaction_id"].tolist()
            time_diff = (window_df["occurred_at"].max() - window_df["occurred_at"].min()).total_seconds()
            statement = f"{ratio*100:.1f}% of incoming funds left within {time_diff} seconds."
            confidence = min(1.0, ratio)
            
            finding = PatternFinding(
                finding_type=PatternType.RAPID_PASS_THROUGH,
                statement=statement,
                evidence_ids=evidence_ids,
                confidence=confidence
            )
            if not any(set(evidence_ids).issubset(set(f.evidence_ids)) for f in findings):
                findings.append(finding)
                
    return DetectRapidPassThroughOutput(pass_through_findings=findings)

def detect_structuring(account_id: str, time_window_hours: float = 24.0) -> DetectStructuringOutput:
    config = load_config()
    txns = get_account_transactions(account_id).transactions
    if not txns:
        return DetectStructuringOutput(structuring_findings=[])
        
    df = pd.DataFrame(txns)
    df["occurred_at"] = pd.to_datetime(df["occurred_at"])
    df = df.sort_values("occurred_at")
    
    threshold = config.thresholds.structuring_threshold_amount
    lower_bound = threshold * 0.90
    
    struct_txns = df[(df["amount"] >= lower_bound) & (df["amount"] < threshold)]
    
    findings = []
    
    for index, row in struct_txns.iterrows():
        start_time = row["occurred_at"]
        end_time = start_time + pd.Timedelta(hours=time_window_hours)
        
        window_df = struct_txns[(struct_txns["occurred_at"] >= start_time) & (struct_txns["occurred_at"] <= end_time)]
        if len(window_df) >= config.thresholds.structuring_min_transactions:
            evidence_ids = window_df["transaction_id"].tolist()
            statement = f"{len(window_df)} transfers just under threshold arrived within {time_window_hours} hours."
            finding = PatternFinding(
                finding_type=PatternType.STRUCTURING,
                statement=statement,
                evidence_ids=evidence_ids,
                confidence=0.9
            )
            if not any(set(evidence_ids).issubset(set(f.evidence_ids)) for f in findings):
                findings.append(finding)
                
    return DetectStructuringOutput(structuring_findings=findings)

def detect_cycles(seed_account_id: str, max_depth: int = 5) -> DetectCyclesOutput:
    repo = get_initialized_data_repository()
    graph = repo.transaction_graph
    
    if seed_account_id not in graph:
        return DetectCyclesOutput(cycles=[], cycle_findings=[])
        
    cycles = []
    findings = []
    
    stack = [(seed_account_id, [seed_account_id], [])]
    
    while stack:
        current, path, timestamps = stack.pop()
        
        if len(path) > max_depth + 1:
            continue
            
        for succ in graph.successors(current):
            edges = graph.get_edge_data(current, succ)
            if not edges: continue
            
            last_time = timestamps[-1][0] if timestamps else None
            
            valid_edges = []
            for k, data in edges.items():
                occurred_at = pd.to_datetime(data["occurred_at"])
                if last_time is None or occurred_at >= last_time:
                    valid_edges.append((occurred_at, k))
                    
            if not valid_edges:
                continue
                
            valid_edges.sort()
            best_edge = valid_edges[0]
            
            if succ == seed_account_id and len(path) > 1:
                cycle_nodes = path
                evidence_ids = [e[1] for e in timestamps] + [best_edge[1]]
                
                # Check if this exact cycle is already found
                found = False
                for c in cycles:
                    if len(c) == len(cycle_nodes) and all(a == b for a, b in zip(c, cycle_nodes)):
                        found = True
                        break
                        
                if not found:
                    cycles.append(cycle_nodes)
                    findings.append(PatternFinding(
                        finding_type=PatternType.CYCLE,
                        statement=f"Cycle detected involving {len(cycle_nodes)} accounts.",
                        evidence_ids=evidence_ids,
                        confidence=1.0
                    ))
            elif succ not in path:
                stack.append((succ, path + [succ], timestamps + [best_edge]))
                
    return DetectCyclesOutput(cycles=cycles, cycle_findings=findings)

def find_common_funding_sources(account_ids: list[str], lookback_period_hours: float = 24.0) -> FindCommonSourcesOutput:
    repo = get_initialized_data_repository()
    graph = repo.transaction_graph
    
    sources_map = {}
    for acc in account_ids:
        if acc not in graph:
            continue
        sources_map[acc] = set()
        for u, v, k, data in graph.in_edges(acc, keys=True, data=True):
            sources_map[acc].add((u, k))
            
    if not sources_map:
        return FindCommonSourcesOutput(common_sources=[], findings=[])
        
    common_source_nodes = set.intersection(*(set([u for u, k in s]) for s in sources_map.values() if s))
    
    findings = []
    if common_source_nodes:
        for source in common_source_nodes:
            evidence_ids = []
            for acc in account_ids:
                if acc in sources_map:
                    evidence_ids.extend([k for u, k in sources_map[acc] if u == source])
            
            finding = PatternFinding(
                finding_type=PatternType.COMMON_FUNDING_SOURCE,
                statement=f"Common funding source '{source}' found for {len(account_ids)} accounts.",
                evidence_ids=evidence_ids,
                confidence=0.8
            )
            findings.append(finding)
            
    return FindCommonSourcesOutput(common_sources=list(common_source_nodes), findings=findings)

def find_common_destinations(account_ids: list[str], lookforward_period_hours: float = 24.0) -> FindCommonDestinationsOutput:
    repo = get_initialized_data_repository()
    graph = repo.transaction_graph
    
    dest_map = {}
    for acc in account_ids:
        if acc not in graph:
            continue
        dest_map[acc] = set()
        for u, v, k, data in graph.out_edges(acc, keys=True, data=True):
            dest_map[acc].add((v, k))
            
    if not dest_map:
        return FindCommonDestinationsOutput(common_destinations=[], findings=[])
        
    common_dest_nodes = set.intersection(*(set([v for v, k in d]) for d in dest_map.values() if d))
    
    findings = []
    if common_dest_nodes:
        for dest in common_dest_nodes:
            evidence_ids = []
            for acc in account_ids:
                if acc in dest_map:
                    evidence_ids.extend([k for v, k in dest_map[acc] if v == dest])
            
            finding = PatternFinding(
                finding_type=PatternType.COMMON_DESTINATION,
                statement=f"Common destination '{dest}' found for {len(account_ids)} accounts.",
                evidence_ids=evidence_ids,
                confidence=0.8
            )
            findings.append(finding)
            
    return FindCommonDestinationsOutput(common_destinations=list(common_dest_nodes), findings=findings)

def find_shared_identifiers(account_ids: list[str], identifier_types: list[str] | None = None) -> FindSharedIdentifiersOutput:
    repo = get_initialized_data_repository()
    tx_df = repo._frames["transactions"]
    
    mask = tx_df["source_account_ref"].isin(account_ids) | tx_df["destination_account_ref"].isin(account_ids)
    subset = tx_df[mask]
    
    shared_devices = []
    shared_ips = []
    findings = []
    
    if not subset.empty:
        ip_groups = subset.dropna(subset=["source_ip"]).groupby("source_ip")
        for ip, group in ip_groups:
            users = set(group["source_account_ref"]).intersection(account_ids)
            if len(users) > 1:
                shared_ips.append(ip)
                findings.append(PatternFinding(
                    finding_type=PatternType.GATHER_SCATTER,
                    statement=f"IP {ip} shared by {len(users)} accounts.",
                    evidence_ids=group["transaction_id"].tolist(),
                    confidence=0.7
                ))
                
        dev_groups = subset.dropna(subset=["device_id"]).groupby("device_id")
        for dev, group in dev_groups:
            users = set(group["source_account_ref"]).intersection(account_ids)
            if len(users) > 1:
                shared_devices.append(dev)
                findings.append(PatternFinding(
                    finding_type=PatternType.GATHER_SCATTER,
                    statement=f"Device {dev} shared by {len(users)} accounts.",
                    evidence_ids=group["transaction_id"].tolist(),
                    confidence=0.7
                ))
                
    return FindSharedIdentifiersOutput(
        shared_devices=shared_devices,
        shared_ips=shared_ips,
        shared_addresses=[],
        findings=findings
    )
    
def find_coordinated_amounts(account_id: str, time_window_hours: float = 24.0) -> FindCoordinatedAmountsOutput:
    config = load_config()
    txns = get_account_transactions(account_id).transactions
    if not txns:
        return FindCoordinatedAmountsOutput(findings=[])
        
    df = pd.DataFrame(txns)
    findings = []
    
    df = df.sort_values("amount")
    
    current_group = []
    current_amount = None
    
    for index, row in df.iterrows():
        amt = row["amount"]
        if current_amount is None:
            current_amount = amt
            current_group = [row]
            continue
            
        if abs(amt - current_amount) / current_amount <= config.thresholds.coordinated_amounts_tolerance:
            current_group.append(row)
        else:
            if len(current_group) >= config.thresholds.coordinated_amounts_min_transactions:
                group_df = pd.DataFrame(current_group)
                group_df["occurred_at"] = pd.to_datetime(group_df["occurred_at"])
                time_diff = (group_df["occurred_at"].max() - group_df["occurred_at"].min()).total_seconds() / 3600
                if time_diff <= time_window_hours:
                    evidence_ids = group_df["transaction_id"].tolist()
                    findings.append(PatternFinding(
                        finding_type=PatternType.COORDINATED_AMOUNTS,
                        statement=f"Found {len(current_group)} transactions with coordinated amounts ~{current_amount} within {time_diff:.1f} hours.",
                        evidence_ids=evidence_ids,
                        confidence=0.8
                    ))
            current_amount = amt
            current_group = [row]
            
    if len(current_group) >= config.thresholds.coordinated_amounts_min_transactions:
        group_df = pd.DataFrame(current_group)
        group_df["occurred_at"] = pd.to_datetime(group_df["occurred_at"])
        time_diff = (group_df["occurred_at"].max() - group_df["occurred_at"].min()).total_seconds() / 3600
        if time_diff <= time_window_hours:
            evidence_ids = group_df["transaction_id"].tolist()
            findings.append(PatternFinding(
                finding_type=PatternType.COORDINATED_AMOUNTS,
                statement=f"Found {len(current_group)} transactions with coordinated amounts ~{current_amount} within {time_diff:.1f} hours.",
                evidence_ids=evidence_ids,
                confidence=0.8
            ))
            
    return FindCoordinatedAmountsOutput(findings=findings)

def detect_round_tripping(account_id: str, time_window_hours: float = 24.0) -> DetectRoundTrippingOutput:
    repo = get_initialized_data_repository()
    graph = repo.transaction_graph
    
    findings = []
    
    if account_id in graph:
        for succ in graph.successors(account_id):
            if succ == account_id: continue
            for edges_out_1 in graph.get_edge_data(account_id, succ).values():
                t1 = pd.to_datetime(edges_out_1["occurred_at"])
                if graph.has_edge(succ, account_id):
                    for k2, edges_out_2 in graph.get_edge_data(succ, account_id).items():
                        t2 = pd.to_datetime(edges_out_2["occurred_at"])
                        if t1 < t2 and (t2 - t1).total_seconds() / 3600 <= time_window_hours:
                            findings.append(PatternFinding(
                                finding_type=PatternType.ROUND_TRIPPING,
                                statement=f"Round tripping detected: Funds sent to {succ} and returned within {(t2-t1).total_seconds()/60:.1f} minutes.",
                                evidence_ids=[edges_out_1["transaction_id"], edges_out_2["transaction_id"]],
                                confidence=0.9
                            ))
                            
                for succ2 in graph.successors(succ):
                    if succ2 == account_id or succ2 == succ: continue
                    if graph.has_edge(succ2, account_id):
                        for k2, edges_out_2 in graph.get_edge_data(succ, succ2).items():
                            t2 = pd.to_datetime(edges_out_2["occurred_at"])
                            if t1 < t2:
                                for k3, edges_out_3 in graph.get_edge_data(succ2, account_id).items():
                                    t3 = pd.to_datetime(edges_out_3["occurred_at"])
                                    if t2 < t3 and (t3 - t1).total_seconds() / 3600 <= time_window_hours:
                                        findings.append(PatternFinding(
                                            finding_type=PatternType.ROUND_TRIPPING,
                                            statement=f"Round tripping detected: Funds routed through {succ} and {succ2} and returned within {(t3-t1).total_seconds()/60:.1f} minutes.",
                                            evidence_ids=[edges_out_1["transaction_id"], edges_out_2["transaction_id"], edges_out_3["transaction_id"]],
                                            confidence=0.9
                                        ))
                                        
    unique_findings = []
    seen_evidence = set()
    for f in findings:
        evidence_tuple = tuple(sorted(f.evidence_ids))
        if evidence_tuple not in seen_evidence:
            seen_evidence.add(evidence_tuple)
            unique_findings.append(f)
            
    return DetectRoundTrippingOutput(findings=unique_findings)
