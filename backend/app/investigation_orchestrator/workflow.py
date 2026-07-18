"""LangGraph construction for the Hybrid Supervisor workflow."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph

from .evidence_validator import evidence_validator_node
from .human_review import human_review_node
from .nodes import (
    kyc_agent_node,
    merge_and_validate_node,
    parallel_dispatch_node,
    planner_node,
    screening_agent_node,
    supervisor_node,
    transaction_agent_node,
)
from .report_agent import report_agent_node
from .state import InvestigationInput, InvestigationState


def build_workflow(checkpointer: Any | None = None):
    """Compile the MVP workflow with an injectable persistence backend."""

    builder = StateGraph(InvestigationState, input_schema=InvestigationInput)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("planner", planner_node)
    builder.add_node("parallel_dispatch", parallel_dispatch_node)
    builder.add_node("transaction_agent", transaction_agent_node)
    builder.add_node("kyc_agent", kyc_agent_node)
    builder.add_node("merge_and_validate", merge_and_validate_node)
    builder.add_node("screening_agent", screening_agent_node)
    builder.add_node("evidence_validator", evidence_validator_node)
    builder.add_node("report_agent", report_agent_node)
    builder.add_node("human_review", human_review_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("parallel_dispatch", "transaction_agent")
    builder.add_edge("parallel_dispatch", "kyc_agent")
    builder.add_edge(["transaction_agent", "kyc_agent"], "merge_and_validate")

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
