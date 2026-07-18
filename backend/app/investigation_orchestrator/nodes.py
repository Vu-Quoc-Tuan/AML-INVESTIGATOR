"""Deterministic orchestration nodes and LLM node adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

from langchain_core.tools import BaseTool

from langgraph.graph import END
from langgraph.types import Command

from .agents import invoke_planner, invoke_worker
from .prompts import planner_context, screening_context, worker_context
from .state import AgentOutput, HandoffRecord, InvestigationState


SupervisorDestination = Literal[
    "planner",
    "parallel_dispatch",
    "screening_agent",
    "evidence_validator",
    "report_agent",
    "human_review",
    "__end__",
]


def _handoff(source: str, target: str, reason: str) -> HandoffRecord:
    return {"source": source, "target": target, "reason": reason}


def supervisor_node(
    state: InvestigationState,
) -> Command[SupervisorDestination]:
    """Apply mandatory routing rules and hand control to the next stage."""

    review = state.get("human_review")
    if review:
        decision = review["decision"]
        status = {
            "APPROVED": "APPROVED",
            "REJECTED": "REJECTED",
            "MORE_INFORMATION_REQUIRED": "AWAITING_INFORMATION",
        }[decision]
        return Command(
            update={
                "phase": "complete",
                "case_status": status,
                "handoff_log": [
                    _handoff("supervisor", "end", f"Human decision: {decision}")
                ],
            },
            goto=END,
        )

    if state.get("workflow_error"):
        if state.get("case_file") and not state.get("evidence_validation"):
            target = "evidence_validator"
            phase = "evidence_validation"
        elif not state.get("report"):
            target = "report_agent"
            phase = "reporting"
        else:
            target = "human_review"
            phase = "human_review"
        return Command(
            update={
                "phase": phase,
                "case_status": "IN_REVIEW",
                "handoff_log": [
                    _handoff(
                        "supervisor",
                        target,
                        "Workflow failure requires validated evidence and human review",
                    )
                ],
            },
            goto=target,
        )

    if not state.get("investigation_plan"):
        target = "planner"
        phase = "planning"
        reason = "Create the investigation plan"
    elif not state.get("case_file"):
        target = "parallel_dispatch"
        phase = "parallel_investigation"
        reason = "Collect Transaction and KYC evidence"
    elif "screening" not in state.get("agent_outputs", {}):
        target = "screening_agent"
        phase = "screening"
        reason = "Run screening after investigation evidence is merged"
    elif not state.get("evidence_validation"):
        target = "evidence_validator"
        phase = "evidence_validation"
        reason = "Apply deterministic evidence rules"
    elif not state.get("report"):
        target = "report_agent"
        phase = "reporting"
        reason = "Draft the evidence-backed dossier"
    else:
        target = "human_review"
        phase = "human_review"
        reason = "A human must make the final decision"

    return Command(
        update={
            "phase": phase,
            "case_status": "IN_REVIEW" if target == "human_review" else "OPEN",
            "handoff_log": [_handoff("supervisor", target, reason)],
        },
        goto=target,
    )


def make_planner_node(agent: Any) -> Callable[[InvestigationState], Command]:
    """Adapt the structured planner agent to the shared workflow state."""

    def planner_node(state: InvestigationState) -> Command[Literal["supervisor"]]:
        plan, error_type = invoke_planner(agent, planner_context(state))
        update: dict[str, Any] = {
            "investigation_plan": plan,
            "handoff_log": [
                _handoff("planner", "supervisor", "Investigation plan created")
            ],
        }
        if error_type:
            update["errors"] = [f"Planner fallback used: {error_type}"]
        return Command(update=update, goto="supervisor")

    return planner_node


def parallel_dispatch_node(state: InvestigationState) -> dict[str, str]:
    """Mark the start of the fixed Transaction/KYC fork."""

    return {"phase": "parallel_investigation"}


def make_worker_node(
    owner: Literal["transaction", "kyc"],
    agent: Any | None,
    tools: Sequence[BaseTool],
) -> Callable[[InvestigationState], dict[str, object]]:
    """Adapt one parallel LLM worker without allowing direct state mutation."""

    def worker_node(state: InvestigationState) -> dict[str, object]:
        output = invoke_worker(owner, agent, tools, worker_context(state))
        return {"agent_outputs": {owner: output}}

    return worker_node


def merge_and_validate_node(
    state: InvestigationState,
) -> Command[Literal["supervisor", "report_agent"]]:
    """Commit complete parallel output to the Orchestrator-owned case file."""

    outputs = state.get("agent_outputs", {})
    missing = [name for name in ("transaction", "kyc") if name not in outputs]
    if missing:
        message = f"Missing mandatory parallel outputs: {', '.join(missing)}"
        return Command(
            update={
                "phase": "reporting",
                "case_status": "IN_REVIEW",
                "workflow_error": message,
                "case_file": {
                    "case_id": state["case_id"],
                    "alert": state.get("alert", {}),
                    "findings": [],
                    "evidence": [],
                },
                "evidence_validation": {
                    "status": "FAILED",
                    "valid_finding_count": 0,
                    "invalid_finding_count": 0,
                    "issues": [message],
                },
                "errors": [message],
                "handoff_log": [
                    _handoff("merge_and_validate", "report_agent", message)
                ],
            },
            goto="report_agent",
        )

    failed = [
        name for name in ("transaction", "kyc") if outputs[name].get("status") == "ERROR"
    ]
    if failed:
        message = f"Mandatory agents failed: {', '.join(failed)}"
        return Command(
            update={
                "phase": "reporting",
                "case_status": "IN_REVIEW",
                "workflow_error": message,
                "case_file": {
                    "case_id": state["case_id"],
                    "alert": state.get("alert", {}),
                    "findings": [],
                    "evidence": [],
                },
                "evidence_validation": {
                    "status": "FAILED",
                    "valid_finding_count": 0,
                    "invalid_finding_count": 0,
                    "issues": [message],
                },
                "errors": [message],
                "handoff_log": [
                    _handoff("merge_and_validate", "report_agent", message)
                ],
            },
            goto="report_agent",
        )

    findings = [
        finding
        for name in ("transaction", "kyc")
        for finding in outputs[name].get("findings", [])
    ]
    evidence = [
        item
        for name in ("transaction", "kyc")
        for item in outputs[name].get("evidence", [])
    ]
    case_file = {
        "case_id": state["case_id"],
        "alert": state.get("alert", {}),
        "findings": findings,
        "evidence": evidence,
    }
    return Command(
        update={
            "case_file": case_file,
            "phase": "merged",
            "handoff_log": [
                _handoff(
                    "merge_and_validate",
                    "supervisor",
                    "Parallel outputs committed to Shared Case File",
                )
            ],
        },
        goto="supervisor",
    )


def make_screening_node(
    agent: Any | None, tools: Sequence[BaseTool]
) -> Callable[[InvestigationState], Command]:
    """Adapt screening output and route provider failures to a reviewable dossier."""

    def screening_agent_node(
        state: InvestigationState,
    ) -> Command[Literal["supervisor"]]:
        output = invoke_worker("screening", agent, tools, screening_context(state))
        update: dict[str, Any] = {
            "agent_outputs": {"screening": output},
            "handoff_log": [
                _handoff("screening_agent", "supervisor", "Screening completed")
            ],
        }
        if output.get("status") == "ERROR":
            update["workflow_error"] = "Screening agent failed"
            update["errors"] = ["Screening agent failed"]
        return Command(update=update, goto="supervisor")

    return screening_agent_node
