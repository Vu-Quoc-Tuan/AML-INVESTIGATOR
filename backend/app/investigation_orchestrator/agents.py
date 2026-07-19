"""LLM agent construction and deterministic output boundary checks."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from app.investigation_events import (
    ExecutionEventRecorder,
    InvestigationEventType,
    ToolExecutionFailed,
)

from .agent_schemas import (
    MANDATORY_STAGES,
    BehaviorMappingResponse,
    InvestigationPlanResponse,
    InvestigationReportResponse,
    PlanStep,
    RagQuerySpec,
    RiskHypothesis,
    ScreeningAnalysisResponse,
    WorkerAnalysisResponse,
)
from .prompts import (
    BEHAVIOR_MAPPER_PROMPT,
    KYC_AGENT_PROMPT,
    PLANNER_PROMPT,
    REPORT_AGENT_PROMPT,
    SCREENING_AGENT_PROMPT,
    TRANSACTION_AGENT_PROMPT,
)
from .state import AgentOutput, InvestigationState
from .soft_prompt import append_soft_prompt
from .tool_registry import AgentName, ToolResult


def _child_config(config: RunnableConfig | None) -> RunnableConfig:
    child: RunnableConfig = dict(config or {})
    child["recursion_limit"] = 8
    return child


def _event_recorder_from_config(
    config: RunnableConfig | None,
) -> tuple[ExecutionEventRecorder | None, str | None]:
    """Pull the instrumented workflow recorder (if any) off LangGraph config."""

    configurable = (config or {}).get("configurable") or {}
    if not isinstance(configurable, dict):
        return None, None
    recorder = configurable.get("aml_event_recorder")
    agent_id = configurable.get("aml_agent_id")
    if not isinstance(recorder, ExecutionEventRecorder):
        return None, None
    return recorder, str(agent_id) if agent_id else None


def record_tool_messages(
    recorder: ExecutionEventRecorder | None,
    agent_id: str,
    messages: Sequence[Any],
    tool_names: set[str],
) -> None:
    """Persist TOOL_* events from ToolMessages (reliable with create_agent).

    LangChain callbacks often do not fire for create_agent tool runs; reading the
    final message list matches how evidence is admitted in collect_tool_results.
    """

    if recorder is None:
        return
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name not in tool_names:
            continue
        name = str(message.name)
        recorder.append(
            InvestigationEventType.TOOL_STARTED,
            agent_id=agent_id,
            tool_name=name,
            status="RUNNING",
            summary=f"Tool {name} started",
            payload={"tool_call_id": getattr(message, "tool_call_id", None)},
        )
        if getattr(message, "status", None) == "error":
            recorder.append(
                InvestigationEventType.TOOL_FAILED,
                agent_id=agent_id,
                tool_name=name,
                status="FAILED",
                summary=f"Tool {name} failed",
                payload={"error_type": "ToolMessageError"},
            )
            continue
        try:
            result = ToolResult.model_validate(_decode_tool_message(message))
        except (TypeError, ValueError, json.JSONDecodeError):
            recorder.append(
                InvestigationEventType.TOOL_FAILED,
                agent_id=agent_id,
                tool_name=name,
                status="FAILED",
                summary=f"Tool {name} failed",
                payload={"error_type": "InvalidToolResult"},
            )
            continue
        if result.status == "ERROR":
            recorder.append(
                InvestigationEventType.TOOL_FAILED,
                agent_id=agent_id,
                tool_name=name,
                status="FAILED",
                summary=f"Tool {name} failed",
                payload={
                    "error_code": result.error_code,
                    "warnings": list(result.warnings)[:8],
                },
            )
            continue
        recorder.append(
            InvestigationEventType.TOOL_SUCCEEDED,
            agent_id=agent_id,
            tool_name=name,
            status=result.status,
            summary=f"Tool {name} completed",
            payload={
                "status": result.status,
                "error_code": result.error_code,
                "evidence_count": len(result.evidence),
                "warnings": list(result.warnings)[:8],
            },
        )


def build_planner_agent(model: Any, *, soft_prompt: str | None = None) -> Any:
    return create_agent(
        model=model,
        tools=[],
        system_prompt=append_soft_prompt(PLANNER_PROMPT, soft_prompt),
        response_format=ToolStrategy(InvestigationPlanResponse),
    )


def _build_worker_agent(
    model: Any,
    tools: Sequence[BaseTool],
    *,
    prompt: str,
    response_schema: type[WorkerAnalysisResponse] = WorkerAnalysisResponse,
    soft_prompt: str | None = None,
) -> Any | None:
    if not tools:
        return None
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=append_soft_prompt(prompt, soft_prompt),
        response_format=ToolStrategy(response_schema),
    )


def build_transaction_agent(
    model: Any,
    tools: Sequence[BaseTool],
    *,
    soft_prompt: str | None = None,
) -> Any | None:
    return _build_worker_agent(
        model, tools, prompt=TRANSACTION_AGENT_PROMPT, soft_prompt=soft_prompt
    )


def build_kyc_agent(
    model: Any,
    tools: Sequence[BaseTool],
    *,
    soft_prompt: str | None = None,
) -> Any | None:
    return _build_worker_agent(
        model, tools, prompt=KYC_AGENT_PROMPT, soft_prompt=soft_prompt
    )


def build_screening_agent(
    model: Any,
    tools: Sequence[BaseTool],
    *,
    soft_prompt: str | None = None,
) -> Any | None:
    return _build_worker_agent(
        model,
        tools,
        prompt=SCREENING_AGENT_PROMPT,
        response_schema=ScreeningAnalysisResponse,
        soft_prompt=soft_prompt,
    )


def build_behavior_mapper_agent(
    model: Any, *, soft_prompt: str | None = None
) -> Any:
    return create_agent(
        model=model,
        tools=[],
        system_prompt=append_soft_prompt(BEHAVIOR_MAPPER_PROMPT, soft_prompt),
        response_format=ToolStrategy(BehaviorMappingResponse),
    )


def build_report_agent(model: Any, *, soft_prompt: str | None = None) -> Any:
    return create_agent(
        model=model,
        tools=[],
        system_prompt=append_soft_prompt(REPORT_AGENT_PROMPT, soft_prompt),
        response_format=ToolStrategy(InvestigationReportResponse),
    )


def _scout_findings(state: InvestigationState) -> list[dict[str, Any]]:
    case_file = state.get("case_file") or {}
    findings = [
        item
        for item in (case_file.get("findings") or [])
        if isinstance(item, dict) and item.get("finding_type") != "LEGAL_CITATION"
    ]
    screening = (state.get("agent_outputs") or {}).get("screening") or {}
    findings.extend(
        item
        for item in (screening.get("findings") or [])
        if isinstance(item, dict)
    )
    return findings


def _scout_finding_ids(state: InvestigationState) -> set[str]:
    return {
        str(item["finding_id"])
        for item in _scout_findings(state)
        if item.get("finding_id")
    }


def _sanitize_behavior_mapping(
    mapping: dict[str, Any], state: InvestigationState
) -> dict[str, Any]:
    """Drop legal queries that are not grounded in real scout findings."""

    allowed = _scout_finding_ids(state)
    raw_queries = mapping.get("rag_queries") or []
    cleaned: list[dict[str, Any]] = []
    for index, query in enumerate(raw_queries):
        if not isinstance(query, dict):
            continue
        linked = [
            str(item)
            for item in (query.get("linked_finding_ids") or [])
            if item and str(item) in allowed
        ]
        query_text = str(query.get("query_text") or "").strip()
        if not linked or not query_text:
            continue
        cleaned.append(
            {
                "query_id": str(query.get("query_id") or f"RQ-{index + 1}"),
                "query_text": query_text[:1000],
                "linked_finding_ids": linked,
                "hypothesis_tag": query.get("hypothesis_tag"),
            }
        )
    summary = str(mapping.get("behavior_summary") or "").strip()
    if not summary:
        summary = (
            "No scout findings available for legal enrichment"
            if not allowed
            else "Behavior summary unavailable"
        )
    hypotheses = []
    for item in mapping.get("risk_hypotheses") or []:
        try:
            hypotheses.append(RiskHypothesis.model_validate(item))
        except Exception:
            continue
    return BehaviorMappingResponse(
        behavior_summary=summary[:1200],
        rag_queries=[RagQuerySpec.model_validate(item) for item in cleaned[:5]],
        risk_hypotheses=hypotheses,
    ).model_dump()


def _fallback_behavior_mapping(state: InvestigationState) -> dict[str, Any]:
    scouts = _scout_findings(state)
    summaries = [
        str(item.get("summary"))
        for item in scouts
        if item.get("summary")
    ]
    linked = [str(item["finding_id"]) for item in scouts if item.get("finding_id")]
    if not linked:
        return BehaviorMappingResponse(
            behavior_summary="No scout findings available for legal enrichment",
            rag_queries=[],
            risk_hypotheses=[],
        ).model_dump()

    behavior_summary = " ".join(summaries)[:1200] or "Scout findings present"
    query_text = (
        "Hành vi tài chính đáng ngờ sau đây có thể liên quan điều luật nào trong "
        f"Bộ luật Hình sự Việt Nam: {behavior_summary}"
    )
    return BehaviorMappingResponse(
        behavior_summary=behavior_summary,
        rag_queries=[
            RagQuerySpec(
                query_id="RQ-FALLBACK-1",
                query_text=query_text[:1000],
                linked_finding_ids=linked[:10],
                hypothesis_tag="fallback_behavior_frame",
            )
        ],
        risk_hypotheses=[],
    ).model_dump()


def invoke_behavior_mapper(
    agent: Any | None,
    context: str,
    state: InvestigationState,
    config: RunnableConfig | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Return behavior-framed RAG queries grounded in scout findings only."""

    if agent is None:
        return _sanitize_behavior_mapping(
            _fallback_behavior_mapping(state), state
        ), "NoBehaviorMapperAgent"
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            config=_child_config(config),
        )
        mapping = _structured_response(result, BehaviorMappingResponse)
        return _sanitize_behavior_mapping(mapping.model_dump(), state), None
    except Exception as exc:
        return _sanitize_behavior_mapping(
            _fallback_behavior_mapping(state), state
        ), type(exc).__name__


def _structured_response(result: dict[str, Any], schema: type[Any]) -> Any:
    return schema.model_validate(result.get("structured_response"))


def invoke_planner(
    agent: Any, context: str, config: RunnableConfig | None = None
) -> tuple[dict[str, Any], str | None]:
    """Return a valid plan; preserve a redacted error code on provider failure."""

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            config=_child_config(config),
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
    config: RunnableConfig | None = None,
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
    child_config = _child_config(config)
    allowed_tools = {tool.name for tool in tools}
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            config=child_config,
        )
        schema = ScreeningAnalysisResponse if owner == "screening" else WorkerAnalysisResponse
        analysis = _structured_response(result, schema)
        messages = result.get("messages", [])
        tool_results, warnings = collect_tool_results(messages, allowed_tools)
        recorder, configured_agent_id = _event_recorder_from_config(child_config)
        record_tool_messages(
            recorder,
            configured_agent_id or f"{owner}_agent",
            messages,
            allowed_tools,
        )
        output = _assemble_worker_output(owner, analysis, tool_results, warnings)
        if owner == "screening":
            output = _finalize_screening_output(
                output,
                ScreeningAnalysisResponse.model_validate(analysis),
                tool_results,
            )
        return output
    except ToolExecutionFailed:
        raise
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


def _legal_mappings_from_case_file(case_file: dict[str, Any]) -> list[dict[str, Any]]:
    """Map scout findings to articles using legal evidence linkage."""

    evidence_by_id = {
        item.get("evidence_id"): item
        for item in case_file.get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    scout_ids = {
        str(item.get("finding_id"))
        for item in case_file.get("findings", [])
        if isinstance(item, dict)
        and item.get("finding_id")
        and item.get("finding_type") != "LEGAL_CITATION"
    }
    mappings: list[dict[str, Any]] = []
    for finding in case_file.get("findings", []):
        if not isinstance(finding, dict):
            continue
        if finding.get("finding_type") != "LEGAL_CITATION":
            continue
        evidence_ids = [
            str(item) for item in (finding.get("evidence_ids") or []) if item
        ]
        linked_scout_ids: list[str] = []
        articles: list[str] = []
        for evidence_id in evidence_ids:
            item = evidence_by_id.get(evidence_id) or {}
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            article = payload.get("article")
            if article:
                articles.append(str(article))
            for linked in payload.get("linked_finding_ids") or []:
                linked_id = str(linked)
                if linked_id in scout_ids and linked_id not in linked_scout_ids:
                    linked_scout_ids.append(linked_id)
        if not evidence_ids or not articles or not linked_scout_ids:
            continue
        mappings.append(
            {
                "finding_ids": linked_scout_ids,
                "evidence_ids": evidence_ids,
                "article": articles[0],
                "relevance_note": str(finding.get("summary") or articles[0]),
            }
        )
    return mappings


def _default_risk_level(case_file: dict[str, Any], validation: dict[str, Any]) -> str:
    """Score risk from scout evidence only; legal hits never auto-escalate.

    Legal citations support auditability of hypotheses. They prove that a
    retrieved statute *may relate to a query*, not that the case is high risk.
    """

    if validation.get("status") == "FAILED":
        return "INCONCLUSIVE"

    scout_findings = [
        item
        for item in case_file.get("findings", [])
        if isinstance(item, dict) and item.get("finding_type") != "LEGAL_CITATION"
    ]
    if not scout_findings:
        return "INCONCLUSIVE"

    screening = case_file.get("screening") or {}
    if screening.get("status") == "CONFIRMED_MATCH":
        return "HIGH"
    return "MEDIUM"


def invoke_report(
    agent: Any,
    context: str,
    case_id: str,
    *,
    case_file: dict[str, Any],
    validation: dict[str, Any],
    workflow_error: str | None,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Return a safe automated risk dossier even if the provider call fails."""

    legal_mappings = _legal_mappings_from_case_file(case_file)
    default_risk = _default_risk_level(case_file, validation or {})
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            config=_child_config(config),
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
            summary=(
                "The automated draft could not be completed. The case file and "
                "validation status remain available for inspection."
            ),
            overall_risk_level=default_risk,  # type: ignore[arg-type]
            risk_rationale="Automated narrative unavailable; inspect validated findings.",
            legal_mappings=[],
            evidence_count=len(case_file.get("evidence", [])),
            validation=validation or {"status": "INCONCLUSIVE"},
            workflow_error=combined_error,
        ).model_dump()
    # Hard override factual fields; legal_mappings only from validated citations.
    safe_report.update(
        {
            "case_id": case_id,
            "findings": list(case_file.get("findings", [])),
            "evidence_count": len(case_file.get("evidence", [])),
            "screening_status": (case_file.get("screening") or {}).get("status"),
            "validation": validation,
            "workflow_error": generation_error or workflow_error,
            "legal_mappings": legal_mappings,
            "overall_risk_level": safe_report.get("overall_risk_level") or default_risk,
        }
    )
    if not safe_report.get("risk_rationale"):
        safe_report["risk_rationale"] = (
            "Risk level assigned from validated scout and legal-citation findings."
        )
    return safe_report
