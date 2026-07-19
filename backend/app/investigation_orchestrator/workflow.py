"""LangGraph construction for the Hybrid Supervisor workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import inspect
from typing import Any

from langchain_core.callbacks.manager import CallbackManager
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph

from app.legal_rag.config import LegalRagConfig
from app.legal_rag.hybrid_retriever import HybridLegalRetriever, LegalRetriever
from app.investigation_events import (
    ExecutionEventRecorder,
    InvestigationEventRepository,
    InvestigationEventType,
    ToolEventCallback,
)

from .evidence_validator import evidence_validator_node
from .agents import (
    build_behavior_mapper_agent,
    build_kyc_agent,
    build_planner_agent,
    build_report_agent,
    build_screening_agent,
    build_transaction_agent,
)
from .agent_config import AgentSettingsBundle
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


def _instrument_agent_node(
    agent_id: str,
    node: Callable,
    event_repository: InvestigationEventRepository,
) -> Callable:
    parameters = inspect.signature(node).parameters.values()
    accepts_config = len(inspect.signature(node).parameters) >= 2 or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )

    def instrumented(
        state: InvestigationState, config: RunnableConfig
    ) -> Any:
        recorder = ExecutionEventRecorder.from_state(event_repository, state)
        recorder.append(
            InvestigationEventType.AGENT_STARTED,
            agent_id=agent_id,
            status="RUNNING",
            summary=f"{agent_id} started",
        )
        tool_callback = ToolEventCallback(recorder, agent_id)
        child_config: RunnableConfig = dict(config or {})
        child_config["callbacks"] = CallbackManager.configure(
            inheritable_callbacks=child_config.get("callbacks"),
            local_callbacks=[tool_callback],
        )
        # Reliable tool logging path for create_agent (callbacks often miss tools).
        configurable = dict(child_config.get("configurable") or {})
        configurable["aml_event_recorder"] = recorder
        configurable["aml_agent_id"] = agent_id
        child_config["configurable"] = configurable
        try:
            result = (
                node(state, child_config)
                if accepts_config
                else node(state)
            )
            tool_callback.raise_if_failed()
        except Exception as exc:
            recorder.append(
                InvestigationEventType.AGENT_FAILED,
                agent_id=agent_id,
                status="FAILED",
                summary=f"{agent_id} failed",
                payload={"error_type": type(exc).__name__},
            )
            raise
        update = getattr(result, "update", None)
        output = update if isinstance(update, dict) else result if isinstance(result, dict) else None
        recorder.append(
            InvestigationEventType.AGENT_COMPLETED,
            agent_id=agent_id,
            status="COMPLETED",
            summary=f"{agent_id} completed",
            payload={"output": output} if output is not None else None,
        )
        return result

    return instrumented


def _model_for_agent(
    agent_id: str,
    *,
    shared_model: Any | None,
    agent_settings: AgentSettingsBundle | None,
) -> Any:
    if shared_model is not None:
        return shared_model
    model_id = None
    if agent_settings is not None:
        model_id = agent_settings.for_agent(agent_id).model_id
    return build_chat_model(profile_id=model_id)


def _prompt_for_agent(
    agent_id: str,
    *,
    agent_settings: AgentSettingsBundle | None,
    soft_prompt: str | None,
) -> str | None:
    if agent_settings is not None:
        agent_prompt = agent_settings.for_agent(agent_id).soft_prompt
        if agent_prompt:
            return agent_prompt
    return soft_prompt


def _llm_nodes(
    registry: ToolRegistry,
    *,
    shared_model: Any | None = None,
    agent_settings: AgentSettingsBundle | None = None,
    soft_prompt: str | None = None,
) -> dict[str, Callable]:
    transaction_tools = registry.tools_for("transaction")
    kyc_tools = registry.tools_for("kyc")
    screening_tools = registry.tools_for("screening")
    return {
        "planner": make_planner_node(
            build_planner_agent(
                _model_for_agent(
                    "planner", shared_model=shared_model, agent_settings=agent_settings
                ),
                soft_prompt=_prompt_for_agent(
                    "planner", agent_settings=agent_settings, soft_prompt=soft_prompt
                ),
            )
        ),
        "transaction_agent": make_worker_node(
            "transaction",
            build_transaction_agent(
                _model_for_agent(
                    "transaction",
                    shared_model=shared_model,
                    agent_settings=agent_settings,
                ),
                transaction_tools,
                soft_prompt=_prompt_for_agent(
                    "transaction",
                    agent_settings=agent_settings,
                    soft_prompt=soft_prompt,
                ),
            ),
            transaction_tools,
        ),
        "kyc_agent": make_worker_node(
            "kyc",
            build_kyc_agent(
                _model_for_agent(
                    "kyc", shared_model=shared_model, agent_settings=agent_settings
                ),
                kyc_tools,
                soft_prompt=_prompt_for_agent(
                    "kyc", agent_settings=agent_settings, soft_prompt=soft_prompt
                ),
            ),
            kyc_tools,
        ),
        "screening_agent": make_screening_node(
            build_screening_agent(
                _model_for_agent(
                    "screening",
                    shared_model=shared_model,
                    agent_settings=agent_settings,
                ),
                screening_tools,
                soft_prompt=_prompt_for_agent(
                    "screening",
                    agent_settings=agent_settings,
                    soft_prompt=soft_prompt,
                ),
            ),
            screening_tools,
        ),
        "behavior_mapper": make_behavior_mapper_node(
            build_behavior_mapper_agent(
                _model_for_agent(
                    "behavior_mapper",
                    shared_model=shared_model,
                    agent_settings=agent_settings,
                ),
                soft_prompt=_prompt_for_agent(
                    "behavior_mapper",
                    agent_settings=agent_settings,
                    soft_prompt=soft_prompt,
                ),
            )
        ),
        "report_agent": make_report_node(
            build_report_agent(
                _model_for_agent(
                    "report", shared_model=shared_model, agent_settings=agent_settings
                ),
                soft_prompt=_prompt_for_agent(
                    "report", agent_settings=agent_settings, soft_prompt=soft_prompt
                ),
            )
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
    agent_settings: AgentSettingsBundle | None = None,
    event_repository: InvestigationEventRepository | None = None,
):
    """Compile the workflow with production LLMs or deterministic test nodes."""

    if agent_nodes is None:
        registry = tool_registry or build_production_tool_registry(
            legal_retriever=legal_retriever
        )
        registry.require_tools()
        nodes = _llm_nodes(
            registry,
            shared_model=model,
            agent_settings=agent_settings,
            soft_prompt=soft_prompt,
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

    if event_repository is not None:
        nodes = {
            name: _instrument_agent_node(name, node, event_repository)
            for name, node in nodes.items()
        }

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
