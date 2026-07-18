"""Deterministic dossier stub used until the LLM report agent is available."""

from __future__ import annotations

from typing import Literal

from langgraph.types import Command

from .state import InvestigationState


def report_agent_node(
    state: InvestigationState,
) -> Command[Literal["supervisor"]]:
    """Build a reviewable dossier from validated case data only."""

    case_file = state.get("case_file", {})
    findings = case_file.get("findings", [])
    validation = state.get("evidence_validation", {})
    report = {
        "case_id": state["case_id"],
        "title": "AML Investigation Dossier (stub)",
        "summary": f"Prepared {len(findings)} evidence-backed findings for review.",
        "findings": findings,
        "evidence_count": len(case_file.get("evidence", [])),
        "screening_status": case_file.get("screening", {}).get("status"),
        "validation": validation,
        "workflow_error": state.get("workflow_error"),
        "recommended_action": "HUMAN_REVIEW_REQUIRED",
        "automated_compliance_decision": False,
    }
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
