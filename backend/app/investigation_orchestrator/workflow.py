"""LangGraph construction for the Hybrid Supervisor workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph

from app.legal_rag.config import LegalRagConfig
from app.legal_rag.hybrid_retriever import HybridLegalRetriever, LegalRetriever

from .evidence_validator import evidence_validator_node
from .agents import (
    build_behavior_mapper_agent,
    build_kyc_agent,
    build_planner_agent,
    build_report_agent,
    build_screening_agent,
    build_transaction_agent,
)
from .model import build_chat_model
from .nodes import (
    make_behavior_mapper_node,
    make_legal_rag_node,
    make_planner_node,
    make_screening_node,
    make_worker_node,
    merge_and_validate_node,
    parallel_dispatch_node,
    supervisor_node,
)
from .report_agent import make_report_node
from .production_tools import build_production_tool_registry
from .state import InvestigationInput, InvestigationState
from .tool_registry import ToolRegistry


LLM_NODE_NAMES = {
    "planner",
    "transaction_agent",
    "kyc_agent",
    "screening_agent",
    "behavior_mapper",
    "report_agent",
}


def _llm_nodes(
    model: Any, registry: ToolRegistry, soft_prompt: str | None = None
) -> dict[str, Callable]:
    transaction_tools = registry.tools_for("transaction")
    kyc_tools = registry.tools_for("kyc")
    screening_tools = registry.tools_for("screening")
    return {
        "planner": make_planner_node(
            build_planner_agent(model, soft_prompt=soft_prompt)
        ),
        "transaction_agent": make_worker_node(
            "transaction",
            build_transaction_agent(
                model, transaction_tools, soft_prompt=soft_prompt
            ),
            transaction_tools,
        ),
        "kyc_agent": make_worker_node(
            "kyc",
            build_kyc_agent(model, kyc_tools, soft_prompt=soft_prompt),
            kyc_tools,
        ),
        "screening_agent": make_screening_node(
            build_screening_agent(
                model, screening_tools, soft_prompt=soft_prompt
            ),
            screening_tools,
        ),
        "behavior_mapper": make_behavior_mapper_node(
            build_behavior_mapper_agent(model, soft_prompt=soft_prompt)
        ),
        "report_agent": make_report_node(
            build_report_agent(model, soft_prompt=soft_prompt)
        ),
    }


def build_workflow(
    checkpointer: Any | None = None,
    *,
    model: Any | None = None,
    tool_registry: ToolRegistry | None = None,
    agent_nodes: Mapping[str, Callable] | None = None,
    legal_retriever: LegalRetriever | None = None,
    soft_prompt: str | None = None,
):
    """Compile the workflow with production LLMs or deterministic test nodes."""

    if agent_nodes is None:
        registry = tool_registry or build_production_tool_registry(
            legal_retriever=legal_retriever
        )
        registry.require_tools()
        resolved_model = model or build_chat_model()
        nodes = (
            _llm_nodes(resolved_model, registry)
            if soft_prompt is None
            else _llm_nodes(resolved_model, registry, soft_prompt)
        )
    else:
        missing = LLM_NODE_NAMES - agent_nodes.keys()
        extra = agent_nodes.keys() - LLM_NODE_NAMES
        if missing or extra:
            raise ValueError(
                f"agent_nodes must contain exactly {sorted(LLM_NODE_NAMES)}; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        nodes = dict(agent_nodes)

    retriever = legal_retriever or HybridLegalRetriever(LegalRagConfig.from_env())

    builder = StateGraph(InvestigationState, input_schema=InvestigationInput)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("planner", nodes["planner"])
    builder.add_node("parallel_dispatch", parallel_dispatch_node)
    builder.add_node("transaction_agent", nodes["transaction_agent"])
    builder.add_node("kyc_agent", nodes["kyc_agent"])
    builder.add_node("merge_and_validate", merge_and_validate_node)
    builder.add_node("screening_agent", nodes["screening_agent"])
    builder.add_node("behavior_mapper", nodes["behavior_mapper"])
    builder.add_node("legal_rag", make_legal_rag_node(retriever))
    builder.add_node("evidence_validator", evidence_validator_node)
    builder.add_node("report_agent", nodes["report_agent"])

    builder.add_edge(START, "supervisor")
    builder.add_edge("parallel_dispatch", "transaction_agent")
    builder.add_edge("parallel_dispatch", "kyc_agent")
    builder.add_edge(["transaction_agent", "kyc_agent"], "merge_and_validate")

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver()
    )
