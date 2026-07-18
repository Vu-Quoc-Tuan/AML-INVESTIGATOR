"""Deterministic graph nodes used to test orchestration without network calls."""

from __future__ import annotations

from typing import Literal

from langgraph.types import Command

from app.investigation_orchestrator.agent_schemas import MANDATORY_STAGES
from app.investigation_orchestrator.state import InvestigationState
from app.legal_rag.hybrid_retriever import StaticLegalRetriever


def planner_node(state: InvestigationState) -> Command[Literal["supervisor"]]:
    return Command(
        update={
            "investigation_plan": {
                "case_summary": f"Deterministic test plan for {state['case_id']}",
                "steps": [
                    {
                        "stage": stage,
                        "objective": f"Complete {stage}",
                        "rationale": "Mandatory test stage",
                    }
                    for stage in MANDATORY_STAGES
                ],
            },
            "handoff_log": [
                {"source": "planner", "target": "supervisor", "reason": "Plan created"}
            ],
        },
        goto="supervisor",
    )


def transaction_node(state: InvestigationState) -> dict[str, object]:
    case_id = state["case_id"]
    visibility = state.get("alert", {}).get("data_visibility", "FULL_INTERNAL")
    source_system = {
        "FULL_INTERNAL": "SHB_TRANSACTION_LEDGER",
        "PAYMENT_MESSAGE_ONLY": "PAYMENT_MESSAGE",
        "ENRICHED_EXTERNAL": "INTERBANK_ENRICHMENT_DEMO",
    }.get(visibility, "UNKNOWN")
    evidence_id = f"{case_id}:transaction:1"
    return {
        "agent_outputs": {
            "transaction": {
                "agent": "transaction_agent",
                "status": "COMPLETED",
                "available": True,
                "findings": [
                    {
                        "finding_id": f"{case_id}:finding:transaction:1",
                        "finding_type": "TRANSACTION_PATTERN",
                        "summary": "Deterministic rapid pass-through pattern",
                        "evidence_ids": [evidence_id],
                        "visibility_level": visibility,
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": evidence_id,
                        "source_system": source_system,
                        "source_record_id": state.get("alert", {}).get(
                            "transaction_id", f"test-transaction-{case_id}"
                        ),
                        "visibility_level": visibility,
                        "payload": {"fixture": True},
                    }
                ],
            }
        }
    }


def kyc_node(state: InvestigationState) -> dict[str, object]:
    case_id = state["case_id"]
    alert = state.get("alert", {})
    is_internal = alert.get("subject_bank_id", "BANK-SHB-001") == "BANK-SHB-001"
    findings: list[dict] = []
    evidence: list[dict] = []
    if is_internal:
        evidence_id = f"{case_id}:kyc:1"
        findings.append(
            {
                "finding_id": f"{case_id}:finding:kyc:1",
                "finding_type": "KYC_PROFILE",
                "summary": "Deterministic verified internal KYC profile",
                "evidence_ids": [evidence_id],
                "entity_scope": "SHB_INTERNAL",
            }
        )
        evidence.append(
            {
                "evidence_id": evidence_id,
                "source_system": "SHB_KYC_REPOSITORY",
                "source_record_id": alert.get("subject_id", f"test-subject-{case_id}"),
                "payload": {"fixture": True},
            }
        )
    return {
        "agent_outputs": {
            "kyc": {
                "agent": "kyc_agent",
                "status": "COMPLETED" if is_internal else "INCONCLUSIVE",
                "available": is_internal,
                "findings": findings,
                "evidence": evidence,
            }
        }
    }


def screening_node(state: InvestigationState) -> Command[Literal["supervisor"]]:
    case_id = state["case_id"]
    alert = state.get("alert", {})
    available = alert.get("screening_available", True)
    status = alert.get("screening_status", "NO_MATCH") if available else "INCONCLUSIVE"
    entity_scope = alert.get("screening_entity_scope", "SHB_INTERNAL")
    match_basis = alert.get("screening_match_basis", "IDENTIFIER")
    if status == "CONFIRMED_MATCH" and entity_scope == "EXTERNAL" and match_basis == "NAME":
        status = "POTENTIAL_MATCH"
    evidence_id = f"{case_id}:screening:1"
    output = {
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
                "source_record_id": f"test-screening-{case_id}",
                "payload": {"available": available, "status": status, "fixture": True},
            }
        ],
    }
    return Command(
        update={
            "agent_outputs": {"screening": output},
            "handoff_log": [
                {
                    "source": "screening_agent",
                    "target": "supervisor",
                    "reason": "Screening completed",
                }
            ],
        },
        goto="supervisor",
    )


def behavior_mapper_node(state: InvestigationState) -> Command[Literal["supervisor"]]:
    case_id = state["case_id"]
    findings = list((state.get("case_file") or {}).get("findings") or [])
    linked = [
        str(item.get("finding_id"))
        for item in findings
        if isinstance(item, dict) and item.get("finding_id")
    ]
    return Command(
        update={
            "behavior_mapping": {
                "behavior_summary": (
                    f"Deterministic behavior frame for {case_id}: rapid pass-through "
                    "and related scout findings."
                ),
                "rag_queries": [
                    {
                        "query_id": "RQ-TEST-1",
                        "query_text": (
                            "Hành vi chuyển tiền qua trung gian nhanh và hợp pháp hóa "
                            "tài sản do phạm tội có thể liên quan tội rửa tiền như thế nào?"
                        ),
                        "linked_finding_ids": linked[:5],
                        "hypothesis_tag": "money_laundering_pass_through",
                    }
                ],
                "risk_hypotheses": [
                    {
                        "tag": "rapid_pass_through",
                        "rationale": "Transaction scout reported pass-through pattern",
                        "confidence": 0.8,
                    }
                ],
            },
            "handoff_log": [
                {
                    "source": "behavior_mapper",
                    "target": "supervisor",
                    "reason": "Behavior framed into legal retrieval queries",
                }
            ],
        },
        goto="supervisor",
    )


def report_node(state: InvestigationState) -> Command[Literal["supervisor"]]:
    from app.investigation_orchestrator.agents import (
        _default_risk_level,
        _legal_mappings_from_case_file,
    )

    case_file = state.get("case_file", {})
    validation = state.get("evidence_validation", {})
    legal_mappings = _legal_mappings_from_case_file(case_file)
    report = {
        "case_id": state["case_id"],
        "title": "AML Investigation Dossier (test fixture)",
        "summary": "Deterministic risk dossier for investigator review",
        "overall_risk_level": _default_risk_level(case_file, validation),
        "risk_rationale": "Fixture risk rationale based on validated findings only",
        "legal_mappings": legal_mappings,
        "findings": case_file.get("findings", []),
        "evidence_count": len(case_file.get("evidence", [])),
        "screening_status": (case_file.get("screening") or {}).get("status"),
        "validation": validation,
        "workflow_error": state.get("workflow_error"),
    }
    return Command(
        update={
            "report": report,
            "handoff_log": [
                {
                    "source": "report_agent",
                    "target": "supervisor",
                    "reason": "Test risk dossier created",
                }
            ],
        },
        goto="supervisor",
    )


def deterministic_agent_nodes() -> dict:
    return {
        "planner": planner_node,
        "transaction_agent": transaction_node,
        "kyc_agent": kyc_node,
        "screening_agent": screening_node,
        "behavior_mapper": behavior_mapper_node,
        "report_agent": report_node,
    }


def deterministic_legal_retriever() -> StaticLegalRetriever:
    return StaticLegalRetriever()
