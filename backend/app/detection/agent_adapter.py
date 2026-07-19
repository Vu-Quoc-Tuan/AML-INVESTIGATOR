"""Narrow adapter from a queued detection candidate to workflow input/result."""

from __future__ import annotations

from typing import Any

from app.investigation_orchestrator import initial_state

from .contracts import CandidateRecord


def case_id_for(candidate: CandidateRecord) -> str:
    return f"AML-{candidate.candidate_id}"


def to_investigation_input(candidate: CandidateRecord) -> dict:
    decision = candidate.decision
    alert = {
        "source": "realtime_detection_queue",
        "candidate_id": candidate.candidate_id,
        "event_id": candidate.event_id,
        "transaction": candidate.transaction_snapshot,
        "detection": {
            "decision": decision.kind.value,
            "ml_confidence": decision.confidence,
            "model_version": decision.model_version,
            "rule_hits": [
                {
                    "rule_id": hit.rule_id,
                    "reason": hit.reason,
                    "evidence": hit.evidence,
                }
                for hit in decision.rule_hits
            ],
            "imputed_features": list(decision.imputed_features),
        },
    }
    return initial_state(case_id_for(candidate), alert)


def _extract_citations(
    report: dict[str, Any], case_file: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build compact citation cards for UI hover (legal RAG + evidence ledger)."""

    evidence_by_id: dict[str, dict[str, Any]] = {}
    for item in case_file.get("evidence") or []:
        if isinstance(item, dict) and item.get("evidence_id"):
            evidence_by_id[str(item["evidence_id"])] = item

    citations: list[dict[str, Any]] = []
    mappings = report.get("legal_mappings") or []
    if not isinstance(mappings, list):
        mappings = []

    for index, mapping in enumerate(mappings[:12]):
        if not isinstance(mapping, dict):
            continue
        evidence_ids = [str(x) for x in (mapping.get("evidence_ids") or []) if x][:6]
        finding_ids = [str(x) for x in (mapping.get("finding_ids") or []) if x][:6]
        article = str(mapping.get("article") or "").strip()
        relevance = str(mapping.get("relevance_note") or "").strip()
        snippet = ""
        source_system = "LEGAL_RAG"
        source_record_id = ""
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(evidence_id) or {}
            payload = (
                evidence.get("payload")
                if isinstance(evidence.get("payload"), dict)
                else {}
            )
            if not article and payload.get("article"):
                article = str(payload["article"]).strip()
            if payload.get("snippet") and not snippet:
                snippet = " ".join(str(payload["snippet"]).split())[:360]
            if evidence.get("source_system"):
                source_system = str(evidence["source_system"])
            if evidence.get("source_record_id") and not source_record_id:
                source_record_id = str(evidence["source_record_id"])
        if not article and not evidence_ids:
            continue
        citations.append(
            {
                "id": f"c{index + 1}",
                "label": (article or f"Citation {index + 1}")[:120],
                "source_system": source_system,
                "source_record_id": source_record_id[:200],
                "relevance_note": relevance[:300],
                "snippet": snippet,
                "evidence_ids": evidence_ids,
                "finding_ids": finding_ids,
            }
        )

    # Fallback: legal citation findings even if report mappings empty
    if not citations:
        for index, finding in enumerate(case_file.get("findings") or []):
            if not isinstance(finding, dict):
                continue
            if finding.get("finding_type") != "LEGAL_CITATION":
                continue
            evidence_ids = [
                str(x) for x in (finding.get("evidence_ids") or []) if x
            ][:6]
            payload: dict[str, Any] = {}
            source_system = "LEGAL_RAG"
            for evidence_id in evidence_ids:
                evidence = evidence_by_id.get(evidence_id) or {}
                if isinstance(evidence.get("payload"), dict):
                    payload = evidence["payload"]
                if evidence.get("source_system"):
                    source_system = str(evidence["source_system"])
                break
            article = str(payload.get("article") or finding.get("summary") or "").strip()
            if not article:
                continue
            citations.append(
                {
                    "id": f"c{index + 1}",
                    "label": article[:120],
                    "source_system": source_system,
                    "source_record_id": str(
                        (evidence_by_id.get(evidence_ids[0]) or {}).get(
                            "source_record_id"
                        )
                        or ""
                    )[:200],
                    "relevance_note": str(finding.get("summary") or "")[:300],
                    "snippet": " ".join(str(payload.get("snippet") or "").split())[:360],
                    "evidence_ids": evidence_ids,
                    "finding_ids": [],
                }
            )
            if len(citations) >= 12:
                break
    return citations


def summarize_result(final_state: Any, case_id: str) -> dict[str, Any]:
    """Durable investigation summary for tickets + FE final output (with citations)."""

    if not isinstance(final_state, dict):
        return {"case_id": case_id, "phase": None, "citations": []}

    report = final_state.get("report") or {}
    if not isinstance(report, dict):
        report = {}
    case_file = final_state.get("case_file") or {}
    if not isinstance(case_file, dict):
        case_file = {}

    rationale = report.get("risk_rationale")
    if isinstance(rationale, str):
        rationale = " ".join(rationale.split())[:1_200]

    summary = report.get("summary")
    if isinstance(summary, str):
        summary = " ".join(summary.split())[:800]

    agent_outputs = final_state.get("agent_outputs") or {}
    agent_statuses: dict[str, str] = {}
    if isinstance(agent_outputs, dict):
        for name, output in agent_outputs.items():
            if isinstance(output, dict) and output.get("status") is not None:
                agent_statuses[str(name)] = str(output["status"])

    errors = final_state.get("errors") or []
    if not isinstance(errors, list):
        errors = [str(errors)]

    overall = report.get("overall_risk_level")
    recommended = report.get("recommended_action")
    citations = _extract_citations(report, case_file)
    return {
        "case_id": case_id,
        "phase": final_state.get("phase"),
        "title": report.get("title"),
        "summary": summary,
        "overall_risk_level": overall,
        "recommended_action": recommended,
        "risk_rationale": rationale,
        "legal_mappings": (report.get("legal_mappings") or [])[:12]
        if isinstance(report.get("legal_mappings"), list)
        else [],
        "citations": citations,
        "agent_statuses": agent_statuses,
        "errors": [str(item) for item in errors[:10]],
        "is_laundering_suspect": is_laundering_suspect(overall, recommended),
    }


def is_laundering_suspect(
    overall_risk_level: Any = None, recommended_action: Any = None
) -> bool:
    """Heuristic: HIGH/CRITICAL (or escalate-style actions) need analyst APPROVE/REJECT."""

    risk = str(overall_risk_level or "").strip().upper()
    if risk in {"HIGH", "CRITICAL", "CONFIRMED", "SUSPICIOUS", "SEVERE"}:
        return True
    action = str(recommended_action or "").strip().upper()
    if any(token in action for token in ("ESCALATE", "SAR", "STR", "BLOCK", "FREEZE")):
        return True
    return False

