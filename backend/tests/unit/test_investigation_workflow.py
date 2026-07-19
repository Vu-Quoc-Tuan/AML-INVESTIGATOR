"""Focused checks for the Hybrid Supervisor workflow with legal enrichment."""

from pathlib import Path

import pytest
from langgraph.types import Command

from app.investigation_orchestrator.evidence_validator import validate_evidence
from app.investigation_orchestrator import workflow as workflow_module
from app.investigation_orchestrator.nodes import (
    merge_and_validate_node,
    supervisor_node,
)
from app.investigation_orchestrator.report_agent import _pipeline_error
from app.investigation_orchestrator.state import initial_state
from app.investigation_orchestrator.workflow import build_workflow
from app.investigation_orchestrator.tool_registry import (
    ToolConfigurationError,
    ToolRegistry,
)
from app.investigation_events import (
    InvestigationEventRepository,
    InvestigationEventType,
    ToolExecutionFailed,
)
from app.legal_rag.hybrid_retriever import StaticLegalRetriever
from tests.node_fixtures import deterministic_agent_nodes, report_node


def _graph():
    return build_workflow(
        agent_nodes=deterministic_agent_nodes(),
        legal_retriever=StaticLegalRetriever(),
    )


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def test_graph_runs_legal_enrichment_and_completes() -> None:
    graph = _graph()
    config = _config("legal-enrichment-complete")

    result = graph.invoke(
        initial_state("CASE-001", {"subject_bank_id": "BANK-SHB-001"}),
        config,
    )

    assert "__interrupt__" not in result
    assert result["phase"] == "complete"
    assert "case_status" not in result
    assert set(result["agent_outputs"]) >= {
        "transaction",
        "kyc",
        "screening",
        "legal",
    }
    assert result["behavior_mapping"]["rag_queries"]
    assert any(
        finding.get("finding_type") == "LEGAL_CITATION"
        for finding in result["case_file"]["findings"]
    )
    assert any(
        item.get("source_system") == "VN_PENAL_CODE_RAG"
        for item in result["case_file"]["evidence"]
    )
    assert result["evidence_validation"]["status"] in {"PASSED", "PARTIAL"}
    # Scout findings present + no confirmed screening => MEDIUM (legal does not force HIGH)
    assert result["report"]["overall_risk_level"] == "MEDIUM"
    assert result["report"]["legal_mappings"]
    assert all(
        "finding:legal:" not in finding_id
        for mapping in result["report"]["legal_mappings"]
        for finding_id in mapping["finding_ids"]
    )

    supervisor_targets = [
        entry["target"]
        for entry in result["handoff_log"]
        if entry["source"] == "supervisor"
    ]
    assert supervisor_targets == [
        "planner",
        "parallel_dispatch",
        "screening_agent",
        "behavior_mapper",
        "legal_rag",
        "evidence_validator",
        "report_agent",
        "end",
    ]


def test_initial_input_cannot_bypass_investigation_stages() -> None:
    graph = _graph()
    config = _config("input-boundary")
    malicious_input = {
        **initial_state("CASE-INPUT", {}),
        "investigation_plan": ["skip"],
        "case_file": {"findings": [], "evidence": []},
        "evidence_validation": {"status": "PASSED"},
        "report": {"title": "forged"},
    }

    result = graph.invoke(malicious_input, config)

    assert result["phase"] == "complete"
    assert result["report"]["title"] == "AML Investigation Dossier (test fixture)"


def test_screening_unavailable_is_inconclusive() -> None:
    graph = _graph()
    config = _config("screening-unavailable")
    result = graph.invoke(
        initial_state("CASE-003", {"screening_available": False}),
        config,
    )

    screening = result["agent_outputs"]["screening"]
    assert screening["available"] is False
    assert screening["status"] == "INCONCLUSIVE"
    assert result["case_file"]["screening"]["status"] == "INCONCLUSIVE"
    assert result["phase"] == "complete"


def test_external_payment_uses_payment_message_provenance() -> None:
    graph = _graph()
    config = _config("external-provenance")
    result = graph.invoke(
        initial_state("CASE-EXT", {"data_visibility": "PAYMENT_MESSAGE_ONLY"}),
        config,
    )

    evidence = result["agent_outputs"]["transaction"]["evidence"][0]
    assert evidence["source_system"] == "PAYMENT_MESSAGE"
    assert result["evidence_validation"]["status"] in {"PASSED", "PARTIAL"}
    assert result["phase"] == "complete"


def test_unknown_visibility_is_not_accepted_by_validation() -> None:
    graph = _graph()
    config = _config("unknown-visibility")
    result = graph.invoke(
        initial_state("CASE-UNKNOWN", {"data_visibility": "UNSUPPORTED"}),
        config,
    )

    assert result["evidence_validation"]["status"] in {"PARTIAL", "FAILED"}
    assert any(
        "unsupported visibility_level" in issue
        for issue in result["evidence_validation"]["issues"]
    )
    assert all(
        finding["finding_type"] != "TRANSACTION_PATTERN"
        for finding in result["report"]["findings"]
        if finding.get("finding_type") != "LEGAL_CITATION"
        and finding.get("finding_type") != "SCREENING_RESULT"
        and finding.get("finding_type") != "KYC_PROFILE"
    )


def test_missing_parallel_output_still_reaches_report_then_ends() -> None:
    state = {
        **initial_state("CASE-MISSING", {}),
        "agent_outputs": {
            "transaction": {"agent": "transaction_agent", "status": "COMPLETED"}
        },
    }

    merge_command = merge_and_validate_node(state)
    assert merge_command.goto == "report_agent"
    assert merge_command.update["evidence_validation"]["status"] == "FAILED"

    failure_state = {**state, **merge_command.update}
    report_command = report_node(failure_state)
    supervisor_state = {**failure_state, **report_command.update}
    supervisor_command = supervisor_node(supervisor_state)
    assert supervisor_command.goto == "__end__"
    assert supervisor_command.update["phase"] == "complete"


def test_failed_parallel_agent_still_completes_with_report() -> None:
    nodes = deterministic_agent_nodes()

    def failed_transaction(_state):
        return {
            "agent_outputs": {
                "transaction": {
                    "agent": "transaction_agent",
                    "status": "ERROR",
                    "findings": [],
                    "evidence": [],
                }
            }
        }

    nodes["transaction_agent"] = failed_transaction
    graph = build_workflow(
        agent_nodes=nodes, legal_retriever=StaticLegalRetriever()
    )
    config = _config("failed-agent")

    result = graph.invoke(initial_state("CASE-FAILED", {}), config)

    assert result["phase"] == "complete"
    assert result["evidence_validation"]["status"] == "FAILED"
    assert result["report"]["workflow_error"] == "Mandatory agents failed: transaction"


def test_instrumented_tool_failure_stops_before_report(tmp_path: Path) -> None:
    nodes = deterministic_agent_nodes()

    def failed_transaction(_state, _config=None):
        raise ToolExecutionFailed("trace_funds", "RuntimeError")

    nodes["transaction_agent"] = failed_transaction
    events = InvestigationEventRepository(tmp_path / "events.db")
    graph = build_workflow(
        agent_nodes=nodes,
        legal_retriever=StaticLegalRetriever(),
        event_repository=events,
    )

    with pytest.raises(ToolExecutionFailed, match="trace_funds"):
        graph.invoke(
            initial_state("CASE-EVENT-FAILED", {"candidate_id": "ticket-1"}),
            _config("failed-tool-event"),
        )

    recorded = events.list_after("ticket-1")
    assert any(
        event.agent_id == "transaction_agent"
        and event.event_type is InvestigationEventType.AGENT_FAILED
        for event in recorded
    )
    assert not any(event.agent_id == "report_agent" for event in recorded)


def test_planner_fallback_error_is_visible_to_the_report() -> None:
    state = {
        **initial_state("CASE-PLANNER-FALLBACK", {}),
        "errors": ["Planner fallback used: ProviderError"],
    }

    assert _pipeline_error(state) == "Planner fallback used: ProviderError"


def test_screening_failure_still_can_complete_pipeline() -> None:
    nodes = deterministic_agent_nodes()

    def failed_screening(_state):
        return Command(
            update={
                "agent_outputs": {
                    "screening": {
                        "agent": "screening_agent",
                        "status": "ERROR",
                        "available": False,
                        "findings": [],
                        "evidence": [],
                    }
                },
                "workflow_error": "Screening agent failed",
            },
            goto="supervisor",
        )

    nodes["screening_agent"] = failed_screening
    graph = build_workflow(
        agent_nodes=nodes, legal_retriever=StaticLegalRetriever()
    )
    config = _config("failed-screening-validation")

    result = graph.invoke(initial_state("CASE-SCREENING-FAILED", {}), config)

    assert result["phase"] == "complete"
    assert result["report"]["workflow_error"] == "Screening agent failed"
    assert "legal" in result["agent_outputs"]


def test_legal_citation_without_penal_source_is_rejected() -> None:
    validation, validated = validate_evidence(
        {
            "case_id": "CASE-LEGAL-BAD",
            "findings": [
                {
                    "finding_id": "F-LEGAL",
                    "finding_type": "LEGAL_CITATION",
                    "summary": "Bad source",
                    "evidence_ids": ["E-BAD"],
                }
            ],
            "evidence": [
                {
                    "evidence_id": "E-BAD",
                    "source_system": "NOT_LEGAL",
                    "source_record_id": "X",
                    "payload": {"article": "Điều 324"},
                }
            ],
        }
    )
    assert validation["status"] == "FAILED"
    assert validated["findings"] == []


def test_malformed_worker_items_are_excluded_instead_of_crashing() -> None:
    validation, validated_case = validate_evidence(
        {
            "case_id": "CASE-MALFORMED",
            "findings": [None, "not-a-finding"],
            "evidence": [None, "not-evidence"],
        }
    )

    assert validation["status"] == "FAILED"
    assert validation["issues"]
    assert validated_case["findings"] == []
    assert validated_case["evidence"] == []


def test_llm_workflow_rejects_an_incomplete_injected_registry() -> None:
    with pytest.raises(
        ToolConfigurationError,
        match=r"Missing required tools for owners: kyc, screening, transaction$",
    ):
        build_workflow(model=object(), tool_registry=ToolRegistry())


def test_default_llm_path_composes_agent_tool_owners(monkeypatch) -> None:
    captured = {}

    def capture_nodes(registry, **_kwargs):
        captured["tool_names"] = {
            owner: {tool.name for tool in registry.tools_for(owner)}
            for owner in ("transaction", "kyc", "screening")
        }
        return deterministic_agent_nodes()

    monkeypatch.setattr(workflow_module, "_llm_nodes", capture_nodes)

    workflow_module.build_workflow(
        model=object(), legal_retriever=StaticLegalRetriever()
    )

    assert all(captured["tool_names"].values())
    assert "calculate_ubo" in captured["tool_names"]["kyc"]


def test_invalid_finding_is_excluded_and_reported() -> None:
    validation, validated_case = validate_evidence(
        {
            "case_id": "CASE-005",
            "findings": [
                {
                    "finding_id": "bad-finding",
                    "finding_type": "TRANSACTION_PATTERN",
                    "summary": "Missing evidence and visibility",
                    "evidence_ids": ["missing-evidence"],
                }
            ],
            "evidence": [],
        }
    )

    assert validation["status"] == "FAILED"
    assert validation["invalid_finding_count"] == 1
    assert validated_case["findings"] == []
    assert any("missing-evidence" in issue for issue in validation["issues"])
