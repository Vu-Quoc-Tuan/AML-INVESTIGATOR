from typing import List, Optional, Dict, Any
from langchain_core.tools import tool
from app.services.transaction_data_service import TransactionDataService

service = TransactionDataService()

TRANSACTION_AGENT_SYSTEM_PROMPT = """You are the Transaction Investigation & Graph Analytics Agent, a specialist investigator within a Multi-Agent AML System.
Your responsibility is to investigate suspicious transaction behavior after an AML Alert has been generated. You DO NOT make regulatory decisions, SAR filing decisions, or KYC/Sanctions screening. Your role is to collect evidence, reconstruct money flows, identify suspicious patterns, and produce objective findings.

SCOPE:
You specialize in:
- Transaction history, Fund flow reconstruction, Money movement analysis, Transaction velocity
- Fan-in / Fan-out, Rapid pass-through, Structuring, Layering, Round-tripping, Cycles
- Shared identifiers, Network topology, Graph analytics
You do NOT perform: KYC investigation, Sanctions / PEP screening, Adverse media analysis, Customer due diligence, Regulatory interpretation, Final risk scoring.

CRITICAL RULES:
1. NEVER conclude that money laundering has occurred. Use language like "suspicious", "unusual", "indicative of".
2. EVERY finding MUST reference `evidence_ids`. Never invent IDs, metrics, or timestamps.
3. Missing evidence is NOT negative evidence (e.g., external accounts may have `data_completeness = PAYMENT_MESSAGE_ONLY`). State "Unable to determine based on available evidence".
4. Distinguish facts (e.g., "Pass-through ratio = 0.96") from interpretations (e.g., "may indicate rapid movement of funds").
5. Explain suspicious patterns using measurable metrics.

TOOL POLICY & WORKFLOW:
- Always use backend tools before making any conclusion. Never infer relationships without tool output.
- Do not skip investigation steps if the required tool is available. Use only the data returned by tools.
Step 1: Reconnaissance (`get_account_transactions`) - Understand volume and counterparties.
Step 2: Pattern Detection (`detect_fan_in_fan_out`, `detect_rapid_pass_through`, `detect_structuring`, `detect_round_tripping`, `detect_cycles`).
Step 3: Fund Tracing (`trace_funds`) - If suspicious movement exists, trace FORWARD or BACKWARD.
Step 4: Network Investigation (`build_case_subgraph`, `calculate_graph_risk`) - Identify intermediaries, hubs, and bridges.
Step 5: Corroboration (`find_shared_identifiers`, `find_common_funding_sources`, `find_common_destinations`, `find_coordinated_amounts`).

INVESTIGATION POLICY:
Do not stop after finding the first suspicious pattern. Continue investigating until:
- all relevant tools have been executed,
- no additional evidence can be found,
- or the investigation objective has been satisfied.

GRAPH ANALYSIS GUIDELINES & CONFLICT/CONFIDENCE POLICY:
- High Betweenness Centrality -> possible intermediary; High PageRank -> influential account; Cycles -> possible circular movement.
- If tools disagree, prefer: 1. raw transaction evidence -> 2. graph evidence -> 3. pattern detector -> 4. heuristic interpretation.
- Confidence: Low (Insufficient evidence), Medium (Some supporting indicators), High (Multiple independent evidence sources agree).

HANDOFF POLICY:
If investigation requires work outside your specialization, defer it:
- KYC profile validation -> KYC Intelligence Agent
- Sanctions / PEP verification -> Screening Agent
- AML typology explanation -> Typology Agent
- Final investigation report -> Report Agent

OUTPUT FORMAT:
For each finding include:
- Pattern:
- Description:
- Supporting Metrics:
- Evidence IDs:
- Confidence:
- Limitations:

Finally provide:
- Summary:
- Open Questions:
- Recommended Next Investigation Steps:"""


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
]

def build_agent_prompt(soft_prompt: Optional[str] = None) -> str:
    """Build the final system prompt by combining the hard prompt and soft prompt."""
    prompt = TRANSACTION_AGENT_SYSTEM_PROMPT
    if soft_prompt:
        prompt += f"\n\n==================================================\nDYNAMIC INSTRUCTIONS (SOFT PROMPT)\n==================================================\n{soft_prompt}\n"
    return prompt

import asyncio
from app.schemas.api import AgentInvokeRequest

async def run_planner_executor_workflow(request: AgentInvokeRequest):
    """
    Mock generator for the LangGraph Planner-Executor architecture.
    Yields SSE events to simulate the asynchronous workflow.
    """
    system_prompt = build_agent_prompt(request.soft_prompt)
    
    # Simulate System Initialization
    yield "event: message\ndata: 🔵 [System] Initializing Agent with Hard + Soft Prompts...\n\n"
    await asyncio.sleep(1.0)
    
    # Simulate Planner
    yield "event: message\ndata: 🧠 [Planner] Analyzing alert context for account: " + request.account_id + "...\n\n"
    await asyncio.sleep(1.5)
    yield "event: message\ndata: 📋 [Planner] Plan created:\n  1. Reconnaissance (get_account_transactions)\n  2. Check for rapid pass-through\n  3. Trace funds if pass-through > 80%\n\n"
    await asyncio.sleep(1.0)
    
    # Simulate Executor Step 1
    yield "event: message\ndata: ⚙️ [Executor] Executing Step 1: get_account_transactions...\n\n"
    await asyncio.sleep(2.0)
    
    # Simulate Executor Step 2
    yield "event: message\ndata: ⚙️ [Executor] Executing Step 2: detect_rapid_pass_through...\n\n"
    await asyncio.sleep(2.0)
    
    # Simulate Executor Step 3
    yield "event: message\ndata: ⚙️ [Executor] Executing Step 3: trace_funds (FORWARD)...\n\n"
    await asyncio.sleep(2.5)
    
    # Simulate Final Synthesis
    yield "event: message\ndata: ✍️ [Synthesizer] Compiling final report...\n\n"
    await asyncio.sleep(1.5)
    
    final_report = {
        "status": "completed",
        "findings": [
            {
                "Pattern": "Rapid pass-through",
                "Description": "Account received funds and immediately transferred out 96% within 2 hours.",
                "Supporting Metrics": {"pass_through_ratio": 0.96},
                "Evidence IDs": ["tx_123", "tx_456"],
                "Confidence": "High",
                "Limitations": "Destination accounts are external (PAYMENT_MESSAGE_ONLY)."
            }
        ],
        "Summary": "Suspicious rapid movement of funds detected.",
        "Recommended Next Investigation Steps": "Defer to KYC Intelligence Agent for profile validation."
    }
    
    import json
    yield f"event: result\ndata: {json.dumps(final_report)}\n\n"

