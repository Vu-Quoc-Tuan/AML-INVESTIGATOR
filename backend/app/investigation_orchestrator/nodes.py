"""Supervisor and stub worker nodes for the AML investigation graph."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END
from langgraph.types import Command

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
        target = "report_agent" if not state.get("report") else "human_review"
        phase = "reporting" if target == "report_agent" else "human_review"
        return Command(
            update={
                "phase": phase,
                "case_status": "IN_REVIEW",
                "handoff_log": [
                    _handoff(
                        "supervisor",
                        target,
                        "Workflow failure requires human review",
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


def planner_node(
    state: InvestigationState,
) -> Command[Literal["supervisor"]]:
    """Return the structured plan that a future LLM planner may replace."""

    plan = [
        "transaction_investigation",
        "kyc_entity_investigation",
        "screening_and_compliance",
        "evidence_validation",
        "report_generation",
        "human_review",
    ]
    return Command(
        update={
            "investigation_plan": plan,
            "handoff_log": [
                _handoff("planner", "supervisor", "Investigation plan created")
            ],
        },
        goto="supervisor",
    )


def parallel_dispatch_node(state: InvestigationState) -> dict[str, str]:
    """Mark the start of the fixed Transaction/KYC fork."""

    return {"phase": "parallel_investigation"}


def transaction_agent_node(state: InvestigationState) -> dict[str, object]:
    """Produce representative transaction findings without calling real tools."""

    case_id = state["case_id"]
    visibility = state.get("alert", {}).get("data_visibility", "FULL_INTERNAL")
    source_system = {
        "FULL_INTERNAL": "SHB_TRANSACTION_LEDGER",
        "PAYMENT_MESSAGE_ONLY": "PAYMENT_MESSAGE",
        "ENRICHED_EXTERNAL": "INTERBANK_ENRICHMENT_DEMO",
    }.get(visibility, "UNKNOWN")
    evidence_id = f"{case_id}:transaction:1"
    output: AgentOutput = {
        "agent": "transaction_agent",
        "status": "COMPLETED",
        "findings": [
            {
                "finding_id": f"{case_id}:finding:transaction:1",
                "finding_type": "TRANSACTION_PATTERN",
                "summary": "Stub rapid pass-through pattern detected",
                "evidence_ids": [evidence_id],
                "visibility_level": visibility,
            }
        ],
        "evidence": [
            {
                "evidence_id": evidence_id,
                "source_system": source_system,
                "source_record_id": state.get("alert", {}).get(
                    "transaction_id", f"stub-transaction-{case_id}"
                ),
                "visibility_level": visibility,
                "payload": {"stub": True},
            }
        ],
    }
    return {"agent_outputs": {"transaction": output}}


def kyc_agent_node(state: InvestigationState) -> dict[str, object]:
    """Produce KYC/UBO output while respecting SHB-centric visibility."""

    case_id = state["case_id"]
    alert = state.get("alert", {})
    is_shb_entity = alert.get("subject_bank_id", "BANK-SHB-001") == "BANK-SHB-001"
    output: AgentOutput = {
        "agent": "kyc_agent",
        "status": "COMPLETED",
        "findings": [],
        "evidence": [],
        "metadata": {"full_kyc_available": is_shb_entity},
    }

    if is_shb_entity:
        evidence_id = f"{case_id}:kyc:1"
        output["findings"] = [
            {
                "finding_id": f"{case_id}:finding:kyc:1",
                "finding_type": "KYC_PROFILE",
                "summary": "Stub verified SHB KYC and UBO profile collected",
                "evidence_ids": [evidence_id],
                "entity_scope": "SHB_INTERNAL",
            }
        ]
        output["evidence"] = [
            {
                "evidence_id": evidence_id,
                "source_system": "SHB_KYC_REPOSITORY",
                "source_record_id": alert.get("subject_id", f"stub-subject-{case_id}"),
                "payload": {"ubo_verified": True, "stub": True},
            }
        ]

    return {"agent_outputs": {"kyc": output}}


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


def screening_agent_node(
    state: InvestigationState,
) -> Command[Literal["supervisor"]]:
    """Produce screening output and preserve unavailable results as inconclusive."""

    case_id = state["case_id"]
    alert = state.get("alert", {})
    available = alert.get("screening_available", True)
    status = alert.get("screening_status", "NO_MATCH") if available else "INCONCLUSIVE"
    entity_scope = alert.get("screening_entity_scope", "SHB_INTERNAL")
    match_basis = alert.get("screening_match_basis", "IDENTIFIER")
    if status == "CONFIRMED_MATCH" and entity_scope == "EXTERNAL" and match_basis == "NAME":
        status = "POTENTIAL_MATCH"

    evidence_id = f"{case_id}:screening:1"
    output: AgentOutput = {
        "agent": "screening_agent",
        "status": status,
        "available": available,
        "findings": [
            {
                "finding_id": f"{case_id}:finding:screening:1",
                "finding_type": "SCREENING_RESULT",
                "summary": f"Screening completed with status {status}",
                "evidence_ids": [evidence_id],
                "entity_scope": entity_scope,
                "match_basis": match_basis,
            }
        ],
        "evidence": [
            {
                "evidence_id": evidence_id,
                "source_system": "INTERNAL_SCREENING_SERVICE",
                "source_record_id": f"stub-screening-{case_id}",
                "payload": {"available": available, "status": status, "stub": True},
            }
        ],
    }
    return Command(
        update={
            "agent_outputs": {"screening": output},
            "handoff_log": [
                _handoff("screening_agent", "supervisor", "Screening completed")
            ],
        },
        goto="supervisor",
    )
