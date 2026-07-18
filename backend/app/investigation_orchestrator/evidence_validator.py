"""Deterministic evidence checks required before dossier generation."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.types import Command

from .state import AgentOutput, Finding, InvestigationState


def validate_evidence(
    case_file: dict[str, Any], screening_output: AgentOutput | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a validation summary and a case file containing valid findings."""

    issues: list[str] = []
    if not isinstance(case_file, dict):
        issues.append("case_file must be a dictionary")
        case_file = {}

    raw_findings = case_file.get("findings", [])
    raw_evidence = case_file.get("evidence", [])
    findings = list(raw_findings) if isinstance(raw_findings, list) else []
    evidence = list(raw_evidence) if isinstance(raw_evidence, list) else []
    if not isinstance(raw_findings, list):
        issues.append("case_file.findings must be a list")
    if not isinstance(raw_evidence, list):
        issues.append("case_file.evidence must be a list")

    if screening_output is not None and not isinstance(screening_output, dict):
        issues.append("screening output must be a dictionary")
        screening_output = None
    if screening_output:
        screening_findings = screening_output.get("findings", [])
        screening_evidence = screening_output.get("evidence", [])
        if isinstance(screening_findings, list):
            findings.extend(screening_findings)
        else:
            issues.append("screening findings must be a list")
        if isinstance(screening_evidence, list):
            evidence.extend(screening_evidence)
        else:
            issues.append("screening evidence must be a list")

    evidence_by_id: dict[str, dict[str, Any]] = {}
    valid_evidence: list[dict[str, Any]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            issues.append(f"evidence[{index}] must be a dictionary")
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            issues.append(f"evidence[{index}] has no evidence_id")
            continue
        evidence_by_id[evidence_id] = item
        valid_evidence.append(item)

    valid_findings: list[Finding] = []

    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            issues.append(f"finding[{index}] must be a dictionary")
            continue
        finding_id = finding.get("finding_id", "unknown-finding")
        finding_issues: list[str] = []
        evidence_ids = finding.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or not evidence_ids:
            finding_issues.append("has no evidence_ids")
            evidence_ids = []

        for evidence_id in evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                finding_issues.append(f"references missing evidence {evidence_id}")
                continue
            if not item.get("source_system") or not item.get("source_record_id"):
                finding_issues.append(f"evidence {evidence_id} has no source reference")
            visibility = item.get("visibility_level")
            expected_source = {
                "FULL_INTERNAL": "SHB_TRANSACTION_LEDGER",
                "PAYMENT_MESSAGE_ONLY": "PAYMENT_MESSAGE",
                "ENRICHED_EXTERNAL": "INTERBANK_ENRICHMENT_DEMO",
            }.get(visibility)
            if expected_source and item.get("source_system") != expected_source:
                finding_issues.append(
                    f"evidence {evidence_id} source does not match {visibility}"
                )

        if (
            finding.get("finding_type") == "TRANSACTION_PATTERN"
            and not finding.get("visibility_level")
        ):
            finding_issues.append("has no visibility_level")
        if finding.get("finding_type") == "TRANSACTION_PATTERN" and finding.get(
            "visibility_level"
        ) not in {"FULL_INTERNAL", "PAYMENT_MESSAGE_ONLY", "ENRICHED_EXTERNAL"}:
            finding_issues.append("has unsupported visibility_level")

        if (
            finding.get("finding_type") == "SCREENING_RESULT"
            and screening_output
            and not screening_output.get("available", True)
            and screening_output.get("status") != "INCONCLUSIVE"
        ):
            finding_issues.append("unavailable screening must be INCONCLUSIVE")

        if (
            screening_output
            and screening_output.get("status") == "CONFIRMED_MATCH"
            and finding.get("entity_scope") == "EXTERNAL"
            and finding.get("match_basis") == "NAME"
        ):
            finding_issues.append("external name-only match cannot be CONFIRMED_MATCH")

        if finding_issues:
            issues.extend(f"{finding_id}: {issue}" for issue in finding_issues)
        else:
            valid_findings.append(finding)

    status = "PASSED" if not issues else ("PARTIAL" if valid_findings else "FAILED")
    validation = {
        "status": status,
        "valid_finding_count": len(valid_findings),
        "invalid_finding_count": len(findings) - len(valid_findings),
        "issues": issues,
    }
    validated_case_file = {
        **case_file,
        "findings": valid_findings,
        "evidence": valid_evidence,
        "screening": screening_output or {},
    }
    return validation, validated_case_file


def evidence_validator_node(
    state: InvestigationState,
) -> Command[Literal["supervisor"]]:
    """Validate staged findings and return control to the Supervisor."""

    screening = state.get("agent_outputs", {}).get("screening")
    validation, case_file = validate_evidence(state.get("case_file", {}), screening)
    return Command(
        update={
            "case_file": case_file,
            "evidence_validation": validation,
            "handoff_log": [
                {
                    "source": "evidence_validator",
                    "target": "supervisor",
                    "reason": f"Evidence validation {validation['status']}",
                }
            ],
        },
        goto="supervisor",
    )
