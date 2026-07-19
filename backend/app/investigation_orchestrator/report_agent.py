"""State adapter for the structured LLM report agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langgraph.types import Command
from langchain_core.runnables import RunnableConfig

from .agents import invoke_report
from .prompts import report_context
from .state import InvestigationState


def _pipeline_error(state: InvestigationState) -> str | None:
    workflow_error = state.get("workflow_error")
    if workflow_error:
        return workflow_error
    errors = state.get("errors", [])
    return "; ".join(errors) if errors else None


def make_report_node(agent: Any) -> Callable[[InvestigationState], Command]:
    """Build an investigation dossier from validated state only."""

    def report_agent_node(
        state: InvestigationState,
        config: RunnableConfig,
    ) -> Command[Literal["supervisor"]]:
        workflow_error = _pipeline_error(state)
        report = invoke_report(
            agent,
            report_context(state),
            state["case_id"],
            case_file=state.get("case_file", {}),
            validation=state.get("evidence_validation", {}),
            workflow_error=workflow_error,
            config=config,
        )
        return Command(
            update={
                "report": report,
                "handoff_log": [
                    {
                        "source": "report_agent",
                        "target": "supervisor",
                        "reason": "Draft dossier created from validated findings",
                    }
                ],
            },
            goto="supervisor",
        )

    return report_agent_node
