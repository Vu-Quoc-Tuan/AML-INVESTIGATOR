"""Deterministic orchestration nodes and LLM node adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig

from langgraph.graph import END
from langgraph.types import Command

from app.legal_rag.config import LegalRagConfig
from app.legal_rag.hybrid_retriever import LegalRetriever
from app.legal_rag.tool_adapter import hits_to_boundary

from .agents import invoke_behavior_mapper, invoke_planner, invoke_worker
from .prompts import behavior_mapper_context, planner_context, screening_context, worker_context
from .state import AgentOutput, HandoffRecord, InvestigationState


SupervisorDestination = Literal[
    "planner",
    "parallel_dispatch",
    "screening_agent",
    "behavior_mapper",
    "legal_rag",
    "evidence_validator",
    "report_agent",
    "__end__",
]


def _handoff(source: str, target: str, reason: str) -> HandoffRecord:
    return {"source": source, "target": target, "reason": reason}


def supervisor_node(
    state: InvestigationState,
) -> Command[SupervisorDestination]:
    """Apply mandatory routing rules and hand control to the next stage."""

    if state.get("workflow_error"):
        if state.get("case_file") and not state.get("evidence_validation"):
            # Prefer finishing validation + report when scouts already produced data.
            if "legal" not in state.get("agent_outputs", {}) and state.get(
                "behavior_mapping"
            ):
                target: SupervisorDestination = "legal_rag"
                phase = "legal_enrichment"
                reason = "Complete legal enrichment before failure dossier"
            elif not state.get("behavior_mapping") and state.get("case_file"):
                target = "behavior_mapper"
                phase = "legal_enrichment"
                reason = "Map behaviors before failure dossier"
            elif not state.get("evidence_validation"):
                target = "evidence_validator"
                phase = "evidence_validation"
                reason = "Validate evidence before failure dossier"
            else:
                target = "report_agent"
                phase = "reporting"
                reason = "Draft failure dossier"
        elif not state.get("report"):
            target = "report_agent"
            phase = "reporting"
            reason = "Draft failure dossier"
        else:
            return Command(
                update={
                    "phase": "complete",
                    "handoff_log": [
                        _handoff(
                            "supervisor",
                            "end",
                            "Investigation complete after failure dossier",
                        )
                    ],
                },
                goto=END,
            )
        return Command(
            update={
                "phase": phase,
                "handoff_log": [_handoff("supervisor", target, reason)],
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
        reason = "Run watchlist screening after investigation evidence is merged"
    elif not state.get("behavior_mapping"):
        target = "behavior_mapper"
        phase = "legal_enrichment"
        reason = "Frame behaviors into legal retrieval queries"
    elif "legal" not in state.get("agent_outputs", {}):
        target = "legal_rag"
        phase = "legal_enrichment"
        reason = "Retrieve penal-code passages for framed behaviors"
    elif not state.get("evidence_validation"):
        target = "evidence_validator"
        phase = "evidence_validation"
        reason = "Apply deterministic evidence rules"
    elif not state.get("report"):
        target = "report_agent"
        phase = "reporting"
        reason = "Draft the risk dossier"
    else:
        return Command(
            update={
                "phase": "complete",
                "handoff_log": [
                    _handoff(
                        "supervisor",
                        "end",
                        "Investigation complete after risk dossier",
                    )
                ],
            },
            goto=END,
        )

    return Command(
        update={
            "phase": phase,
            "handoff_log": [_handoff("supervisor", target, reason)],
        },
        goto=target,
    )


def make_planner_node(agent: Any) -> Callable[[InvestigationState], Command]:
    """Adapt the structured planner agent to the shared workflow state."""

    def planner_node(
        state: InvestigationState, config: RunnableConfig
    ) -> Command[Literal["supervisor"]]:
        plan, error_type = invoke_planner(agent, planner_context(state), config)
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

    def worker_node(
        state: InvestigationState, config: RunnableConfig
    ) -> dict[str, object]:
        output = invoke_worker(owner, agent, tools, worker_context(state), config)
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
    """Adapt screening output and continue the one-way pipeline."""

    def screening_agent_node(
        state: InvestigationState,
        config: RunnableConfig,
    ) -> Command[Literal["supervisor"]]:
        output = invoke_worker(
            "screening", agent, tools, screening_context(state), config
        )
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


def make_behavior_mapper_node(
    agent: Any | None,
) -> Callable[[InvestigationState], Command]:
    """Frame scout findings into legal RAG queries without inventing evidence."""

    def behavior_mapper_node(
        state: InvestigationState,
        config: RunnableConfig,
    ) -> Command[Literal["supervisor"]]:
        mapping, error_type = invoke_behavior_mapper(
            agent, behavior_mapper_context(state), state, config
        )
        update: dict[str, Any] = {
            "behavior_mapping": mapping,
            "handoff_log": [
                _handoff(
                    "behavior_mapper",
                    "supervisor",
                    "Behavior framed into legal retrieval queries",
                )
            ],
        }
        if error_type:
            update["errors"] = [f"Behavior mapper fallback used: {error_type}"]
        return Command(update=update, goto="supervisor")

    return behavior_mapper_node


def make_legal_rag_node(
    retriever: LegalRetriever,
    config: LegalRagConfig | None = None,
) -> Callable[[InvestigationState], Command]:
    """Deterministic hybrid legal retrieval from behavior-mapped queries."""

    cfg = config or LegalRagConfig.from_env()

    def legal_rag_node(state: InvestigationState) -> Command[Literal["supervisor"]]:
        mapping = state.get("behavior_mapping") or {}
        queries = mapping.get("rag_queries") or []
        findings: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        warnings: list[str] = []
        query_results: list[dict[str, Any]] = []
        available = True
        status = "COMPLETED"

        if not queries:
            status = "NO_DATA"
            available = False
            warnings.append("NO_RAG_QUERIES")
        else:
            for index, query in enumerate(queries):
                if not isinstance(query, dict):
                    warnings.append(f"invalid_query[{index}]")
                    continue
                query_id = str(query.get("query_id") or f"RQ-{index + 1}")
                query_text = str(query.get("query_text") or "").strip()
                linked = [
                    str(item)
                    for item in (query.get("linked_finding_ids") or [])
                    if item
                ]
                if not linked:
                    warnings.append(f"{query_id}:missing_scout_links")
                    continue
                if not query_text:
                    warnings.append(f"{query_id}:empty_query")
                    continue
                try:
                    hits = retriever.retrieve(query_text, top_k=cfg.top_k)
                    boundary = hits_to_boundary(
                        query_id=query_id,
                        query_text=query_text,
                        hits=hits,
                        linked_finding_ids=linked,
                        config=cfg,
                    )
                except Exception as exc:
                    available = False
                    status = "ERROR"
                    warnings.append(f"{query_id}:{type(exc).__name__}")
                    continue

                artifact = boundary.model_dump(mode="json")
                query_results.append(artifact.get("data") or {})
                warnings.extend(list(artifact.get("warnings") or []))
                if artifact.get("status") == "ERROR":
                    available = False
                    status = "ERROR"
                elif artifact.get("status") == "NO_DATA" and status == "COMPLETED":
                    status = "INCONCLUSIVE"
                for item in artifact.get("evidence") or []:
                    if isinstance(item, dict):
                        evidence.append(item)
                data = artifact.get("data") or {}
                for hit in data.get("hits") or []:
                    if not isinstance(hit, dict):
                        continue
                    evidence_id = hit.get("evidence_id")
                    if not evidence_id:
                        continue
                    findings.append(
                        {
                            "finding_id": f"{state['case_id']}:finding:legal:{query_id}:{hit.get('rank', 1)}",
                            "finding_type": "LEGAL_CITATION",
                            "summary": (
                                f"Penal-code passage {hit.get('article')} may relate to "
                                f"behavior query {query_id}"
                            ),
                            "evidence_ids": [evidence_id],
                            "visibility_level": "FULL_INTERNAL",
                        }
                    )

        output: AgentOutput = {
            "agent": "legal_rag",
            "status": status,
            "available": available and bool(evidence),
            "findings": findings,
            "evidence": evidence,
            "metadata": {
                "warnings": warnings,
                "query_results": query_results,
                "behavior_summary": mapping.get("behavior_summary"),
            },
        }
        update: dict[str, Any] = {
            "agent_outputs": {"legal": output},
            "handoff_log": [
                _handoff("legal_rag", "supervisor", "Legal retrieval completed")
            ],
        }
        if status == "ERROR":
            update["errors"] = ["Legal RAG retrieval failed"]
        return Command(update=update, goto="supervisor")

    return legal_rag_node
