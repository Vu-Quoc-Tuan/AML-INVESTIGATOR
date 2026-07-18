"""Deterministic evidence checks required before dossier generation."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.types import Command

from .state import AgentOutput, Finding, InvestigationState


LEGAL_SOURCE_SYSTEM = "VN_PENAL_CODE_RAG"


def _extend_from_agent_output(
    findings: list[Any],
    evidence: list[Any],
    issues: list[str],
    output: AgentOutput | None,
    label: str,
) -> None:
    if output is None:
        return
    if not isinstance(output, dict):
        issues.append(f"{label} output must be a dictionary")
        return
    extra_findings = output.get("findings", [])
    extra_evidence = output.get("evidence", [])
    if isinstance(extra_findings, list):
        findings.extend(extra_findings)
    else:
        issues.append(f"{label} findings must be a list")
    if isinstance(extra_evidence, list):
        evidence.extend(extra_evidence)
    else:
        issues.append(f"{label} evidence must be a list")


def _dedupe_evidence(
    evidence: list[Any], issues: list[str]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Keep one record per evidence_id; reject conflicting duplicates."""

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
        existing = evidence_by_id.get(evidence_id)
        if existing is None:
            evidence_by_id[evidence_id] = item
            valid_evidence.append(item)
            continue
        # Same id must not silently overwrite different provenance/linkage.
        if (
            existing.get("source_system") != item.get("source_system")
            or existing.get("source_record_id") != item.get("source_record_id")
            or (existing.get("payload") or {}).get("query_id")
            != (item.get("payload") or {}).get("query_id")
            or (existing.get("payload") or {}).get("article")
            != (item.get("payload") or {}).get("article")
        ):
            issues.append(
                f"duplicate evidence_id {evidence_id} has conflicting payloads"
            )
        # Identical duplicates are dropped from the list (already retained once).
    return evidence_by_id, valid_evidence


def validate_evidence(
    case_file: dict[str, Any],
    screening_output: AgentOutput | None = None,
    legal_output: AgentOutput | None = None,
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

    # Scout universe before legal merge (case_file + screening only).
    scout_ids: set[str] = {
        str(item.get("finding_id"))
        for item in findings
        if isinstance(item, dict)
        and item.get("finding_id")
        and item.get("finding_type") != "LEGAL_CITATION"
    }
    if screening_output and isinstance(screening_output, dict):
        for item in screening_output.get("findings") or []:
            if isinstance(item, dict) and item.get("finding_id"):
                scout_ids.add(str(item["finding_id"]))

    _extend_from_agent_output(findings, evidence, issues, screening_output, "screening")
    _extend_from_agent_output(findings, evidence, issues, legal_output, "legal")

    evidence_by_id, valid_evidence = _dedupe_evidence(evidence, issues)

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
            if finding.get("finding_type") == "LEGAL_CITATION":
                if item.get("source_system") != LEGAL_SOURCE_SYSTEM:
                    finding_issues.append(
                        f"evidence {evidence_id} is not a legal RAG citation source"
                    )
                payload = item.get("payload") or {}
                if not isinstance(payload, dict) or not payload.get("article"):
                    finding_issues.append(
                        f"evidence {evidence_id} legal payload missing article"
                    )
                linked = payload.get("linked_finding_ids") if isinstance(payload, dict) else None
                if not isinstance(linked, list) or not linked:
                    finding_issues.append(
                        f"evidence {evidence_id} missing linked scout finding ids"
                    )
                else:
                    for linked_id in linked:
                        if str(linked_id) not in scout_ids:
                            finding_issues.append(
                                f"evidence {evidence_id} links unknown scout finding "
                                f"{linked_id}"
                            )
            else:
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

        if finding.get("finding_type") == "LEGAL_CITATION":
            if not evidence_ids:
                finding_issues.append("legal citation requires evidence_ids")

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
        "legal": legal_output or {},
    }
    return validation, validated_case_file


def evidence_validator_node(
    state: InvestigationState,
) -> Command[Literal["supervisor"]]:
    """Validate staged findings and return control to the Supervisor."""

    outputs = state.get("agent_outputs", {})
    screening = outputs.get("screening")
    legal = outputs.get("legal")
    validation, case_file = validate_evidence(
        state.get("case_file", {}), screening, legal
    )
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
