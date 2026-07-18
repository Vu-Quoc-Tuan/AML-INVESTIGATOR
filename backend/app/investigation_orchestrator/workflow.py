"""LangGraph construction for the Hybrid Supervisor workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph

from .evidence_validator import evidence_validator_node
from .human_review import human_review_node
from .agents import (
    build_kyc_agent,
    build_planner_agent,
    build_report_agent,
    build_screening_agent,
    build_transaction_agent,
)
from .model import build_chat_model
from .nodes import (
    make_planner_node,
    make_screening_node,
    make_worker_node,
    merge_and_validate_node,
    parallel_dispatch_node,
    supervisor_node,
)
from .report_agent import make_report_node
from .state import InvestigationInput, InvestigationState
from .tool_registry import ToolRegistry


LLM_NODE_NAMES = {
    "planner",
    "transaction_agent",
    "kyc_agent",
    "screening_agent",
    "report_agent",
}


def _llm_nodes(model: Any, registry: ToolRegistry) -> dict[str, Callable]:
    transaction_tools = registry.tools_for("transaction")
    kyc_tools = registry.tools_for("kyc")
    screening_tools = registry.tools_for("screening")
    return {
        "planner": make_planner_node(build_planner_agent(model)),
        "transaction_agent": make_worker_node(
            "transaction",
            build_transaction_agent(model, transaction_tools),
            transaction_tools,
        ),
        "kyc_agent": make_worker_node(
            "kyc", build_kyc_agent(model, kyc_tools), kyc_tools
        ),
        "screening_agent": make_screening_node(
            build_screening_agent(model, screening_tools), screening_tools
        ),
        "report_agent": make_report_node(build_report_agent(model)),
    }


def build_workflow(
    checkpointer: Any | None = None,
    *,
    model: Any | None = None,
    tool_registry: ToolRegistry | None = None,
    agent_nodes: Mapping[str, Callable] | None = None,
):
    """Compile the workflow with production LLMs or deterministic test nodes."""

    if agent_nodes is None:
        nodes = _llm_nodes(model or build_chat_model(), tool_registry or ToolRegistry())
    else:
        missing = LLM_NODE_NAMES - agent_nodes.keys()
        extra = agent_nodes.keys() - LLM_NODE_NAMES
        if missing or extra:
            raise ValueError(
                f"agent_nodes must contain exactly {sorted(LLM_NODE_NAMES)}; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        nodes = dict(agent_nodes)

    builder = StateGraph(InvestigationState, input_schema=InvestigationInput)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("planner", nodes["planner"])
    builder.add_node("parallel_dispatch", parallel_dispatch_node)
    builder.add_node("transaction_agent", nodes["transaction_agent"])
    builder.add_node("kyc_agent", nodes["kyc_agent"])
    builder.add_node("merge_and_validate", merge_and_validate_node)
    builder.add_node("screening_agent", nodes["screening_agent"])
    builder.add_node("evidence_validator", evidence_validator_node)
    builder.add_node("report_agent", nodes["report_agent"])
    builder.add_node("human_review", human_review_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("parallel_dispatch", "transaction_agent")
    builder.add_edge("parallel_dispatch", "kyc_agent")
    builder.add_edge(["transaction_agent", "kyc_agent"], "merge_and_validate")

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver()
    )
