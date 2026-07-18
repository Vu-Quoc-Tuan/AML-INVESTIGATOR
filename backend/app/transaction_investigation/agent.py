from typing import List, Optional, Dict, Any
from langchain_core.tools import tool
from app.services.transaction_data_service import TransactionDataService

service = TransactionDataService()

TRANSACTION_AGENT_SYSTEM_PROMPT = """You are the Transaction Investigation & Graph Analytics Agent, a specialized AI investigator in a broader AML (Anti-Money Laundering) system.

Your primary role is to investigate AML alerts by analyzing transaction data, tracing fund flows, detecting suspicious money movement patterns, and analyzing relationship graphs.

CRITICAL RULES YOU MUST FOLLOW:
1. DO NOT make final legal or compliance determinations (e.g., "This is definitely money laundering"). You only identify *suspicious patterns* and gather *evidence*.
2. EVERY finding you report MUST be backed by `evidence_ids` returned by your tools. Do not invent or hallucinate transaction IDs.
3. You cannot query the database directly. You must use the provided tools to fetch data.
4. If a tool returns no data or an error, state clearly that the evidence is inconclusive rather than guessing.
5. Base your analysis strictly on the tool outputs. Pay attention to confidence scores and metrics like Betweenness Centrality or Pass-through ratios.

When analyzing an account, follow this general workflow:
- Step 1: Reconnaissance. Use `get_account_transactions` to get a high-level view of inbound/outbound volume and top counterparties.
- Step 2: Pattern Sweeping. Run tools like `detect_fan_in_fan_out`, `detect_rapid_pass_through`, and `detect_structuring` to find hard evidence of suspicious behavior.
- Step 3: Network Tracing. If you find rapid pass-through or fan-in, use `trace_funds` to see where the money originated (BACKWARD) or where it went (FORWARD) up to 3 hops.
- Step 4: Graph Analysis. Build a subgraph with `build_case_subgraph` and evaluate risk metrics with `calculate_graph_risk` to find key intermediaries.
- Step 5: Corroborate. Use `find_shared_identifiers` or `find_coordinated_amounts` to prove coordination between seemingly unrelated accounts.

Provide your final analysis in a clear, structured report citing specific transaction IDs and metrics."""


@tool
def get_account_transactions(account_id: str, start_time: Optional[str] = None, end_time: Optional[str] = None, direction: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve all transactions for a specific account, including counterparty summaries and total flows. Useful for initial reconnaissance."""
    return service.get_account_transactions(account_id, start_time, end_time, direction)


@tool
def trace_funds(seed_account_ids: List[str], direction: str, max_depth: int = 3, start_time: Optional[str] = None, end_time: Optional[str] = None) -> Dict[str, Any]:
    """Trace fund flows across the network. 
    direction must be 'FORWARD' (trace where money went) or 'BACKWARD' (trace where money came from).
    Returns paths, visited accounts, and a graph snapshot."""
    return service.trace_funds(seed_account_ids, direction, max_depth, start_time, end_time)


@tool
def detect_fan_in_fan_out(account_id: str, time_window_hours: float = 24.0) -> Dict[str, Any]:
    """Detect 'Fan-in' (funds aggregating from many sources) or 'Fan-out' (funds dispersing to many destinations) patterns. Returns evidence IDs and confidence."""
    return service.detect_fan_in_fan_out(account_id, time_window_hours)


@tool
def detect_rapid_pass_through(account_id: str, time_window_hours: float = 24.0) -> Dict[str, Any]:
    """Detect if an account acts as a pass-through (receives funds and immediately sends a high percentage out). Typical of mule accounts."""
    return service.detect_rapid_pass_through(account_id, time_window_hours)


@tool
def detect_structuring(account_id: str, time_window_hours: float = 24.0) -> Dict[str, Any]:
    """Detect structuring (smurfing) attempts where multiple transactions are made just below the reporting threshold."""
    return service.detect_structuring(account_id, time_window_hours)


@tool
def detect_cycles(seed_account_id: str, max_depth: int = 5) -> Dict[str, Any]:
    """Detect circular money flows (cycles) originating from or involving the seed account, indicating potential layering."""
    return service.detect_cycles(seed_account_id, max_depth)


@tool
def find_common_funding_sources(account_ids: List[str], lookback_period_hours: float = 24.0) -> Dict[str, Any]:
    """Check if a group of seemingly unrelated accounts share a common funding source."""
    return service.find_common_funding_sources(account_ids, lookback_period_hours)


@tool
def find_common_destinations(account_ids: List[str], lookforward_period_hours: float = 24.0) -> Dict[str, Any]:
    """Check if a group of seemingly unrelated accounts are sending money to a common destination."""
    return service.find_common_destinations(account_ids, lookforward_period_hours)


@tool
def find_shared_identifiers(account_ids: List[str]) -> Dict[str, Any]:
    """Find if a group of accounts are sharing the same IP address or Device ID when making transactions, indicating coordination."""
    return service.find_shared_identifiers(account_ids)


@tool
def find_coordinated_amounts(account_id: str, time_window_hours: float = 24.0) -> Dict[str, Any]:
    """Find transactions with identical or highly coordinated amounts, which is highly suspicious."""
    return service.find_coordinated_amounts(account_id, time_window_hours)


@tool
def detect_round_tripping(account_id: str, time_window_hours: float = 24.0) -> Dict[str, Any]:
    """Detect round-tripping where funds are sent out to the network and loop back to the same account shortly after."""
    return service.detect_round_tripping(account_id, time_window_hours)


@tool
def build_case_subgraph(seed_entity_ids: List[str], max_depth: int = 2) -> Dict[str, Any]:
    """Extract a local network subgraph around the seed entities to visualize relationships and run graph metrics."""
    return service.build_case_subgraph(seed_entity_ids, max_depth)


@tool
def calculate_graph_risk(graph_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate network science metrics (Betweenness Centrality, PageRank) on a graph snapshot to identify key intermediaries and risk scores."""
    return service.calculate_graph_risk(graph_snapshot)


# List of all tools available to the LangGraph/LangChain Agent
TRANSACTION_AGENT_TOOLS = [
    get_account_transactions,
    trace_funds,
    detect_fan_in_fan_out,
    detect_rapid_pass_through,
    detect_structuring,
    detect_cycles,
    find_common_funding_sources,
    find_common_destinations,
    find_shared_identifiers,
    find_coordinated_amounts,
    detect_round_tripping,
    build_case_subgraph,
    calculate_graph_risk
]
