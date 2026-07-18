"""LLM agent construction and deterministic output boundary checks."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from .agent_schemas import (
    MANDATORY_STAGES,
    InvestigationPlanResponse,
    InvestigationReportResponse,
    PlanStep,
    ScreeningAnalysisResponse,
    WorkerAnalysisResponse,
)
from .prompts import (
    KYC_AGENT_PROMPT,
    PLANNER_PROMPT,
    REPORT_AGENT_PROMPT,
    SCREENING_AGENT_PROMPT,
    TRANSACTION_AGENT_PROMPT,
)
from .state import AgentOutput
from .tool_registry import AgentName, ToolResult


def build_planner_agent(model: Any) -> Any:
    return create_agent(
        model=model,
        tools=[],
        system_prompt=PLANNER_PROMPT,
        response_format=ToolStrategy(InvestigationPlanResponse),
    )


def _build_worker_agent(
    model: Any,
    tools: Sequence[BaseTool],
    *,
    prompt: str,
    response_schema: type[WorkerAnalysisResponse] = WorkerAnalysisResponse,
) -> Any | None:
    if not tools:
        return None
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=prompt,
        response_format=ToolStrategy(response_schema),
    )


def build_transaction_agent(model: Any, tools: Sequence[BaseTool]) -> Any | None:
    return _build_worker_agent(model, tools, prompt=TRANSACTION_AGENT_PROMPT)


def build_kyc_agent(model: Any, tools: Sequence[BaseTool]) -> Any | None:
    return _build_worker_agent(model, tools, prompt=KYC_AGENT_PROMPT)


def build_screening_agent(model: Any, tools: Sequence[BaseTool]) -> Any | None:
    return _build_worker_agent(
        model,
        tools,
        prompt=SCREENING_AGENT_PROMPT,
        response_schema=ScreeningAnalysisResponse,
    )


def build_report_agent(model: Any) -> Any:
    return create_agent(
        model=model,
        tools=[],
        system_prompt=REPORT_AGENT_PROMPT,
        response_format=ToolStrategy(InvestigationReportResponse),
    )


def _structured_response(result: dict[str, Any], schema: type[Any]) -> Any:
    return schema.model_validate(result.get("structured_response"))


def invoke_planner(agent: Any, context: str) -> tuple[dict[str, Any], str | None]:
    """Return a valid plan; preserve a redacted error code on provider failure."""

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            config={"recursion_limit": 8},
        )
        plan = _structured_response(result, InvestigationPlanResponse)
        return plan.model_dump(), None
    except Exception as exc:
        fallback = InvestigationPlanResponse(
            case_summary="Mandatory investigation plan generated after planner failure",
            steps=[
                PlanStep(stage=stage, objective=f"Complete {stage}", rationale="Mandatory")
                for stage in MANDATORY_STAGES
            ],
        )
        return fallback.model_dump(), type(exc).__name__


def _decode_tool_message(message: ToolMessage) -> Any:
    if message.artifact is not None:
        return message.artifact
    content = message.content
    if isinstance(content, str):
        return json.loads(content)
    if isinstance(content, list) and len(content) == 1:
        item = content[0]
        return item.get("text") if isinstance(item, dict) and "text" in item else item
    return content


def collect_tool_results(
    messages: Sequence[Any], tool_names: set[str]
) -> tuple[list[ToolResult], list[str]]:
    """Validate registered tool messages and ignore structured-output tool calls."""

    results: list[ToolResult] = []
    warnings: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name not in tool_names:
            continue
        if message.status == "error":
            warnings.append(f"Tool {message.name} failed")
            continue
        try:
            results.append(ToolResult.model_validate(_decode_tool_message(message)))
        except (TypeError, ValueError, json.JSONDecodeError):
            warnings.append(f"Tool {message.name} returned an invalid result contract")
    return results, warnings


def _assemble_worker_output(
    owner: AgentName,
    analysis: WorkerAnalysisResponse,
    tool_results: Sequence[ToolResult],
    boundary_warnings: Sequence[str] = (),
) -> AgentOutput:
    evidence_by_id: dict[str, dict[str, Any]] = {}
    evidence_scope_by_id: dict[str, str] = {}
    rejected_evidence_ids: set[str] = set()
    warnings = [*analysis.warnings, *boundary_warnings]
    for result in tool_results:
        warnings.extend(result.warnings)
        if result.status != "SUCCESS":
            continue
        for item in result.evidence:
            if item.evidence_id in rejected_evidence_ids:
                continue
            serialized = item.model_dump(mode="json", exclude_none=True)
            current = evidence_by_id.get(item.evidence_id)
            if current is not None:
                evidence_by_id.pop(item.evidence_id)
                rejected_evidence_ids.add(item.evidence_id)
                warnings.append(f"Duplicate evidence rejected: {item.evidence_id}")
                continue
            evidence_by_id[item.evidence_id] = serialized
            if isinstance(result.data, dict) and isinstance(
                result.data.get("entity_scope"), str
            ):
                evidence_scope_by_id[item.evidence_id] = result.data["entity_scope"]

    findings: list[dict[str, Any]] = []
    for finding in analysis.findings:
        missing = set(finding.evidence_ids) - evidence_by_id.keys()
        if missing:
            warnings.append(
                f"Finding {finding.finding_id} rejected: evidence not returned by tools"
            )
            continue
        if owner == "kyc":
            scopes_verified_internal = all(
                evidence_scope_by_id.get(evidence_id) == "SHB_INTERNAL"
                for evidence_id in finding.evidence_ids
            )
            if finding.entity_scope != "SHB_INTERNAL" or not scopes_verified_internal:
                warnings.append(
                    f"Finding {finding.finding_id} rejected: KYC scope is not verified internal"
                )
                continue
        if owner == "transaction":
            evidence_visibility = {
                evidence_by_id[evidence_id].get("visibility_level")
                for evidence_id in finding.evidence_ids
            }
            if (
                not finding.visibility_level
                or evidence_visibility != {finding.visibility_level}
            ):
                warnings.append(
                    f"Finding {finding.finding_id} rejected: visibility does not match evidence"
                )
                continue
        findings.append(finding.model_dump(exclude_none=True))

    has_success = any(result.status == "SUCCESS" for result in tool_results)
    status = analysis.status if has_success else "INCONCLUSIVE"
    if status != "COMPLETED":
        findings = []
    output: AgentOutput = {
        "agent": f"{owner}_agent",
        "status": status,
        "available": has_success,
        "findings": findings,
        "evidence": list(evidence_by_id.values()),
        "metadata": {**analysis.metadata, "warnings": warnings},
    }
    return output


def invoke_worker(
    owner: AgentName,
    agent: Any | None,
    tools: Sequence[BaseTool],
    context: str,
) -> AgentOutput:
    """Invoke a worker and admit evidence only through registered tool messages."""

    if agent is None or not tools:
        return {
            "agent": f"{owner}_agent",
            "status": "INCONCLUSIVE",
            "available": False,
            "findings": [],
            "evidence": [],
            "metadata": {"warnings": ["No registered tools available"]},
        }
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            config={"recursion_limit": 8},
        )
        schema = ScreeningAnalysisResponse if owner == "screening" else WorkerAnalysisResponse
        analysis = _structured_response(result, schema)
        tool_results, warnings = collect_tool_results(
            result.get("messages", []), {tool.name for tool in tools}
        )
        output = _assemble_worker_output(owner, analysis, tool_results, warnings)
        if owner == "screening":
            output = _finalize_screening_output(
                output,
                ScreeningAnalysisResponse.model_validate(analysis),
                tool_results,
            )
        return output
    except Exception as exc:
        return {
            "agent": f"{owner}_agent",
            "status": "ERROR",
            "available": False,
            "findings": [],
            "evidence": [],
            "metadata": {"error_type": type(exc).__name__},
        }


def _finalize_screening_output(
    output: AgentOutput,
    screening: ScreeningAnalysisResponse,
    tool_results: Sequence[ToolResult],
) -> AgentOutput:
    """Enforce source availability and conservative screening classification."""

    if screening.status == "ERROR":
        output["available"] = False
        output["status"] = "ERROR"
        output["findings"] = []
        return output

    source_unavailable = any(
        isinstance(result.data, dict) and result.data.get("available") is False
        for result in tool_results
    )
    available = (
        screening.status == "COMPLETED"
        and screening.available
        and output.get("available", False)
        and not source_unavailable
    )
    status = screening.screening_status if available else "INCONCLUSIVE"
    referenced_evidence_ids = {
        evidence_id
        for finding in output.get("findings", [])
        for evidence_id in finding.get("evidence_ids", [])
    }
    external_name_evidence_ids = {
        item.evidence_id
        for result in tool_results
        if result.status == "SUCCESS"
        and isinstance(result.data, dict)
        and result.data.get("entity_scope") == "EXTERNAL"
        and result.data.get("match_basis") == "NAME"
        for item in result.evidence
    }
    external_name_only = any(
        finding.get("entity_scope") == "EXTERNAL"
        and finding.get("match_basis") == "NAME"
        for finding in output.get("findings", [])
    ) or bool(referenced_evidence_ids & external_name_evidence_ids)
    if status == "CONFIRMED_MATCH":
        strong_match_evidence_ids = {
            item.evidence_id
            for result in tool_results
            if result.status == "SUCCESS"
            and isinstance(result.data, dict)
            and isinstance(result.data.get("entity_scope"), str)
            and result.data.get("match_basis") in {"IDENTIFIER", "MULTI_ATTRIBUTE"}
            for item in result.evidence
        }
        confirmed_supported = (
            bool(output.get("findings"))
            and bool(output.get("evidence"))
            and bool(referenced_evidence_ids & strong_match_evidence_ids)
            and not external_name_only
        )
        if not confirmed_supported:
            status = "POTENTIAL_MATCH" if output.get("evidence") else "INCONCLUSIVE"
            output.setdefault("metadata", {}).setdefault("warnings", []).append(
                "Unsupported CONFIRMED_MATCH downgraded by screening boundary"
            )
    output["available"] = available
    output["status"] = status
    if status == "INCONCLUSIVE":
        output["findings"] = []
    return output


def invoke_report(
    agent: Any,
    context: str,
    case_id: str,
    *,
    case_file: dict[str, Any],
    validation: dict[str, Any],
    workflow_error: str | None,
) -> dict[str, Any]:
    """Return a safe human-review dossier even if the provider call fails."""

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            config={"recursion_limit": 8},
        )
        report = _structured_response(result, InvestigationReportResponse)
        if report.case_id != case_id:
            raise ValueError("Report case_id does not match workflow case_id")
        safe_report = report.model_dump()
        generation_error = None
    except Exception as exc:
        combined_error = f"Report generation failed: {type(exc).__name__}"
        if workflow_error:
            combined_error = f"{workflow_error}; {combined_error}"
        generation_error = combined_error
        safe_report = InvestigationReportResponse(
            case_id=case_id,
            title="AML Investigation Dossier — generation incomplete",
            summary="The automated draft could not be completed. Review the case data manually.",
            evidence_count=len(case_file.get("evidence", [])),
            validation=validation or {"status": "INCONCLUSIVE"},
            workflow_error=combined_error,
        ).model_dump()
    safe_report.update(
        {
            "case_id": case_id,
            "findings": list(case_file.get("findings", [])),
            "evidence_count": len(case_file.get("evidence", [])),
            "screening_status": case_file.get("screening", {}).get("status"),
            "validation": validation,
            "workflow_error": generation_error or workflow_error,
            "recommended_action": "HUMAN_REVIEW_REQUIRED",
            "automated_compliance_decision": False,
        }
    )
    return safe_report
